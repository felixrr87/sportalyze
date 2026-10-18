# backend/scrapers/understat.py
# ============================================================
# Conector a Understat — xG real, shots con coordenadas
# Sin API key necesaria. pip install understatapi
# Cubre: EPL, La Liga, Bundesliga, Serie A, Ligue 1, RFPL
# Datos desde 2014/15
#
# OJO CON CÓMO SE LLAMA A understatapi
# ------------------------------------
# understatapi 0.7.1 es SÍNCRONA. UnderstatClient tiene __enter__ pero
# no tiene __aenter__, y get_player_data() no es una corrutina.
#
# Este archivo la llamaba con `async with` y `await`. Resultado: cada
# llamada reventaba con «__aenter__», la excepción se tragaba y se
# devolvía []. Understat no funcionó NUNCA, y nadie se enteró porque
# el fallo se disfrazaba de lista vacía.
#
# Ahora se llama con `with` dentro de asyncio.to_thread, que es lo que
# corresponde a una librería síncrona: así no bloquea el bucle de
# eventos mientras espera a la red. Y si falla, revienta.
# ============================================================

import asyncio
import logging

from backend.temporada import temporada_actual
# pandas se importaba aquí y no se usaba ni una vez. Son unos
# 90 MB de memoria y medio segundo de arranque para nada, que
# en un servidor pequeño es justo lo que no sobra.
from cachetools import TTLCache
from backend.config import CACHE_TTL
from backend.errors import FuenteNoDisponible

logger = logging.getLogger(__name__)
_cache = TTLCache(maxsize=300, ttl=CACHE_TTL)

# Mapa de códigos de liga
# Los nombres de liga que entiende understatapi. NO son los que uno
# escribiría: la librería los compara con una lista suya, carácter a
# carácter y distinguiendo mayúsculas.
#
# Aquí ponía "La_liga" con ele minúscula y la librería espera
# "La_Liga". Una letra. Con eso, TODA la parte de jugadores de La Liga
# —cartas, scouting, comparador, watchlist— devolvía un error, y sólo
# la de La Liga: las otras cinco funcionaban. Es el fallo que no se ve
# probando "la aplicación" por encima, porque hay que mirar
# precisamente esa liga.
#
# Hay una prueba que compara este diccionario contra la lista de la
# propia librería, así que si cambia de nombres o alguien añade una
# liga mal escrita, salta sin necesidad de red.
UNDERSTAT_LEAGUES = {
    "PL":  "EPL",
    "PD":  "La_Liga",
    "BL1": "Bundesliga",
    "SA":  "Serie_A",
    "FL1": "Ligue_1",
    "RPL": "RFPL",
}


async def _pedir(que: str, llamada):
    """Ejecuta una llamada SÍNCRONA de understatapi fuera del bucle.

    `llamada` recibe el cliente ya abierto y devuelve el dato crudo.
    Si la fuente falla, esto lanza FuenteNoDisponible: no se devuelve
    una lista vacía haciéndose pasar por una respuesta buena.
    """
    def _trabajo():
        try:
            from understatapi import UnderstatClient
        except ImportError as e:
            raise FuenteNoDisponible(
                "Understat", "falta understatapi (pip install understatapi)"
            ) from e
        try:
            with UnderstatClient() as client:      # síncrono, no async
                return llamada(client)
        except Exception as e:
            raise FuenteNoDisponible("Understat", f"{type(e).__name__}: {e}") from e

    return await asyncio.to_thread(_trabajo)


async def get_league_players(competition_code: str, season: int = None) -> list:
    """
    Jugadores de una liga con xG, xA, shots, goals.
    season: el año en que EMPIEZA la temporada (2026 = 2026/27).
            Si no se dice, la que se está jugando hoy.
    """
    season = season if season is not None else temporada_actual()
    cache_key = f"understat_players_{competition_code}_{season}"
    if cache_key in _cache:
        return _cache[cache_key]

    league = UNDERSTAT_LEAGUES.get(competition_code)
    if not league:
        # Esto sí es un vacío legítimo: Understat no cubre esa liga.
        return []

    players_data = await _pedir(
        "jugadores de la liga",
        lambda c: c.league(league=league).get_player_data(season=str(season)),
    )

    result = []
    for p in players_data:
        result.append({
            "player_id":  p.get("id"),
            "name":       p.get("player_name", ""),
            "team":       p.get("team_title", ""),
            "position":   p.get("position", ""),
            "games":      int(p.get("games", 0)),
            "time":       int(p.get("time", 0)),
            "goals":      int(p.get("goals", 0)),
            "xG":         round(float(p.get("xG", 0)), 2),
            "assists":    int(p.get("assists", 0)),
            "xA":         round(float(p.get("xA", 0)), 2),
            "shots":      int(p.get("shots", 0)),
            "key_passes": int(p.get("key_passes", 0)),
            "npg":        int(p.get("npg", 0)),       # non-penalty goals
            "npxG":       round(float(p.get("npxG", 0)), 2),
            "xGChain":    round(float(p.get("xGChain", 0)), 2),
            "xGBuildup":  round(float(p.get("xGBuildup", 0)), 2),
            # Calculadas
            "xG_per90":   round(float(p.get("xG", 0)) / max(int(p.get("time", 90)), 1) * 90, 3),
            "xA_per90":   round(float(p.get("xA", 0)) / max(int(p.get("time", 90)), 1) * 90, 3),
            "goals_diff": round(int(p.get("goals", 0)) - float(p.get("xG", 0)), 2),
        })

    _cache[cache_key] = result
    return result


