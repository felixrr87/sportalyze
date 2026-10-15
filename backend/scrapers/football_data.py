# backend/scrapers/football_data.py
# ============================================================
# Conector a football-data.org API v4
# Tu API key: 18f8f363554247f69bba9b7a9d049da8
# Límite: 10 req/min en tier gratuito
# ============================================================

import httpx
import asyncio
import logging
from datetime import date
from cachetools import TTLCache
from backend.config import FOOTBALL_API_KEY, FOOTBALL_API_BASE, CACHE_TTL, LEAGUES

logger = logging.getLogger(__name__)

# ── CACHÉ, Y POR QUÉ IMPORTA TANTO ──────────────────────────────
#
# El plan gratuito de football-data.org son DIEZ peticiones por
# minuto. Y abrir la ficha de un equipo gasta DOS (el perfil y sus
# últimos partidos). O sea: cinco equipos y se acabó el minuto.
#
# Eso pasaba de verdad: pinchabas seis equipos seguidos y a partir del
# quinto dejaban de cargar, sin más explicación.
#
# Con una caché única de una hora para todo no basta, porque cada
# equipo nuevo es una petición nueva. La solución es guardar cada cosa
# el tiempo que de verdad le corresponde:
#
#   la plantilla de un equipo    cambia en el mercado de fichajes
#   la clasificación             cambia cuando acaba una jornada
#   los partidos de hoy          cambian durante el partido
#
# Guardar la plantilla del Arsenal una hora y volver a pedirla es
# tirar una petición de las diez. Guardarla un día no.
_VIDAS = (
    ("/teams/", "/matches", 1800),      # partidos de un equipo: 30 min
    ("/teams/", None, 86400),           # perfil y plantilla: 1 día
    ("/competitions/", "/standings", 600),   # clasificación: 10 min
    ("/competitions/", "/scorers", 3600),    # goleadores: 1 hora
    ("/matches", None, 300),            # partidos de hoy: 5 min
)


def vida(endpoint: str) -> int:
    """Cuántos segundos vale la pena guardar esta respuesta."""
    for empieza, contiene, segundos in _VIDAS:
        if endpoint.startswith(empieza) and (contiene is None or contiene in endpoint):
            return segundos
    return CACHE_TTL


# Una caché por duración, porque TTLCache sólo admite una vida por
# instancia. Son cuatro o cinco, no hace falta nada más complicado.
_caches = {}


def _caja(endpoint: str) -> TTLCache:
    t = vida(endpoint)
    if t not in _caches:
        _caches[t] = TTLCache(maxsize=500, ttl=t)
    return _caches[t]


class LimiteAlcanzado(Exception):
    """La API ha dicho que no por exceso de peticiones.

    Tiene su propia clase para que arriba se pueda distinguir de un
    fallo de verdad y contarle al usuario que sólo hay que esperar.
    """


def edad(nacimiento: str, hoy: date = None) -> int:
    """Años cumplidos a partir de una fecha 'AAAA-MM-DD'.

    Años CUMPLIDOS, no la resta de años: alguien nacido el 31 de
    diciembre de 2000 no tiene 25 años el 1 de enero de 2025.
    Devuelve None si no hay fecha o viene rota, para que quien use
    esto decida qué hacer en vez de comerse un cero.
    """
    if not nacimiento:
        return None
    try:
        a, m, d = (int(x) for x in nacimiento[:10].split("-"))
    except (ValueError, TypeError):
        return None
    h = hoy or date.today()
    años = h.year - a
    if (h.month, h.day) < (m, d):
        años -= 1
    return años if 14 <= años <= 50 else None


def resumen_edades(edades: list) -> dict:
    """Media, extremos y cuántos han contado.

    `con_fecha` NO es decoración: si de 25 jugadores sólo 11 traen
    fecha, la media es de once y hay que poder saberlo.
    """
    if not edades:
        return {"media": None, "mas_joven": None, "mas_veterano": None,
                "con_fecha": 0}
    return {
        "media":        round(sum(edades) / len(edades), 1),
        "mas_joven":    min(edades),
        "mas_veterano": max(edades),
        "con_fecha":    len(edades),
    }


