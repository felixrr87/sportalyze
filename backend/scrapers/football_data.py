# backend/scrapers/football_data.py
# ============================================================
# Conector a football-data.org API v4
#
# LA CLAVE NO VA AQUÍ. Va en la variable de entorno FOOTBALL_API_KEY.
# Estuvo escrita en este comentario, en un repositorio público, y sigue
# en el historial de commits: borrarla de aquí no la borra de ahí. La
# única forma de cerrar el agujero es revocarla en football-data.org y
# sacar una nueva.
#
# Límite del plan gratuito: 10 peticiones por minuto.
# ============================================================

import asyncio
import logging
import re
import time
from collections import deque
from datetime import date

import httpx
from cachetools import TTLCache
from backend.config import FOOTBALL_API_KEY, FOOTBALL_API_BASE, CACHE_TTL, LEAGUES
from backend.errors import ClaveInvalida, CompeticionNoIncluida

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
    ("/competitions/", "/matches", 600),     # temporada entera: 10 min
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


# ── ¿ha funcionado esta clave alguna vez? ────────────────────────
#
# Una sola variable, y es la que permite distinguir «clave rota» de
# «competición fuera de tu plan», porque football-data contesta lo
# mismo a las dos cosas. Se pone a True en cuanto una petición trae
# datos, y ya no vuelve atrás en este arranque.
_LA_CLAVE_HA_FUNCIONADO = False


def _competicion_de(endpoint: str):
    """«/competitions/PD/standings» -> «PD». Si no es de competición, None."""
    m = re.match(r"^/competitions/([A-Z0-9]+)(/|$)", endpoint)
    return m.group(1) if m else None


class FaltaLaClave(Exception):
    """No hay clave de football-data configurada.

    Tiene su propia clase porque es el fallo más probable al subir esto
    a un servidor: se despliega y se olvida la variable de entorno.
    Sin esto, la pantalla decía «403 Forbidden», que es verdad y no
    sirve de nada: parece que la fuente ha dicho que no cuando lo que
    pasa es que no se le ha preguntado con credenciales.
    """

    def __init__(self):
        super().__init__(
            "falta la clave de football-data. Es gratis: se saca en "
            "football-data.org/client/register y se pone en la variable "
            "de entorno FOOTBALL_API_KEY. El informe post-partido y el "
            "relieve funcionan igual sin ella, porque usan StatsBomb.")


class LimiteAlcanzado(Exception):
    """La API ha dicho que no por exceso de peticiones.

    Tiene su propia clase para que arriba se pueda distinguir de un
    fallo de verdad y contarle al usuario que sólo hay que esperar.
    """


# ══════════════════════════════════════════════════════════════════
# EL TURNERO, Y POR QUÉ HACE FALTA PARA ABRIR ESTO A LA GENTE
# ══════════════════════════════════════════════════════════════════
#
# Las diez peticiones por minuto del plan gratuito son DEL PLAN, no de
# cada visitante. En un ordenador, con una persona usándolo, no se nota.
# Con la página abierta a quien entre, cinco personas pinchando equipos
# a la vez se las comen en segundos y TODAS ven un error.
#
# La caché resuelve la mitad: si dos piden lo mismo, la segunda no sale
# a la red. Pero sólo cuando la primera ya ha vuelto. Si llegan a la vez
# —que es lo que pasa cuando compartes un enlace— las dos ven la caché
# vacía y las dos salen.
#
# Por eso aquí hay dos cosas:
#
#   1. UN TURNO: nunca hay más de PETICIONES_POR_MINUTO peticiones en
#      los últimos sesenta segundos. Quien llega de más espera un poco
#      en vez de recibir un 429. Esperar dos segundos es mejor
#      experiencia que un error, y además no quema la clave.
#
#   2. UN VIAJE POR PETICIÓN: si cinco visitantes piden la misma cosa a
#      la vez, sale UNA sola petición y las cinco esperan a esa. Esto
#      ahorra más turnos que ninguna otra cosa, porque lo normal es que
#      todo el mundo mire las mismas ligas.
#
# Nueve y no diez: el contador de football-data va por ventana de un
# minuto y el reloj de aquí no es el suyo. Dejar uno de margen evita
# rozar el tope por un cuarto de segundo de diferencia.
PETICIONES_POR_MINUTO = 9
VENTANA = 60.0

# Más de esto esperando y se prefiere decirlo a tener a alguien mirando
# una ruedecita. Veinte segundos es mucho para una web y poco para
# perder la petición.
ESPERA_MAXIMA = 20.0


