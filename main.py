# main.py
# ============================================================
# SPORTALYZE — Servidor FastAPI principal
# Arranca con: python main.py
# Docs en:    http://localhost:8000/docs
# ============================================================

import asyncio
import logging
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path
from cachetools import TTLCache
from backend.config import PORT, ENV, LEAGUES
from backend.temporada import nombre_temporada, temporada_actual
from backend.errors import FuenteNoDisponible
from backend.scrapers.football_data import FaltaLaClave, LimiteAlcanzado

# ── Logging ───────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO if ENV == "production" else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sportalyze")

# ── App ───────────────────────────────────────────────────
app = FastAPI(
    title="SPORTALYZE API",
    description="🏆 Plataforma profesional de análisis futbolístico",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Importar scrapers y ML ────────────────────────────────
from backend.scrapers.football_data import football_client
from backend.scrapers.understat import (
    get_league_players, get_player_shots,
    get_match_shots, get_league_teams_xg,
    get_league_fixtures, get_match_roster, _normaliza,
)
from backend.ml import informe_liga as inf_liga
from backend.ml import onoff
from backend.ml.emparejar import emparejar_con_motivo
from backend.ml.emparejar_jugadores import (
    MOTIVOS as MOTIVOS_JUGADOR, emparejar_jugador,
)
from backend.scrapers.transfermarkt import (
    get_player_injuries, build_injury_features,
)
from backend.ml.scouting import run_scouting_pipeline, find_similar_players
from backend.ml import simulador as sim
from backend.ml import informe as inf
from backend.ml.puntuar import PuestoSinDatos
from backend.scrapers import statsbomb as sb
from backend.ml.injury_prediction import build_player_risk_features, calculate_injury_risk


# ════════════════════════════════════════════════════════
# RUTAS — COMPETICIONES
# ════════════════════════════════════════════════════════

@app.get("/api/competitions")
async def get_competitions():
    """Lista todas las competiciones con banderas y colores"""
    try:
        comps = await football_client.get_competitions()
        return {"competitions": comps, "total": len(comps)}
    except Exception as e:
        # Fallback: retornar las ligas que conocemos
        fallback = [
            {**{"id": i, "code": k, "name": v["name"],
                "country": v["country"], "flag": v["flag"],
                "color": v["color"], "emblem": None},
            } for i, (k, v) in enumerate(LEAGUES.items())
        ]
        return {"competitions": fallback, "total": len(fallback), "source": "local"}


# ════════════════════════════════════════════════════════
# RUTAS — CLASIFICACIONES
# ════════════════════════════════════════════════════════

@app.get("/api/standings/{competition_code}")
async def get_standings(competition_code: str):
    """
    Clasificación en tiempo real de una liga.
    Incluye xG de equipos desde Understat.
    """
    try:
        standings = await football_client.get_standings(competition_code.upper())
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

    # ── El xG por equipo, de Understat ──
    #
    # Esto estaba en un `except Exception: pass`. Probándolo con datos
    # reales salieron CERO equipos con xG en las veinte filas, y no
    # había forma de saber por qué: el fallo se lo comía el except y la
    # columna se quedaba vacía como si Understat no tuviera el dato.
    #
    # Ahora el fallo se registra y se dice en la respuesta. Una columna
    # vacía sin explicación es lo mismo que un número inventado: el que
    # mira no puede saber qué está viendo.
    aviso_xg = None
    try:
        xg_data = await get_league_teams_xg(competition_code.upper())
        xg_map = {t["team"]: t for t in xg_data}
        for row in standings["table"]:
            team_key = next(
                (k for k in xg_map if k.lower() in row["team_name"].lower()
                 or row["team_name"].lower() in k.lower()), None
            )
            if team_key:
                row["xG"]  = xg_map[team_key].get("xG", None)
                row["xGA"] = xg_map[team_key].get("xGA", None)

        con_xg = sum(1 for r in standings["table"] if r.get("xG") is not None)
        if not xg_data:
            aviso_xg = ("Understat no ha devuelto datos de equipo para esta "
                        "liga, así que la columna de xG va vacía.")
        elif con_xg == 0:
            aviso_xg = (
                f"Understat ha devuelto {len(xg_data)} equipos pero ninguno "
                f"casa por nombre con los de football-data, así que la "
                f"columna de xG va vacía. Ejemplos de cómo los llama cada "
                f"uno: Understat «{list(xg_map)[:3]}», football-data "
                f"«{[r['team_name'] for r in standings['table'][:3]]}».")
        elif con_xg < len(standings["table"]):
            aviso_xg = (f"{con_xg} de {len(standings['table'])} equipos con "
                        f"xG: a los demás no les encuentro la equivalencia "
                        f"de nombre con Understat.")
    except Exception as e:
        logger.warning("No he podido añadir el xG de Understat: %s", e)
        aviso_xg = f"No he podido traer el xG de Understat: {e}"
    if aviso_xg:
        standings["aviso_xg"] = aviso_xg
    return standings


# ════════════════════════════════════════════════════════
# RUTAS — PARTIDOS
# ════════════════════════════════════════════════════════

@app.get("/api/matches/today")
async def get_today_matches():
    """Partidos de hoy con marcadores live"""
    try:
        matches = await football_client.get_matches_today()
        return {"matches": matches, "total": len(matches)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/matches/{competition_code}")
async def get_competition_matches(
    competition_code: str,
    status: str = Query(None, description="FINISHED | SCHEDULED | LIVE"),
    limit: int = Query(20, ge=1, le=50),
):
    """Partidos de una competición"""
    try:
        matches = await football_client.get_competition_matches(
            competition_code.upper(), status=status, limit=limit
        )
        return {"matches": matches, "total": len(matches)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ════════════════════════════════════════════════════════
# RUTAS — EQUIPOS
# ════════════════════════════════════════════════════════

@app.get("/api/teams/{team_id}")
async def get_team(team_id: int):
    """Perfil completo del equipo con plantilla"""
    try:
        team = await football_client.get_team(team_id)
    except LimiteAlcanzado as e:
        # 429 y no 503: "espera un minuto" no es lo mismo que "roto".
        raise HTTPException(status_code=429, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

    # Los partidos recientes son un extra. Si no caben en la cuota, se
    # devuelve el equipo igual con un aviso, en vez de tirar la ficha
    # entera por algo secundario.
    aviso = None
    try:
        recent = await football_client.get_team_matches(team_id, limit=10)
    except LimiteAlcanzado as e:
        recent, aviso = [], str(e)
    except Exception:
        recent, aviso = [], "No se han podido cargar los últimos partidos."
    salida = {**team, "recent_matches": recent}
    if aviso:
        salida["aviso"] = aviso
    return salida


@app.get("/api/teams/{team_id}/matches")
async def get_team_matches_route(
    team_id: int,
    limit: int = Query(10, ge=1, le=20)
):
    """Últimos partidos de un equipo"""
    try:
        matches = await football_client.get_team_matches(team_id, limit=limit)
        return {"matches": matches, "total": len(matches)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ════════════════════════════════════════════════════════
# RUTAS — GOLEADORES
# ════════════════════════════════════════════════════════

@app.get("/api/scorers/{competition_code}")
async def get_top_scorers(
    competition_code: str,
    limit: int = Query(20, ge=5, le=50),
):
    """Top goleadores de una competición"""
    try:
        scorers = await football_client.get_top_scorers(
            competition_code.upper(), limit=limit
        )
        return {"scorers": scorers, "total": len(scorers)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ════════════════════════════════════════════════════════
# RUTAS — EL SIMULADOR
# ════════════════════════════════════════════════════════

# Simular diez mil temporadas cuesta un segundo y medio de CPU. La
# caché del cliente guarda los PARTIDOS diez minutos; esta guarda la
# SIMULACIÓN el mismo rato, para no repetir el cálculo en cada visita.
_simulaciones = TTLCache(maxsize=8, ttl=600)


@app.get("/api/simulador/{competition_code}")
async def get_simulador(competition_code: str):
    """Rangos de posición final: ajusta fuerzas y simula lo que queda.

    Una sola llamada a football-data trae el calendario entero, jugado y
    por jugar. El motor está en backend/ml/simulador.py.

    Esta ruta se NIEGA a contestar cuando los datos no permiten simular
    honestamente, y dice por qué en `motivo`:

      calendario_incompleto  la fuente no ha dado la temporada entera
      datos_desfasados       hay partidos jugados sin resultado todavía
      demasiado_pronto       hay tan poco jugado que no diría nada
      fuente_caida           football-data no ha contestado
      limite_alcanzado       se han gastado las 10 peticiones del minuto

    Devolver un número en cualquiera de esos casos sería peor que no
    devolver ninguno: parecería de hoy sin serlo.
    """
    codigo = competition_code.upper()
    if codigo in _simulaciones:
        return _simulaciones[codigo]

    try:
        crudos = await football_client.get_competition_season(codigo)
    except FaltaLaClave as e:
        raise HTTPException(status_code=503, detail={
            "motivo": "falta_la_clave", "detalle": str(e)})
    except LimiteAlcanzado as e:
        raise HTTPException(status_code=429, detail={
            "motivo": "limite_alcanzado", "detalle": str(e)})
    except Exception as e:
        raise HTTPException(status_code=503, detail={
            "motivo": "fuente_caida", "detalle": str(e)})

    nombre = LEAGUES.get(codigo, {}).get("name", codigo)
    try:
        # En un hilo: son 1,5 s de numpy y si no bloquean el servidor.
        edicion = await asyncio.to_thread(sim.edicion, crudos, codigo, nombre)
    except sim.CalendarioIncompleto as e:
        raise HTTPException(status_code=503, detail={
            "motivo": "calendario_incompleto", "detalle": str(e)})
    except sim.DatosDesfasados as e:
        raise HTTPException(status_code=503, detail={
            "motivo": "datos_desfasados", "detalle": str(e)})
    except sim.DemasiadoPronto as e:
        raise HTTPException(status_code=503, detail={
            "motivo": "demasiado_pronto", "detalle": str(e)})

    _simulaciones[codigo] = edicion
    return edicion


# ════════════════════════════════════════════════════════
# RUTAS — EL INFORME POST-PARTIDO
# ════════════════════════════════════════════════════════
#
# Sobre StatsBomb Open Data, y eso no es un detalle: el cuaderno del
# que viene este informe lee los eventos del HTML de WhoScored, que por
# dentro son de Opta. Eso vale para mirar un partido en tu ordenador y
# NO vale para publicarlo — es licencia comercial, y las condiciones de
# WhoScored prohíben extraerlo y redistribuirlo.
#
# StatsBomb Open Data es gratis, está publicado para esto y sólo pide
# que se diga de dónde viene. Son ~3.500 partidos de verdad.


@app.get("/api/informe/competiciones")
async def get_informe_competiciones():
    """Qué competiciones y temporadas hay con datos abiertos."""
    try:
        datos = await sb.competiciones()
    except FuenteNoDisponible as e:
        raise HTTPException(status_code=503, detail={
            "motivo": "fuente_caida", "detalle": str(e)})
    return {"competiciones": datos, "total": len(datos),
            "fuente": "StatsBomb Open Data"}


@app.get("/api/informe/partidos/{competition_id}/{season_id}")
async def get_informe_partidos(competition_id: int, season_id: int):
    """Los partidos de una competición y temporada, lo justo para el menú."""
    try:
        datos = await sb.partidos(competition_id, season_id)
    except sb.PartidoNoEstaAbierto:
        raise HTTPException(status_code=404, detail={
            "motivo": "no_esta_abierto",
            "detalle": "esa competición y temporada no están en los datos abiertos"})
    except FuenteNoDisponible as e:
        raise HTTPException(status_code=503, detail={
            "motivo": "fuente_caida", "detalle": str(e)})

    ligero = [{
        "match_id": m["match_id"],
        "fecha": m.get("match_date", ""),
        "local": m["home_team"]["home_team_name"],
        "visitante": m["away_team"]["away_team_name"],
        "goles_local": m.get("home_score"),
        "goles_visitante": m.get("away_score"),
        "fase": (m.get("competition_stage") or {}).get("name", ""),
    } for m in datos]
    ligero.sort(key=lambda m: (m["fecha"], m["local"]))
    return {"partidos": ligero, "total": len(ligero)}


@app.get("/api/informe/{match_id}")
async def get_informe(match_id: int):
    """El informe entero de un partido.

    Se niega, con su motivo, cuando no puede hacerlo bien:

      no_esta_abierto    ese partido no está en los datos abiertos
      partido_incompleto los eventos no dan para un informe, o el
                         marcador que sale no cuadra con el oficial
      fuente_caida       StatsBomb no ha contestado
    """
    try:
        return await sb.informe_de(match_id)
    except sb.PartidoNoEstaAbierto as e:
        raise HTTPException(status_code=404, detail={
            "motivo": "no_esta_abierto", "detalle": str(e)})
    except inf.PartidoIncompleto as e:
        raise HTTPException(status_code=503, detail={
            "motivo": "partido_incompleto", "detalle": str(e)})
    except FuenteNoDisponible as e:
        raise HTTPException(status_code=503, detail={
            "motivo": "fuente_caida", "detalle": str(e)})


# ════════════════════════════════════════════════════════
# RUTAS — JUGADORES (Understat)
# ════════════════════════════════════════════════════════

@app.get("/api/players/{competition_code}")
async def get_league_players_stats(
    competition_code: str,
    season: int = Query(None, description="año en que empieza la temporada; "
                        "por defecto, la que se está jugando"),
    position: str = Query(None),
    min_minutes: int = Query(200, ge=0),
    # Antes: Query(99, ge=15, le=50). El valor por defecto incumplía su
    # propio máximo, así que llamar a la ruta sin parámetros devolvía un
    # 422 contra sus propias reglas. 50 es "sin filtro de edad" de hecho.
    max_age: int = Query(50, ge=15, le=50),
    limit: int = Query(100, ge=10, le=500),
):
    """
    Jugadores de una liga con estadísticas xG reales (Understat).
    Filtros: posición, minutos mínimos, edad máxima.
    """
    # La temporada, resuelta aquí para poder devolverla: quien mire la
    # respuesta tiene que saber de qué año son las cifras. Estuvo
    # clavada a 2024 en cinco rutas, así que Cartas, Scouting y
    # Comparador enseñaban la 2024/25 mientras la clasificación y el
    # Simulador iban de la temporada en curso.
    season = season if season is not None else temporada_actual()
    try:
        players = await get_league_players(competition_code.upper(), season)
    except FuenteNoDisponible as e:
        raise HTTPException(status_code=503, detail=str(e))

    # Cuántos minutos lleva el que más ha jugado. Va en la respuesta
    # porque sin eso el filtro de minutos no se puede interpretar: 400
    # minutos es un filtro suave en una temporada entera y durísimo en
    # octubre, cuando el que más lleva no pasa de 720.
    minutos_maximos = max((p.get("time", 0) or 0 for p in players), default=0)

    # Filtros
    if position:
        players = [p for p in players if p.get("position", "").upper() == position.upper()]
    players = [p for p in players if p.get("time", 0) >= min_minutes]

    # ── Puntuación ──
    #
    # Antes aquí se llamaba a score_player(p, pos[:2]) con la cadena de
    # Understat en crudo: para «F M S» eso era «F », que no es ningún
    # puesto, así que caía en el por defecto y puntuaba a un delantero
    # con las métricas de centrocampista. Y las de centrocampista no
    # las da Understat, así que salía el suelo.
    #
    # Ahora se agrupa por puesto de verdad y se puntúa cada grupo
    # contra SU grupo, que es lo único que hace comparable un
    # percentil. Defensas y porteros se quedan sin nota, con su motivo.
    from backend.ml.puntuar import puntuar, PuestoSinDatos
    from backend.ml.scouting import puesto as puesto_de

    por_puesto = {}
    for p in players:
        por_puesto.setdefault(puesto_de(p.get("position", "")), []).append(p)

    avisos, sin_nota = [], {}
    for pst, grupo in por_puesto.items():
        try:
            ficha = puntuar(grupo, pst)
            avisos.extend(ficha.get("avisos", []))
        except PuestoSinDatos as e:
            sin_nota[pst] = e.motivo
            for p in grupo:
                p["score"] = None
        except ValueError as e:
            sin_nota[pst] = str(e)
            for p in grupo:
                p["score"] = None

    # ── EL RECORTE, POR PUESTO ─────────────────────────────────
    #
    # Antes esto ordenaba por nota —con los sin nota al final— y luego
    # cortaba por `limit`. Probándolo con datos reales de La Liga
    # salieron «200 con nota, 0 sin nota»: como hay más de 200
    # jugadores con nota, los defensas y porteros se caían ENTEROS del
    # corte. O sea que en la pantalla de Cartas de La Liga no aparecía
    # ni un central.
    #
    # Ahora el límite se reparte entre los puestos en proporción a lo
    # que pesa cada uno, y dentro de cada puesto se cogen los mejores.
    # Así siempre hay de todo, y «los mejores» sigue queriendo decir
    # algo dentro de cada puesto.
    for grupo in por_puesto.values():
        grupo.sort(key=lambda x: (x.get("score") is None,
                                  -(x.get("score") or 0)))

    total = len(players)
    recortados = []
    for pst, grupo in por_puesto.items():
        cupo = max(1, round(limit * len(grupo) / total)) if total else 0
        recortados.extend(grupo[:cupo])
    recortados.sort(key=lambda x: (x.get("score") is None,
                                   -(x.get("score") or 0)))
    recortados = recortados[:limit]

    reparto = {}
    for p in recortados:
        clave = puesto_de(p.get("position", ""))
        reparto[clave] = reparto.get(clave, 0) + 1

    return {
        "players": recortados,
        "reparto_por_puesto": reparto,
        "total": len(players),
        "competition": competition_code.upper(),
        "season": season,
        "temporada": nombre_temporada(season),
        "minutos_maximos": minutos_maximos,
        "avisos": avisos,
        "puestos_sin_nota": sin_nota,
    }


@app.get("/api/player/{player_id}/shots")
async def get_player_shot_map(
    player_id: str,
    season: int = Query(None, description="año en que empieza la temporada; "
                        "sin él, TODOS los tiros de su carrera"),
):
    """Disparos de un jugador con coordenadas para el mapa de tiros.

    LO DE LA TEMPORADA NO ES UN ADORNO. Understat devuelve aquí todos
    los tiros de la CARRERA del jugador. Probándolo con datos reales,
    Raphinha salía con 550 tiros —hasta un Brest-Rennes de 2019— en una
    ficha cuya cabecera decía «590 minutos en 8 partidos» y «26 tiros».

    O sea que el mapa y los números de arriba contaban temporadas
    distintas, y el «goles menos xG» de debajo del mapa se calculaba
    sobre siete años. Eso no es un mapa mal pintado: es otra pregunta
    contestada sin avisar.

    Con `season` se devuelven sólo los de esa temporada. Y vaya siempre
    el reparto por temporadas y el total de la carrera, para que quien
    mire la respuesta sepa qué se ha quedado fuera. Filtrar en silencio
    es tan malo como no filtrar.
    """
    try:
        todos = await get_player_shots(player_id)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

    por_temporada = {}
    for t in todos:
        clave = str(t.get("season", ""))
        por_temporada[clave] = por_temporada.get(clave, 0) + 1

    if season is None:
        return {"shots": todos, "total": len(todos),
                "temporada": None, "total_carrera": len(todos),
                "por_temporada": por_temporada}

    shots = [t for t in todos if str(t.get("season", "")) == str(season)]
    return {
        "shots": shots,
        "total": len(shots),
        "temporada": nombre_temporada(season),
        "total_carrera": len(todos),
        "por_temporada": por_temporada,
    }


# ════════════════════════════════════════════════════════
# RUTAS — CON ÉL Y SIN ÉL
# ════════════════════════════════════════════════════════
#
# La respuesta a "¿y los defensas?". Understat publica tiros, así que
# de un central no hay entradas ni intercepciones y su ficha salía sin
# nota. Las fuentes que sí lo publican son datos de Opta con licencia.
#
# Pero no hace falta ver lo que hace el defensa para medir algo real:
# basta con saber cuándo estaba en el campo. Entonces se puede contar
# cuánto xG encaja su equipo mientras él juega, y cuánto cuando no.
#
# backend/ml/minutos.py explica cómo se reconstruyen los tramos, y
# backend/ml/onoff.py qué mide esto y qué no.


@app.get("/api/con-el-sin-el/{competition_code}/{team_id}")
async def con_el_sin_el(competition_code: str, team_id: int,
                        season: int = Query(None)):
    """Cuánto xG hace y encaja el equipo con cada jugador en el campo.

    TARDA. Son dos consultas a Understat por partido jugado —los tiros
    y la alineación—, así que la primera vez de cada equipo se va a
    veinte o treinta segundos. Después está en la caché.
    """
    codigo = competition_code.upper()
    try:
        equipo = await football_client.get_team(team_id)
    except LimiteAlcanzado as e:
        raise HTTPException(status_code=429, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

    nombre = equipo.get("name", "")
    clave = _normaliza(nombre)

    try:
        calendario = await get_league_fixtures(codigo, season)
    except FuenteNoDisponible as e:
        raise HTTPException(status_code=503, detail={
            "motivo": "fuente_caida", "detalle": str(e)})

    suyos = [c for c in calendario if c.get("jugado") and
             clave in (c.get("clave_local"), c.get("clave_visitante"))]

    if not suyos:
        raise HTTPException(status_code=404, detail={
            "motivo": "sin_partidos",
            "detalle": f"Understat no tiene partidos jugados de "
                       f"{nombre} en esta liga. Puede que el equipo esté "
                       f"escrito de otra forma en las dos fuentes."})

    partidos, fallos = [], []
    for c in suyos:
        en_casa = c.get("clave_local") == clave
        try:
            tiros = await get_match_shots(c["match_id"])
            roster = await get_match_roster(c["match_id"])
        except FuenteNoDisponible as e:
            fallos.append(f"{c['local']}–{c['visitante']}: {e}")
            continue

        lado = "local" if en_casa else "visitante"
        otro = "visitante" if en_casa else "local"
        crudos_f = tiros.get("home_shots" if en_casa else "away_shots", [])
        crudos_c = tiros.get("away_shots" if en_casa else "home_shots", [])
        partidos.append({
            "etiqueta": f"{c['local']} {c['goles_local']}-"
                        f"{c['goles_visitante']} {c['visitante']}",
            "jugadores": roster.get(lado, []),
            # minutos+xg es lo único que hace falta, y así no se
            # arrastran las coordenadas de cada tiro para nada
            "tiros_favor": [{"minuto": t.get("minute", 0),
                             "xg": t.get("xG", 0)} for t in crudos_f],
            "tiros_contra": [{"minuto": t.get("minute", 0),
                              "xg": t.get("xG", 0)} for t in crudos_c],
        })

    if not partidos:
        raise HTTPException(status_code=503, detail={
            "motivo": "fuente_caida",
            "detalle": " · ".join(fallos) or "No he podido traer ningún partido."})

    salida = onoff.acumular(partidos)
    salida["equipo_nombre"] = nombre
    salida["competicion"] = codigo
    salida["temporada"] = nombre_temporada(season or temporada_actual())
    if fallos:
        salida.setdefault("descartados", []).extend(
            {"partido": f, "motivo": "fuente_caida", "detalle": ""} for f in fallos)
    return salida


# ════════════════════════════════════════════════════════
# RUTAS — LA PLANTILLA, CRUZADA CON SUS CIFRAS
# ════════════════════════════════════════════════════════
#
# La plantilla sale de football-data: nombre, fecha de nacimiento,
# nacionalidad y puesto. Las cifras salen de Understat. Cada fuente
# tiene justo lo que a la otra le falta, y hasta ahora no se hablaban:
# al pinchar un jugador de la plantilla salía un "próximamente".
#
# Cruzarlas arregla dos cosas de una vez: la ficha se abre desde la
# plantilla, y aparece la EDAD, que es lo que Understat no publica y
# por lo que el filtro de edad del scouting no podía existir.


@app.get("/api/plantilla/{competition_code}/{team_id}")
async def plantilla_con_cifras(competition_code: str, team_id: int,
                               season: int = Query(None)):
    """La plantilla de un equipo con las cifras de cada jugador.

    A cada jugador se le pega su registro de Understat si se puede
    emparejar con seguridad. Si no se puede, va con su motivo: un
    jugador sin cifras se dice, un jugador con las cifras de otro no
    se nota.
    """
    try:
        equipo = await football_client.get_team(team_id)
    except LimiteAlcanzado as e:
        raise HTTPException(status_code=429, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

    plantilla = equipo.get("squad") or []

    # Understat es un extra: si se cae, la plantilla sale igual sin
    # cifras. Media respuesta buena vale más que un error entero.
    aviso, de_understat = None, []
    try:
        de_understat = await get_league_players(competition_code.upper(), season)
    except FuenteNoDisponible as e:
        aviso = f"No he podido traer las cifras de Understat: {e}"

    # Sólo los de ESTE equipo: emparejar contra toda la liga multiplica
    # por veinte las posibilidades de confundir dos apellidos iguales.
    nombre_corto = _normaliza(equipo.get("name", ""))
    suyos = [p for p in de_understat
             if _normaliza(p.get("team", "")) == nombre_corto]

    salida, con_cifras, motivos = [], 0, {}
    for j in plantilla:
        ficha = dict(j)
        encontrado, motivo = emparejar_jugador(
            j.get("name"), suyos, clave=lambda x: x.get("name", ""))
        if encontrado:
            con_cifras += 1
            ficha["understat"] = encontrado
            ficha["player_id"] = encontrado.get("player_id")
        else:
            ficha["understat"] = None
            ficha["sin_cifras"] = motivo
            ficha["sin_cifras_detalle"] = MOTIVOS_JUGADOR.get(motivo, "")
            motivos[motivo] = motivos.get(motivo, 0) + 1
        salida.append(ficha)

    if not suyos and not aviso:
        aviso = (f"Understat no tiene a ningún jugador de {equipo.get('name')} "
                 f"en esta liga. Puede que el equipo esté escrito de otra "
                 f"forma en las dos fuentes, o que no sea una liga que "
                 f"Understat cubra.")

    return {
        "equipo": equipo.get("name"),
        "team_id": team_id,
        "competicion": competition_code.upper(),
        "season": season or temporada_actual(),
        "temporada": nombre_temporada(season or temporada_actual()),
        "plantilla": salida,
        "con_cifras": con_cifras,
        "sin_cifras": len(salida) - con_cifras,
        "motivos": motivos,
        "aviso": aviso,
    }


# ════════════════════════════════════════════════════════
# RUTAS — INFORME DE UN PARTIDO DE ESTA TEMPORADA
# ════════════════════════════════════════════════════════
#
# El informe que ya había usa StatsBomb, que publica competiciones
# cerradas: del partido del sábado pasado no hay nada. Para los
# partidos de esta temporada la única fuente abierta es Understat, y
# da tiros, no pases.
#
# Son dos informes distintos a propósito, y cada uno dice de dónde
# sale y qué no puede enseñar. Mezclarlos en uno solo que a veces
# tiene red de pases y a veces no sería peor: nadie sabría nunca qué
# está mirando.

MOTIVOS_EMPAREJAR = {
    "sin_calendario":
        "Understat no cubre esta competición. Tiene las cinco grandes "
        "ligas europeas y nada más: si esto es Champions, Copa o una "
        "liga de fuera, no hay datos de tiros que traer.",
    "sin_partidos_ese_dia":
        "Understat no tiene ningún partido de esa liga ese día. Si el "
        "partido es de hoy o de ayer, suele ser que todavía no lo han "
        "publicado: tardan unas horas desde el pitido final.",
    "nombres_no_encajan":
        "He encontrado partidos de ese día pero ninguno es éste. Puede "
        "ser que los dos sitios escriban los nombres de forma muy "
        "distinta. Prefiero decirlo a enseñarte el informe de otro "
        "partido, que es lo que pasaría si me pusiera a adivinar.",
    "fecha_ilegible":
        "No he entendido la fecha del partido.",
}


@app.get("/api/informe-liga/{competition_code}")
async def informe_de_liga(
    competition_code: str,
    local: str = Query(..., description="nombre del equipo local, tal cual lo da football-data"),
    visitante: str = Query(...),
    fecha: str = Query(..., description="AAAA-MM-DD"),
    season: int = Query(None),
):
    """El informe de un partido de esta temporada, con datos de Understat.

    No recibe un identificador de partido porque football-data y
    Understat usan los suyos y no se parecen en nada. Se emparejan por
    fecha y nombres, con las reglas de backend/ml/emparejar.py, que
    prefieren no emparejar antes que emparejar mal.
    """
    codigo = competition_code.upper()
    try:
        calendario = await get_league_fixtures(codigo, season)
    except FuenteNoDisponible as e:
        raise HTTPException(status_code=503, detail={
            "motivo": "fuente_caida", "detalle": str(e)})

    partido, motivo = emparejar_con_motivo(
        fecha, _normaliza(local), _normaliza(visitante), calendario)

    if partido is None:
        raise HTTPException(status_code=404, detail={
            "motivo": motivo,
            "detalle": MOTIVOS_EMPAREJAR.get(motivo, "No he podido encontrarlo."),
            "buscaba": f"{local} - {visitante} el {fecha}",
            "partidos_ese_dia": [
                f"{c['local']} - {c['visitante']}" for c in calendario
                if str(c.get("fecha", ""))[:10] == str(fecha)[:10]][:12],
        })

    if not partido.get("jugado"):
        raise HTTPException(status_code=404, detail={
            "motivo": "todavia_no_jugado",
            "detalle": "Ese partido aún no se ha jugado, así que no hay "
                       "tiros que enseñar."})

    try:
        tiros = await get_match_shots(partido["match_id"])
    except FuenteNoDisponible as e:
        raise HTTPException(status_code=503, detail={
            "motivo": "fuente_caida", "detalle": str(e)})

    # Las alineaciones son otra consulta y pueden fallar solas. Si
    # fallan, el informe sale igual sin la tabla de jugadores: media
    # respuesta buena vale más que un error entero.
    roster, aviso_roster = None, None
    try:
        roster = await get_match_roster(partido["match_id"])
    except FuenteNoDisponible as e:
        aviso_roster = f"No he podido traer las alineaciones: {e}"

    salida = inf_liga.informe(partido, tiros, roster)
    salida["competicion"] = codigo
    salida["temporada"] = nombre_temporada(season or temporada_actual())
    salida["aviso_alineaciones"] = aviso_roster
    return salida


# ════════════════════════════════════════════════════════
# RUTAS — LESIONES
# ════════════════════════════════════════════════════════

@app.get("/api/player/{player_id}/injuries")
async def get_player_injuries_route(
    player_id: str,
    player_slug: str = Query("player"),
    minutes_last_30: int = Query(0),
    matches_last_30: int = Query(0),
    age: int = Query(25),
    position: str = Query("MF"),
):
    """
    Historial de lesiones + predicción de riesgo ML.
    Combina Transfermarkt + nuestro modelo de predicción.
    """
    # Historial desde Transfermarkt
    injuries = get_player_injuries(player_id, player_slug)
    injury_features_raw = build_injury_features(injuries)

    # Calcular días desde última lesión
    days_since = 365
    if injuries:
        import datetime
        last = injuries[0].get("date_until", "") or injuries[0].get("date_from", "")
        if last and last != "Present":
            try:
                parts = last.split(".")
                if len(parts) == 3:
                    d = datetime.datetime(int(parts[2]), int(parts[1]), int(parts[0]))
                    days_since = (datetime.datetime.now() - d).days
            except:
                pass

    # Features para el modelo
    risk_features = build_player_risk_features(
        injury_history=injuries,
        minutes_last_30_days=minutes_last_30,
        matches_last_30_days=matches_last_30,
        age=age,
        position=position,
        days_since_last_injury=days_since,
    )

    # Predicción
    risk = calculate_injury_risk(risk_features)

    return {
        "player_id":     player_id,
        "injuries":      injuries,
        "injury_summary":injury_features_raw,
        "risk_prediction": risk,
        "features":      risk_features,
    }


# ════════════════════════════════════════════════════════
# RUTAS — GOLES Y ASISTENCIAS DE LAS CINCO GRANDES
# ════════════════════════════════════════════════════════
#
# Lo pidió Félix: "el ranking de los goles y asistencias de todos, de
# las ligas quitando la Champions".
#
# Sin Champions a propósito, y no es un capricho: en la fase de liga
# un equipo juega ocho partidos contra rivales de otro nivel. Meter
# esos goles en la misma lista que los de LaLiga compara cosas que no
# se parecen. Si algún día entra, entrará en su propia columna.
#
# Y con la diferencia respecto al xG y al xA al lado, que es lo que
# esta lista tiene y las de los periódicos no: no sólo quién lleva más
# goles, sino quién lleva más de los que le tocaban.


ORDENES_GA = {
    # cada orden, con la clave por la que se ordena y el desempate.
    # Ordenar en el servidor no es un capricho: el recorte de `limit`
    # tiene que caer DESPUÉS de ordenar. Si se recorta por G+A y luego
    # la pantalla reordena por diferencia, el que lleva 2 de G+A con
    # 0,3 de xG+xA —que es justo el hallazgo— se ha quedado fuera sin
    # que nadie lo vea.
    "ga": lambda x: (-x["ga"], -x["goles"], x["minutos"]),
    "goles": lambda x: (-x["goles"], -x["asistencias"], x["minutos"]),
    "asistencias": lambda x: (-x["asistencias"], -x["goles"], x["minutos"]),
    "diferencia": lambda x: (-x["diferencia"], -x["ga"], x["minutos"]),
    "ga_90": lambda x: (-x["ga_90"], -x["ga"], x["minutos"]),
}


@app.get("/api/goles-asistencias")
async def goles_y_asistencias(
    season: int = Query(None),
    min_minutes: int = Query(270, ge=0),
    limit: int = Query(120, ge=10, le=500),
    liga: str = Query(None, description="PL | PD | BL1 | SA | FL1; vacío = las cinco"),
    orden: str = Query("ga", description=" | ".join(ORDENES_GA)),
):
    """Goles + asistencias de las cinco grandes ligas, en una lista.

    Se trae cada liga por separado y se juntan. Si alguna se cae, la
    lista sale con las demás y se dice cuál falta: media respuesta
    buena vale más que un error entero, siempre que se avise.
    """
    if orden not in ORDENES_GA:
        raise HTTPException(status_code=400, detail={
            "motivo": "orden_desconocido",
            "detalle": f"'{orden}' no es un orden. Son: "
                       f"{', '.join(ORDENES_GA)}"})

    if liga and liga not in LIGAS_GRANDES:
        raise HTTPException(status_code=400, detail={
            "motivo": "liga_desconocida",
            "detalle": f"'{liga}' no está en la lista. Son: "
                       f"{', '.join(LIGAS_GRANDES)}"})

    pedidas = [liga] if liga else list(LIGAS_GRANDES)

    jugadores, caidas = [], []
    for lg in pedidas:
        try:
            trozo = await get_league_players(lg, season)
            for p in trozo:
                p["league"] = lg
            jugadores.extend(trozo)
        except FuenteNoDisponible as e:
            caidas.append(f"{lg}: {e}")

    if not jugadores:
        raise HTTPException(status_code=503, detail={
            "motivo": "fuente_caida",
            "detalle": " · ".join(caidas) or "Understat no ha contestado"})

    jugadores = [p for p in jugadores if (p.get("time") or 0) >= min_minutes]

    salida = []
    for p in jugadores:
        g = int(p.get("goals") or 0)
        a = int(p.get("assists") or 0)
        xg = float(p.get("xG") or 0)
        xa = float(p.get("xA") or 0)
        minutos = int(p.get("time") or 0)
        salida.append({
            "player_id": p.get("player_id"), "name": p.get("name"),
            "team": p.get("team"), "league": p.get("league"),
            "position": p.get("position"),
            "minutos": minutos, "partidos": int(p.get("games") or 0),
            "goles": g, "asistencias": a, "ga": g + a,
            "xg": round(xg, 2), "xa": round(xa, 2),
            "xga": round(xg + xa, 2),
            # Lo que de verdad aporta esta lista: no quién lleva más,
            # sino quién lleva más de los que le tocaban.
            "diferencia": round((g + a) - (xg + xa), 2),
            "ga_90": round((g + a) / minutos * 90, 3) if minutos else 0.0,
            "xga_90": round((xg + xa) / minutos * 90, 3) if minutos else 0.0,
        })

    salida.sort(key=ORDENES_GA[orden])
    cuantos_habia = len(salida)
    salida = salida[:limit]

    avisos = []
    if caidas:
        avisos.append(f"No he podido traer {' ni '.join(caidas)}. La lista "
                      f"está hecha sin esa liga.")
    if cuantos_habia > limit:
        avisos.append(f"Con {min_minutes} minutos o más hay {cuantos_habia} "
                      f"jugadores y aquí salen los {limit} primeros por "
                      f"'{orden}'. El resto está cortado, no es que no exista.")

    return {
        "jugadores": salida,
        "ligas": pedidas,
        "sin_champions": True,
        "season": season or temporada_actual(),
        "temporada": nombre_temporada(season or temporada_actual()),
        "minutos_minimos": min_minutes,
        "orden": orden,
        "cuantos_cumplen": cuantos_habia,
        "limite": limit,
        "avisos": avisos,
    }


# ════════════════════════════════════════════════════════
# RUTAS — SCOUTING ML
# ════════════════════════════════════════════════════════

@app.get("/api/scouting/{competition_code}")
async def run_scouting(
    competition_code: str,
    position: str = Query("FW", description="FW | MF | DF | GK"),
    max_age: int = Query(25, ge=15, le=35),
    min_minutes: int = Query(500, ge=0),
    season: int = Query(None),
):
    """Scouting: percentiles por 90 minutos y agrupación por parecido.

    `competition_code` puede ser una liga («PD») o «ALL» para las cinco
    grandes juntas.

    LO DE «TODAS» NO ES JUNTAR CINCO LISTAS, y es la diferencia entre
    que el número signifique algo o no. Un percentil se calcula DENTRO
    de un grupo: estar en el 90 de La Liga y estar en el 90 de la
    Premier no son lo mismo, y poner las dos cifras en la misma tabla
    ordenada las compara como si lo fueran.

    Así que para «todas» se traen las cinco ligas, se juntan los
    jugadores en UN SOLO grupo, y los percentiles se calculan sobre ese
    grupo. Entonces el 90 quiere decir «mejor que el 90 % de los
    delanteros de las cinco grandes», que sí es una frase con sentido.

    Se niega, con su motivo, cuando no puede hacerlo bien:

      puesto_sin_datos   Understat no publica con qué puntuar ese
                         puesto. Pasa con defensas y porteros, y no es
                         un «todavía no»: es que esos datos no están.
      faltan_metricas    la fuente ha cambiado y falta algo que antes
                         venía. Mejor saberlo que rellenarlo con ceros.
      fuente_caida       Understat no ha contestado
    """
    codigo = competition_code.upper()
    ligas = list(LIGAS_GRANDES) if codigo in ("ALL", "TODAS") else [codigo]

    players, caidas = [], []
    for lg in ligas:
        try:
            trozo = await get_league_players(lg, season)
            for p in trozo:
                p["league"] = lg          # para saber de dónde sale cada uno
            players.extend(trozo)
        except FuenteNoDisponible as e:
            caidas.append(f"{lg}: {e}")

    if not players:
        # 503, nunca 200 con la lista vacía: "no he podido mirar" no es
        # lo mismo que "he mirado y no hay nadie".
        raise HTTPException(status_code=503, detail={
            "motivo": "fuente_caida",
            "detalle": " · ".join(caidas) or "Understat no ha contestado"})

    try:
        salida = run_scouting_pipeline(
            players=players,
            position=position.upper()[:2],
            max_age=max_age,
            min_minutes=min_minutes,
        )
        salida["ligas"] = ligas
        # El año suelto, además del "2026/27": la ficha de jugador lo
        # necesita para pedir los tiros DE ESTA TEMPORADA y no los de
        # toda la carrera. Que lo saque recortando la cadena es pedir
        # que algún día se recorte mal.
        salida["season"] = season or temporada_actual()
        salida["temporada"] = nombre_temporada(salida["season"])
        if caidas:
            # Una liga caída NO se calla: cambia con quién se está
            # comparando a todo el mundo.
            salida.setdefault("avisos", []).append(
                "No he podido traer " + " ni ".join(caidas) +
                ". Los percentiles están calculados sin esa liga.")
        return salida
    except PuestoSinDatos as e:
        raise HTTPException(status_code=503, detail={
            "motivo": "puesto_sin_datos", "puesto": e.puesto,
            "detalle": e.motivo})
    except ValueError as e:
        raise HTTPException(status_code=503, detail={
            "motivo": "faltan_metricas", "detalle": str(e)})


@app.get("/api/player/{player_id}/similar")
async def get_similar_players(
    player_id: str,
    competition_code: str = Query("PL"),
    top_n: int = Query(5, ge=3, le=10),
    season: int = Query(None),
):
    """'Jugadores similares a X' — K-Means similarity"""
    players = await get_league_players(competition_code.upper(), season)
    target = next((p for p in players if str(p.get("player_id")) == str(player_id)), None)
    if not target:
        raise HTTPException(status_code=404, detail="Jugador no encontrado")

    similar = find_similar_players(
        target_player=target,
        all_players=players,
        position=target.get("position", "MF"),
        top_n=top_n,
    )
    return {"target": target, "similar": similar}


# ════════════════════════════════════════════════════════
# RUTAS — VISUALIZACIONES (PNG en base64)
# ════════════════════════════════════════════════════════

@app.get("/api/viz/radar/{competition_code}/{player_id}")
async def get_player_radar(
    competition_code: str,
    player_id: str,
    season: int = Query(None),
    position: str = Query(None),
):
    """Radar PyPizza del jugador — imagen PNG en base64"""
    try:
        players = await get_league_players(competition_code.upper(), season)
        target = next((p for p in players if str(p.get("player_id")) == str(player_id)), None)
        if not target:
            raise HTTPException(status_code=404, detail="Jugador no encontrado")
        pos = position or target.get("position", "FW")
        from backend.viz.radar import generar_radar_pizza
        img = generar_radar_pizza(
            player_data=target,
            all_players=players,
            position=pos[:2].upper(),
        )
        if not img:
            raise HTTPException(status_code=500, detail="Error generando radar")
        return {"image": img, "player": target["name"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/api/viz/radar-custom")
async def get_custom_radar(
    name: str = Query(...),
    goals: float = Query(0),
    assists: float = Query(0),
    xG: float = Query(0),
    minutes: int = Query(0),
    rating: float = Query(80),
    position: str = Query("FW"),
    team: str = Query(""),
    competition_code: str = Query("PL"),
    season: int = Query(None),
):
    """Radar PyPizza con datos directos — para jugadores locales del frontend"""
    try:
        player_data = {
            "name": name, "goals": goals, "assists": assists,
            "xG": xG, "xA": assists * 0.8, "npxG": xG * 0.95,
            "minutes": minutes, "rating": rating, "team": team,
            "shots": int(goals * 3.5), "key_passes": int(assists * 2),
            "xGChain": xG * 1.3, "xGBuildup": xG * 0.5,
            "position": position,
        }
        # Get league players for percentile comparison
        try:
            all_players = await get_league_players(competition_code.upper(), season)
        except:
            all_players = [player_data]

        from backend.viz.radar import generar_radar_pizza, generar_radar_simple
        img = None
        # Try PyPizza first, fallback to simple radar
        try:
            img = generar_radar_pizza(
                player_data=player_data,
                all_players=all_players,
                position=position[:2].upper(),
                titulo_principal=name,
                titulo_secundario=f"{team} · {position} · Temporada "
                              f"{nombre_temporada(season or temporada_actual())}",
            )
        except Exception as pizza_err:
            logger.warning(f"PyPizza failed ({pizza_err}), using simple radar")
        
        if not img:
            img = generar_radar_simple(
                player_data=player_data,
                all_players=all_players,
                position=position[:2].upper(),
            )
        
        if not img:
            raise HTTPException(status_code=500, detail="Error generando radar")
        return {"image": img, "player": name, "type": "radar"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/api/viz/shotmap/{player_id}")
async def get_shotmap(player_id: str, season_filter: str = Query(None)):
    """Shot map del jugador desde Understat — imagen PNG en base64"""
    try:
        shots = await get_player_shots(player_id)
        if season_filter:
            shots = [s for s in shots if s.get("season") == season_filter]
        if not shots:
            raise HTTPException(status_code=404, detail="Sin datos de disparos")
        player_name = shots[0].get("player", "Jugador") if shots else "Jugador"
        from backend.viz.shotmap import generar_shotmap
        img = generar_shotmap(shots, title=f"Shot Map — {player_name}")
        return {"image": img, "total_shots": len(shots)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


# ── LA RUTA QUE SE INVENTABA LOS TIROS, Y POR QUÉ YA NO ESTÁ ──
#
# Aquí vivía una ruta llamada "shotmap-custom". Le dabas un nombre,
# unos goles y unos tiros, y GENERABA las posiciones con random.gauss,
# el xG con random.uniform y hasta si el disparo había sido con la
# derecha o de cabeza con random.choice. Devolvía un PNG idéntico al
# de un mapa de tiro de verdad.
#
# El frontend no la llamaba, pero estaba viva en la API pública:
# cualquiera podía pedirla y recibir un mapa inventado con pinta de
# real, sin nada en la imagen que lo advirtiera.
#
# Un mapa de tiro con posiciones inventadas no es una aproximación.
# Es una mentira con forma de gráfico. Si no hay datos del jugador,
# la respuesta correcta es decir que no hay datos.
#
# El mapa de verdad sigue donde estaba: lee los disparos reales de
# Understat y devuelve 404 si no los encuentra.

# ════════════════════════════════════════════════════════
# FRONTEND — Servir el HTML
# ════════════════════════════════════════════════════════

frontend_path = Path(__file__).parent / "frontend"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_frontend():
        index = frontend_path / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return JSONResponse({"message": "SPORTALYZE API corriendo. Frontend no encontrado."})
else:
    @app.get("/", include_in_schema=False)
    async def root():
        return {
            "app": "SPORTALYZE API",
            "version": "2.0.0",
            "docs": "/docs",
            "status": "running",
        }


# ════════════════════════════════════════════════════════
# HEALTH CHECK
# ════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    from backend.config import FOOTBALL_API_KEY
    from backend.scrapers.football_data import _turnero
    return {
        "status": "ok",
        "api_key_configured": bool(FOOTBALL_API_KEY),
        "env": ENV,
        # Cuánta cola hay ahora mismo para football-data. Sirve para
        # mirar desde fuera si la página está saturada sin tener que
        # entrar a probarla.
        "espera_football_data": round(_turnero.espera_estimada(), 1),
    }


# ════════════════════════════════════════════════════════
# CALENTAR LA CACHÉ
# ════════════════════════════════════════════════════════
#
# El primero que entra se lo encuentra todo frío: cada pantalla que
# toca es una petición a football-data, y las primeras tardan. Si ese
# primero es alguien a quien le estás enseñando el proyecto, la primera
# impresión es una ruedecita girando.
#
# Así que al arrancar se piden las clasificaciones de las ligas
# grandes. Pero DESPACIO y CEDIENDO EL PASO:
#
#   · una cada CADA_CUANTO segundos, no todas de golpe
#   · y sólo si el turnero dice que no hay cola, porque un visitante de
#     verdad vale más que calentar una liga que a lo mejor nadie mira
#
# Sin eso, calentar seis ligas se comería los seis primeros turnos del
# minuto y el primer visitante esperaría por culpa del calentamiento,
# que es exactamente lo contrario de lo que se busca.

# Las cinco que se ofrecen juntas en el scouting.
LIGAS_GRANDES = ("PD", "PL", "SA", "BL1", "FL1")

LIGAS_QUE_SE_CALIENTAN = ("PD", "PL", "SA", "BL1", "FL1")
CADA_CUANTO = 7.0          # segundos entre una liga y la siguiente
ESPERA_INICIAL = 3.0       # dejar que el servidor acabe de levantarse


async def calentar():
    """Deja las clasificaciones listas antes de que entre nadie."""
    from backend.config import FOOTBALL_API_KEY
    from backend.scrapers.football_data import _turnero

    if not FOOTBALL_API_KEY:
        logger.info("Sin clave de football-data: no hay nada que calentar.")
        return

    await asyncio.sleep(ESPERA_INICIAL)
    hechas = 0
    for codigo in LIGAS_QUE_SE_CALIENTAN:
        # Si hay cola, el visitante va primero. Se deja para otra vez.
        if _turnero.espera_estimada() > 0:
            logger.info("Hay cola; dejo de calentar en %s.", codigo)
            break
        try:
            await football_client.get_standings(codigo)
            hechas += 1
            logger.info("Calentada la clasificación de %s.", codigo)
        except Exception as e:
            # Calentar NUNCA puede tirar el servidor: es un lujo, no un
            # requisito. Si falla, se apunta y se sigue.
            logger.warning("No he podido calentar %s: %s", codigo, e)
        await asyncio.sleep(CADA_CUANTO)
    logger.info("Calentadas %d de %d ligas.", hechas, len(LIGAS_QUE_SE_CALIENTAN))


# El calentamiento se engancha con lifespan y no con @app.on_event,
# que FastAPI da por obsoleto y avisa por consola en cada arranque.
@asynccontextmanager
async def ciclo_de_vida(app):
    # En segundo plano: el servidor tiene que estar contestando ya.
    tarea = asyncio.create_task(calentar())
    yield
    tarea.cancel()


app.router.lifespan_context = ciclo_de_vida


# ════════════════════════════════════════════════════════
# ARRANQUE
# ════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("""
╔══════════════════════════════════════╗
║        ⚽ SPORTALYZE v2.0            ║
║   Análisis Deportivo Profesional     ║
╠══════════════════════════════════════╣
║  API Docs: http://localhost:8000/docs║
║  Frontend: http://localhost:8000     ║
╚══════════════════════════════════════╝
    """)
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=PORT,
        reload=(ENV == "development"),
        log_level="info",
    )