class FootballDataClient:
    """Cliente async para football-data.org API v4"""

    def __init__(self):
        self.headers = {
            "X-Auth-Token": FOOTBALL_API_KEY,
            "Accept": "application/json",
        }
        self.base = FOOTBALL_API_BASE

    async def _get(self, endpoint: str) -> dict:
        """Petición GET con caché y manejo de errores"""
        caja = _caja(endpoint)
        if endpoint in caja:
            logger.debug("Cache hit (%ds): %s", vida(endpoint), endpoint)
            return caja[endpoint]

        url = f"{self.base}{endpoint}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(url, headers=self.headers)
                r.raise_for_status()
                data = r.json()
                caja[endpoint] = data
                return data
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise LimiteAlcanzado(
                    "El plan gratuito permite 10 consultas por minuto y se ha "
                    "llegado al tope. Espera un minuto y vuelve a intentarlo.")
            elif e.response.status_code == 403:
                raise Exception("🔑 API key inválida. Verifica tu clave en football-data.org")
            raise Exception(f"Error API {e.response.status_code}: {e.response.text[:200]}")
        except httpx.TimeoutException:
            raise Exception("⏱️ Timeout — la API tardó demasiado en responder")
        except Exception as e:
            raise Exception(f"Error de conexión: {str(e)}")

    # ── Competiciones ─────────────────────────────────────────

    async def get_competitions(self) -> list:
        """Lista todas las competiciones disponibles con metadata"""
        data = await self._get("/competitions")
        competitions = []
        for c in data.get("competitions", []):
            code = c.get("code", "")
            meta = LEAGUES.get(code, {})
            competitions.append({
                "id":      c["id"],
                "code":    code,
                "name":    c["name"],
                "country": c["area"]["name"],
                "flag":    meta.get("flag", "🌍"),
                "color":   meta.get("color", "#0ea5e9"),
                "emblem":  c.get("emblem"),
                "season":  c.get("currentSeason", {}).get("startDate", "")[:4],
            })
        return competitions

    # ── Clasificaciones ───────────────────────────────────────

    async def get_standings(self, competition_code: str) -> dict:
        """Clasificación completa de una liga"""
        data = await self._get(f"/competitions/{competition_code}/standings")
        meta = LEAGUES.get(competition_code, {})

        standings = data.get("standings", [{}])
        table = standings[0].get("table", []) if standings else []

        result = []
        for entry in table:
            team = entry["team"]
            result.append({
                "position":     entry["position"],
                "team_id":      team["id"],
                "team_name":    team["name"],
                "team_short":   team.get("shortName", team["name"][:12]),
                "team_tla":     team.get("tla", "???"),
                "crest":        team.get("crest"),
                "played":       entry["playedGames"],
                "won":          entry["won"],
                "draw":         entry["draw"],
                "lost":         entry["lost"],
                "goals_for":    entry["goalsFor"],
                "goals_against":entry["goalsAgainst"],
                "goal_diff":    entry["goalDifference"],
                "points":       entry["points"],
                "form":         entry.get("form", ""),
            })

        return {
            "competition": competition_code,
            "name":  meta.get("name", competition_code),
            "flag":  meta.get("flag", "🌍"),
            "color": meta.get("color", "#0ea5e9"),
            "season": data.get("season", {}).get("startDate", "")[:4],
            "table": result,
        }

    # ── Partidos ──────────────────────────────────────────────

    async def get_matches_today(self) -> list:
        """Partidos de hoy en todas las competiciones"""
        data = await self._get("/matches")
        matches = []
        for m in data.get("matches", []):
            comp_code = m.get("competition", {}).get("code", "")
            meta = LEAGUES.get(comp_code, {})
            matches.append({
                "id":          m["id"],
                "competition": m["competition"]["name"],
                "comp_code":   comp_code,
                "flag":        meta.get("flag", "🌍"),
                "date":        m["utcDate"],
                "status":      m["status"],
                "home_team":   m["homeTeam"]["name"],
                "home_crest":  m["homeTeam"].get("crest"),
                "away_team":   m["awayTeam"]["name"],
                "away_crest":  m["awayTeam"].get("crest"),
                "score_home":  m["score"]["fullTime"].get("home"),
                "score_away":  m["score"]["fullTime"].get("away"),
                "minute":      m.get("minute"),
            })
        return matches

    async def get_competition_matches(self, competition_code: str, status: str = None, limit: int = 20) -> list:
        """Partidos de una competición — filtrado por estado"""
        endpoint = f"/competitions/{competition_code}/matches"
        if status:
            endpoint += f"?status={status}"
        data = await self._get(endpoint)
        matches = data.get("matches", [])[-limit:]
        result = []
        for m in reversed(matches):
            result.append({
                "id":         m["id"],
                "matchday":   m.get("matchday"),
                "date":       m["utcDate"][:10],
                "time":       m["utcDate"][11:16],
                "status":     m["status"],
                "home_team":  m["homeTeam"]["name"],
                "home_short": m["homeTeam"].get("shortName", m["homeTeam"]["name"][:12]),
                "home_crest": m["homeTeam"].get("crest"),
                "away_team":  m["awayTeam"]["name"],
                "away_short": m["awayTeam"].get("shortName", m["awayTeam"]["name"][:12]),
                "away_crest": m["awayTeam"].get("crest"),
                "score_home": m["score"]["fullTime"].get("home"),
                "score_away": m["score"]["fullTime"].get("away"),
            })
        return result

    # ── Equipos ───────────────────────────────────────────────

    async def get_team(self, team_id: int) -> dict:
        """Información completa de un equipo, con la edad de la plantilla."""
        data = await self._get(f"/teams/{team_id}")
        squad = []
        edades = []
        for p in data.get("squad", []):
            e = edad(p.get("dateOfBirth", ""))
            if e is not None:
                edades.append(e)
            squad.append({
                "id":           p["id"],
                "name":         p["name"],
                "position":     p.get("position", "Unknown"),
                "date_of_birth":p.get("dateOfBirth", ""),
                "nationality":  p.get("nationality", ""),
                "age":          e,
            })
        return {
            "edades":      resumen_edades(edades),
            "id":          data["id"],
            "name":        data["name"],
            "short_name":  data.get("shortName", data["name"]),
            "tla":         data.get("tla", "???"),
            "crest":       data.get("crest"),
            "address":     data.get("address", ""),
            "website":     data.get("website", ""),
            "founded":     data.get("founded"),
            "club_colors": data.get("clubColors", ""),
            "venue":       data.get("venue", ""),
            "squad":       squad,
        }

    async def get_team_matches(self, team_id: int, limit: int = 10) -> list:
        """Últimos partidos de un equipo"""
        data = await self._get(f"/teams/{team_id}/matches?status=FINISHED&limit={limit}")
        result = []
        for m in data.get("matches", []):
            result.append({
                "date":       m["utcDate"][:10],
                "competition":m["competition"]["name"],
                "home_team":  m["homeTeam"]["name"],
                "away_team":  m["awayTeam"]["name"],
                "score_home": m["score"]["fullTime"].get("home"),
                "score_away": m["score"]["fullTime"].get("away"),
                "is_home":    m["homeTeam"]["id"] == team_id,
            })
        return result

    # ── Goleadores ────────────────────────────────────────────

    async def get_top_scorers(self, competition_code: str, limit: int = 20) -> list:
        """Top goleadores de una competición"""
        data = await self._get(f"/competitions/{competition_code}/scorers?limit={limit}")
        result = []
        for entry in data.get("scorers", []):
            p = entry["player"]
            t = entry.get("team", {})
            result.append({
                "player_id":   p["id"],
                "name":        p["name"],
                "nationality": p.get("nationality", ""),
                "position":    p.get("position", ""),
                "dob":         p.get("dateOfBirth", ""),
                "team_id":     t.get("id"),
                "team_name":   t.get("name", ""),
                "team_crest":  t.get("crest"),
                "goals":       entry.get("goals", 0),
                "assists":     entry.get("assists", 0),
                "played_matches": entry.get("playedMatches", 0),
            })
        return result


# Instancia global
football_client = FootballDataClient()