async def get_player_shots(player_id: str) -> list:
    """
    Todos los disparos de un jugador con coordenadas X,Y para shot map.
    Exactamente lo que necesitan tus notebooks de PostMatch.
    """
    cache_key = f"understat_shots_{player_id}"
    if cache_key in _cache:
        return _cache[cache_key]

    shots_data = await _pedir(
        "disparos del jugador",
        lambda c: c.player(player=player_id).get_shot_data(),
    )

    result = []
    for shot in shots_data:
        result.append({
            "id":          shot.get("id"),
            "minute":      int(shot.get("minute", 0)),
            "result":      shot.get("result", ""),     # Goal, SavedShot, MissedShots, BlockedShot
            "x":           float(shot.get("X", 0)),
            "y":           float(shot.get("Y", 0)),
            "xG":          float(shot.get("xG", 0)),
            "player":      shot.get("player", ""),
            "situation":   shot.get("situation", ""),   # OpenPlay, FromCorner, SetPiece
            "season":      shot.get("season", ""),
            "shot_type":   shot.get("shotType", ""),    # RightFoot, LeftFoot, Head
            "match_id":    shot.get("match_id", ""),
            "home_team":   shot.get("h_team", ""),
            "away_team":   shot.get("a_team", ""),
            "date":        shot.get("date", "")[:10],
        })

    _cache[cache_key] = result
    return result


async def get_match_shots(match_id: str) -> dict:
    """
    Disparos de un partido con coordenadas — para shot maps estilo PostMatch.
    Devuelve disparos separados por equipo local/visitante.
    """
    cache_key = f"understat_match_{match_id}"
    if cache_key in _cache:
        return _cache[cache_key]

    shot_data = await _pedir(
        "disparos del partido",
        lambda c: c.match(match=match_id).get_shot_data(),
    )

    home_shots = []
    away_shots = []

    for side, shots_list in [("h", home_shots), ("a", away_shots)]:
        for shot in shot_data.get(side, []):
            shots_list.append({
                "minute":    int(shot.get("minute", 0)),
                "result":    shot.get("result", ""),
                "x":         float(shot.get("X", 0)) * 100,  # normalizar 0-1 → 0-100
                "y":         float(shot.get("Y", 0)) * 100,
                "xG":        float(shot.get("xG", 0)),
                "player":    shot.get("player", ""),
                "situation": shot.get("situation", ""),
                "shot_type": shot.get("shotType", ""),
            })

    result = {
        "match_id":    match_id,
        "home_shots":  home_shots,
        "away_shots":  away_shots,
        "home_xG":     round(sum(s["xG"] for s in home_shots), 2),
        "away_xG":     round(sum(s["xG"] for s in away_shots), 2),
        "home_goals":  sum(1 for s in home_shots if s["result"] == "Goal"),
        "away_goals":  sum(1 for s in away_shots if s["result"] == "Goal"),
    }

    _cache[cache_key] = result
    return result


