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
    season: int = Query(2024, description="2024 = temporada 2024/25"),
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
    try:
        players = await get_league_players(competition_code.upper(), season)
    except FuenteNoDisponible as e:
        raise HTTPException(status_code=503, detail=str(e))

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
        "avisos": avisos,
        "puestos_sin_nota": sin_nota,
    }


@app.get("/api/player/{player_id}/shots")
async def get_player_shot_map(player_id: str):
    """Disparos de un jugador con coordenadas para shot map"""
    try:
        shots = await get_player_shots(player_id)
        return {"shots": shots, "total": len(shots)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


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
# RUTAS — SCOUTING ML
# ════════════════════════════════════════════════════════

@app.get("/api/scouting/{competition_code}")
async def run_scouting(
    competition_code: str,
    position: str = Query("FW", description="FW | MF | DF | GK"),
    max_age: int = Query(25, ge=15, le=35),
    min_minutes: int = Query(500, ge=0),
    season: int = Query(2024),
):
    """Scouting: percentiles por 90 minutos y agrupación por parecido.

    Se niega, con su motivo, cuando no puede hacerlo bien:

      puesto_sin_datos   Understat no publica con qué puntuar ese
                         puesto. Pasa con defensas y porteros, y no es
                         un «todavía no»: es que esos datos no están.
      faltan_metricas    la fuente ha cambiado y falta algo que antes
                         venía. Mejor saberlo que rellenarlo con ceros.
      fuente_caida       Understat no ha contestado
    """
    try:
        players = await get_league_players(competition_code.upper(), season)
    except FuenteNoDisponible as e:
        # 503, nunca 200 con la lista vacía: "no he podido mirar" no es
        # lo mismo que "he mirado y no hay nadie".
        raise HTTPException(status_code=503, detail={
            "motivo": "fuente_caida", "detalle": str(e)})

    try:
        return run_scouting_pipeline(
            players=players,
            position=position.upper()[:2],
            max_age=max_age,
            min_minutes=min_minutes,
        )
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
    season: int = Query(2024),
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
    season: int = Query(2024),
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
    season: int = Query(2024),
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
                titulo_secundario=f"{team} · {position} · Temporada {season}/{str(season+1)[-2:]}",
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