class Turnero:
    """Reparte turnos para no pasarse del límite del plan."""

    def __init__(self, cuantas=PETICIONES_POR_MINUTO, ventana=VENTANA):
        self.cuantas = cuantas
        self.ventana = ventana
        self._salidas = deque()          # cuándo salió cada petición
        self._cerrojo = asyncio.Lock()

    def _limpiar(self, ahora):
        while self._salidas and ahora - self._salidas[0] >= self.ventana:
            self._salidas.popleft()

    def espera_estimada(self) -> float:
        """Cuánto habría que esperar ahora mismo. Sin pedir turno."""
        ahora = time.monotonic()
        self._limpiar(ahora)
        if len(self._salidas) < self.cuantas:
            return 0.0
        return max(0.0, self.ventana - (ahora - self._salidas[0]))

    async def turno(self):
        """Espera a que toque. Revienta si la cola es absurda."""
        while True:
            async with self._cerrojo:
                ahora = time.monotonic()
                self._limpiar(ahora)
                if len(self._salidas) < self.cuantas:
                    self._salidas.append(ahora)
                    return
                falta = self.ventana - (ahora - self._salidas[0]) + 0.05
            if falta > ESPERA_MAXIMA:
                raise LimiteAlcanzado(
                    f"ahora mismo hay cola: habría que esperar "
                    f"{falta:.0f} segundos. El plan gratuito de "
                    f"football-data son {self.cuantas + 1} consultas por "
                    f"minuto para todo el mundo a la vez. Vuelve en un "
                    f"minuto, o mira el informe post-partido y el "
                    f"relieve, que no gastan de aquí.")
            await asyncio.sleep(min(falta, 1.0))


_turnero = Turnero()

# Peticiones que están saliendo ahora mismo, para no repetirlas.
_en_vuelo = {}


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
        """Una petición, con caché, turno y sin repetir viajes.

        El orden importa:

          1. ¿Está en la caché? Fuera, ni turno ni nada.
          2. ¿La está pidiendo ya otro? Me cuelgo de la suya.
          3. Pido turno (puede esperar unos segundos).
          4. Vuelvo a mirar la caché: mientras esperaba el turno puede
             haber llegado. Este segundo vistazo parece de más y no lo
             es — es justo lo que ahorra peticiones cuando entra gente
             a la vez.
          5. Salgo a la red.
        """
        caja = _caja(endpoint)
        if endpoint in caja:
            logger.debug("Cache hit (%ds): %s", vida(endpoint), endpoint)
            return caja[endpoint]

        # Si ya hay alguien pidiendo esto, se espera a su respuesta en
        # vez de gastar otro turno en lo mismo.
        if endpoint in _en_vuelo:
            logger.debug("Me cuelgo de una petición en curso: %s", endpoint)
            return await asyncio.shield(_en_vuelo[endpoint])

        tarea = asyncio.ensure_future(self._traer(endpoint, caja))
        _en_vuelo[endpoint] = tarea
        try:
            return await asyncio.shield(tarea)
        finally:
            _en_vuelo.pop(endpoint, None)

    async def _traer(self, endpoint: str, caja) -> dict:
        """El viaje de verdad. Sale uno solo por endpoint a la vez."""
        # Antes de gastar un turno: si no hay clave, no hay nada que
        # intentar. Y se dice lo que pasa, no lo que contesta la API.
        if not FOOTBALL_API_KEY:
            raise FaltaLaClave()

        await _turnero.turno()

        # Segundo vistazo: mientras esperaba el turno pudo llegar.
        if endpoint in caja:
            return caja[endpoint]

        url = f"{self.base}{endpoint}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(url, headers=self.headers)
                r.raise_for_status()
                data = r.json()
                # Esta clave ha traído datos al menos una vez. A partir
                # de aquí, un 400 ya no puede ser "clave inválida".
                global _LA_CLAVE_HA_FUNCIONADO
                _LA_CLAVE_HA_FUNCIONADO = True
                caja[endpoint] = data
                return data
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise LimiteAlcanzado(
                    "El plan gratuito permite 10 consultas por minuto y se ha "
                    "llegado al tope. Espera un minuto y vuelve a intentarlo.")
            elif e.response.status_code == 403:
                raise ClaveInvalida("football-data la ha rechazado con un 403")

            # EL 400 QUE NO ES LO QUE DICE SER
            #
            # football-data contesta a una competición fuera de tu plan
            # con 400 «Your API token is invalid». La clave es válida:
            # en el mismo arranque, Premier y Ligue 1 dieron 200 y La
            # Liga, Serie A y Bundesliga dieron ese 400, con siete
            # segundos entre medias.
            #
            # No se mira el texto del mensaje a propósito: viene en el
            # idioma de quien pregunta («Your API token is invalid» o
            # «Su token de API no es válido»), así que una comprobación
            # por texto se rompe el día que cambian de idioma o de
            # redacción. Se mira un hecho: ¿ha funcionado esta clave
            # alguna vez? Si sí, no está rota.
            if e.response.status_code == 400:
                comp = _competicion_de(endpoint)
                if comp and _LA_CLAVE_HA_FUNCIONADO:
                    raise CompeticionNoIncluida(comp)
                raise ClaveInvalida(
                    f"football-data contesta 400 y esta clave no ha traído "
                    f"datos ni una vez en este arranque")

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

    async def get_competition_season(self, competition_code: str) -> list:
        """TODOS los partidos de la temporada, sin recortar y en crudo.

        Es lo que necesita el simulador: el calendario completo, jugado
        y por jugar. get_competition_matches no sirve porque recorta a
        los últimos `limit` y les da la vuelta.

        Devuelve la lista tal como llega de la API (matchday, utcDate,
        status, homeTeam, awayTeam, score) y es el simulador el que la
        traduce. Así, si football-data cambia algo, se ve en un sitio.

        Una llamada, 380 partidos. Guardada diez minutos.
        """
        data = await self._get(f"/competitions/{competition_code}/matches")
        return data.get("matches", [])

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