async def get_league_teams_xg(competition_code: str, season: int = None) -> list:
    """xG por equipo en la liga — para el dashboard"""
    season = season if season is not None else temporada_actual()
    cache_key = f"understat_teams_{competition_code}_{season}"
    if cache_key in _cache:
        return _cache[cache_key]

    league = UNDERSTAT_LEAGUES.get(competition_code)
    if not league:
        # Esto sí es un vacío legítimo: Understat no cubre esa liga.
        return []

    teams_data = await _pedir(
        "xG por equipo",
        lambda c: c.league(league=league).get_team_data(season=str(season)),
    )

    result = []
    for clave, team_data in teams_data.items():
        # OJO: la clave NO es el nombre del equipo, es su ID numérico
        # ("148", "150", "154"). El nombre va dentro, en "title".
        #
        # Esto estaba cogiendo la clave como nombre, así que la
        # clasificación intentaba casar «148» con «FC Barcelona» y no
        # casaba ninguno: cero equipos con xG en las veinte filas. Y no
        # se veía porque el fallo se lo tragaba un `except: pass`.
        team_name = team_data.get("title") or clave
        history = team_data.get("history", [])
        if not history:
            continue
        total_xG   = sum(float(h.get("xG", 0)) for h in history)
        total_xGA  = sum(float(h.get("xGA", 0)) for h in history)
        total_goals = sum(int(h.get("scored", 0)) for h in history)
        total_against = sum(int(h.get("missed", 0)) for h in history)
        result.append({
            "team":          team_name,
            "played":        len(history),
            "xG":            round(total_xG, 1),
            "xGA":           round(total_xGA, 1),
            "goals":         total_goals,
            "goals_against": total_against,
            "xG_diff":       round(total_goals - total_xG, 1),
            "xGA_diff":      round(total_against - total_xGA, 1),
        })

    result.sort(key=lambda x: -x["xG"])
    _cache[cache_key] = result
    return result




# ════════════════════════════════════════════════════════════
# UN PARTIDO CONCRETO
# ════════════════════════════════════════════════════════════
#
# Esto es lo que hace falta para que, al pinchar un partido en la
# pantalla de Partidos, salga su informe.
#
# EL PROBLEMA DE JUNTAR DOS FUENTES
# ---------------------------------
# El calendario viene de football-data y los tiros de Understat, y
# cada uno tiene sus propios identificadores de partido, que no se
# parecen en nada. Así que hay que emparejarlos por lo único que
# comparten: la fecha y los dos equipos.
#
# Y los nombres tampoco coinciden. football-data dice "FC Barcelona" y
# Understat dice "Barcelona"; "Paris Saint-Germain FC" contra "Paris
# Saint Germain". Por eso el emparejado se hace con el nombre
# normalizado y, aun así, se exige que la FECHA cuadre: dos equipos
# pueden jugar dos veces en una temporada, pero no el mismo día.
#
# Si no se encuentra, se dice que no se ha encontrado. Lo que no se
# hace es devolver el partido "más parecido": un informe del partido
# equivocado es peor que no tener informe.


# Esto NO es ortografía, es traducción, y por eso va en una lista a
# mano y no en una regla. Limpiar acentos convierte "Köln" en "koln",
# que sigue sin parecerse a "Cologne" en nada: no hay manera de llegar
# de uno a otro quitando caracteres.
#
# La lista es corta a propósito. Cada entrada es un caso comprobado de
# que una fuente escribe el nombre en un idioma y la otra en otro. Si
# algún día hace falta alargarla mucho, será señal de que el
# emparejado por nombre no da más de sí y hay que buscar otra cosa.
TRADUCCIONES = {
    "koln": "cologne",
    "munchen": "munich",
    "monchengladbach": "gladbach",
    "nurnberg": "nuremberg",
    "torino": "turin",
    "milano": "milan",
    "venezia": "venice",
    "roma": "rome",
    "firenze": "florence",
    "sevilla": "seville",
    "la coruna": "coruna",
}


