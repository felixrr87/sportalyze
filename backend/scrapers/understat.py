# backend/scrapers/understat.py
# ============================================================
# Conector a Understat — xG real, shots con coordenadas
# Sin API key necesaria. pip install understatapi
# Cubre: EPL, La Liga, Bundesliga, Serie A, Ligue 1, RFPL
# Datos desde 2014/15
# ============================================================

import asyncio
import logging
import pandas as pd
from cachetools import TTLCache
from backend.config import CACHE_TTL

logger = logging.getLogger(__name__)
_cache = TTLCache(maxsize=300, ttl=CACHE_TTL)

# Mapa de códigos de liga
UNDERSTAT_LEAGUES = {
    "PL":  "EPL",
    "PD":  "La_liga",
    "BL1": "Bundesliga",
    "SA":  "Serie_A",
    "FL1": "Ligue_1",
    "RPL": "RFPL",
}


async def get_league_players(competition_code: str, season: int = 2024) -> list:
    """
    Jugadores de una liga con xG, xA, shots, goals.
    season: 2024 = temporada 2024/25
    """
    cache_key = f"understat_players_{competition_code}_{season}"
    if cache_key in _cache:
        return _cache[cache_key]

    league = UNDERSTAT_LEAGUES.get(competition_code)
    if not league:
        return []

    try:
        from understatapi import UnderstatClient
        async with UnderstatClient() as client:
            players_data = await client.league(league=league).get_player_data(season=str(season))

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

    except ImportError:
        logger.warning("understatapi not installed. pip install understatapi")
        return []
    except Exception as e:
        logger.error(f"Understat error for {competition_code}: {e}")
        return []


async def get_player_shots(player_id: str) -> list:
    """
    Todos los disparos de un jugador con coordenadas X,Y para shot map.
    Exactamente lo que necesitan tus notebooks de PostMatch.
    """
    cache_key = f"understat_shots_{player_id}"
    if cache_key in _cache:
        return _cache[cache_key]

    try:
        from understatapi import UnderstatClient
        async with UnderstatClient() as client:
            shots_data = await client.player(player=player_id).get_shot_data()

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

    except Exception as e:
        logger.error(f"Understat shots error for {player_id}: {e}")
        return []


async def get_match_shots(match_id: str) -> dict:
    """
    Disparos de un partido con coordenadas — para shot maps estilo PostMatch.
    Devuelve disparos separados por equipo local/visitante.
    """
    cache_key = f"understat_match_{match_id}"
    if cache_key in _cache:
        return _cache[cache_key]

    try:
        from understatapi import UnderstatClient
        async with UnderstatClient() as client:
            shot_data = await client.match(match=match_id).get_shot_data()

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

    except Exception as e:
        logger.error(f"Understat match error {match_id}: {e}")
        return {}


async def get_league_teams_xg(competition_code: str, season: int = 2024) -> list:
    """xG por equipo en la liga — para el dashboard"""
    cache_key = f"understat_teams_{competition_code}_{season}"
    if cache_key in _cache:
        return _cache[cache_key]

    league = UNDERSTAT_LEAGUES.get(competition_code)
    if not league:
        return []

    try:
        from understatapi import UnderstatClient
        async with UnderstatClient() as client:
            teams_data = await client.league(league=league).get_team_data(season=str(season))

        result = []
        for team_name, team_data in teams_data.items():
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

    except Exception as e:
        logger.error(f"Understat teams error {competition_code}: {e}")
        return []