def _normaliza(nombre: str) -> str:
    """Un nombre de equipo reducido a lo que de verdad lo identifica.

    Quita acentos, puntuación, y las palabras de adorno que cada fuente
    pone o quita a su gusto: FC, CF, AC, SC, Club, Deportivo... y
    después traduce los pocos nombres que una fuente escribe en un
    idioma y la otra en otro.
    """
    import unicodedata
    s = unicodedata.normalize("NFKD", str(nombre or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = "".join(c if c.isalnum() or c.isspace() else " " for c in s)
    sobra = {"fc", "cf", "ac", "sc", "cd", "ud", "sd", "rc", "rcd", "afc",
             "bc", "club", "deportivo", "futbol", "football", "calcio",
             "sv", "vf", "vfb", "vfl", "tsg", "tsv", "fsv", "ssc", "as",
             "ss", "us", "de", "the"}
    # "Real" NO se quita: es lo único que separa a Real Sociedad de
    # Sociedad y ayuda a distinguir Real Madrid de Madrid a secas.
    # Los números se van TODOS, y da igual si son el año de fundación
    # ("1. FC Köln", "Bayer 04") o parte del nombre ("TSV 1860"): lo
    # que importa no es conservarlos, es que las dos fuentes reciban el
    # mismo trato. Si a los dos lados se quita el 1860, "1860 Munich" y
    # "TSV 1860 München" siguen encajando igual de bien.
    palabras = [TRADUCCIONES.get(p, p) for p in s.split()
                if p and p not in sobra and not p.isdigit()]
    limpio = " ".join(palabras) or s.strip()
    # Y las de dos palabras ("la coruna"), que no se pueden traducir
    # palabra a palabra.
    for de, a in TRADUCCIONES.items():
        if " " in de and de in limpio:
            limpio = limpio.replace(de, a)
    return limpio


async def get_league_fixtures(competition_code: str, season: int = None) -> list:
    """Todos los partidos de la liga, con el identificador de Understat.

    Es el índice que permite ir de un partido de football-data al mismo
    partido en Understat.
    """
    season = season if season is not None else temporada_actual()
    clave = f"understat_fixtures_{competition_code}_{season}"
    if clave in _cache:
        return _cache[clave]

    league = UNDERSTAT_LEAGUES.get(competition_code)
    if not league:
        return []

    crudos = await _pedir(
        "calendario de la liga",
        lambda c: c.league(league=league).get_match_data(season=str(season)),
    )

    salida = []
    for p in crudos:
        local = (p.get("h") or {}).get("title", "")
        visit = (p.get("a") or {}).get("title", "")
        goles = p.get("goals") or {}
        xg = p.get("xG") or {}
        salida.append({
            "match_id":   str(p.get("id", "")),
            "jugado":     bool(p.get("isResult")),
            "fecha":      str(p.get("datetime", ""))[:10],
            "local":      local,
            "visitante":  visit,
            "clave_local": _normaliza(local),
            "clave_visitante": _normaliza(visit),
            "goles_local":     _entero(goles.get("h")),
            "goles_visitante": _entero(goles.get("a")),
            "xg_local":        _decimal(xg.get("h")),
            "xg_visitante":    _decimal(xg.get("a")),
        })

    _cache[clave] = salida
    return salida


def _entero(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _decimal(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


async def get_match_roster(match_id: str) -> dict:
    """Los jugadores de los dos equipos en ESE partido.

    Understat da, por jugador: minutos, goles, asistencias, tiros,
    pases clave, xG, xA, xGChain, xGBuildup, tarjetas y el minuto en
    que entró o salió. Con eso se puede hacer una tabla de verdad.
    """
    clave = f"understat_roster_{match_id}"
    if clave in _cache:
        return _cache[clave]

    crudo = await _pedir(
        "alineaciones del partido",
        lambda c: c.match(match=str(match_id)).get_roster_data(),
    )

    salida = {"local": [], "visitante": []}
    for lado, destino in (("h", "local"), ("a", "visitante")):
        for _, j in (crudo.get(lado) or {}).items():
            salida[destino].append({
                "player_id":  str(j.get("player_id", "")),
                "nombre":     j.get("player", ""),
                "puesto":     j.get("position", ""),
                "orden":      _entero(j.get("positionOrder")) or 99,
                "minutos":    _entero(j.get("time")) or 0,
                "goles":      _entero(j.get("goals")) or 0,
                "asistencias": _entero(j.get("assists")) or 0,
                "tiros":      _entero(j.get("shots")) or 0,
                "pases_clave": _entero(j.get("key_passes")) or 0,
                "xg":         _decimal(j.get("xG")) or 0.0,
                "xa":         _decimal(j.get("xA")) or 0.0,
                "xgchain":    _decimal(j.get("xGChain")) or 0.0,
                "xgbuildup":  _decimal(j.get("xGBuildup")) or 0.0,
                "amarillas":  _entero(j.get("yellow_card")) or 0,
                "rojas":      _entero(j.get("red_card")) or 0,
                # OJO: roster_in y roster_out NO son minutos.
                #
                # Lo parecían. Se publicaron como "entró en el minuto
                # X" y en pantalla salió "Gerard Martín ▲806581". Son
                # identificadores internos de Understat del cambio, y
                # no hay manera de sacar de ahí el minuto.
                #
                # El minuto del cambio NO ESTÁ en esta respuesta. Lo
                # que sí está, y es verdad, es si salió de inicio o
                # entró desde el banquillo —position vale "Sub"— y
                # cuántos minutos jugó. Con eso se dice lo que se
                # sabe, y no se insinúa lo que no.
                "suplente":   j.get("position") == "Sub",
            })
        salida[destino].sort(key=lambda x: x["orden"])

    _cache[clave] = salida
    return salida
