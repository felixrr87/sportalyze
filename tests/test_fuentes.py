# tests/test_fuentes.py
# ============================================================
# Las pruebas que impiden que vuelva a pasar lo que pasó.
#
#     pytest -q
#
# No necesitan red ni clave de API: la fuente externa se sustituye por
# un doble. Lo que se comprueba no es que Understat esté levantado, es
# que NUESTRO código reacciona bien tanto si contesta como si no.
#
# EL FALLO QUE ORIGINÓ ESTE ARCHIVO
# ---------------------------------
# understatapi 0.7.1 es síncrona y el código la llamaba con `async
# with` y `await`. Cada llamada reventaba, la excepción se tragaba, se
# devolvía [], y la API respondía:
#
#     HTTP 200  {"players": [], "summary": {}, "top_prospects": []}
#
# Un club leyendo eso entiende "no hay jugadores que encajen". La
# verdad era "la fuente lleva rota desde el primer día".
# ============================================================
import asyncio
import inspect

import pytest
from fastapi.testclient import TestClient

import main
from backend.errors import FuenteNoDisponible
from backend.scrapers import understat


# ── 1 · la librería es síncrona, y hay que llamarla como tal ──────

def test_understatapi_sigue_siendo_sincrona():
    """Si algún día understatapi se vuelve async, esta prueba avisa.

    Mientras sea síncrona, llamarla con `async with` es un error, y es
    exactamente el error que tuvimos.
    """
    from understatapi import UnderstatClient
    assert hasattr(UnderstatClient, "__enter__"), "ya no es un context manager"
    assert not hasattr(UnderstatClient, "__aenter__"), (
        "understatapi ahora SÍ es async: revisa backend/scrapers/understat.py")
    assert not inspect.iscoroutinefunction(
        UnderstatClient().league(league="EPL").get_player_data), (
        "get_player_data ahora es corrutina: revisa cómo la llamamos")


def test_el_codigo_no_usa_async_with_con_el_cliente():
    """El error original, buscado por su nombre en el archivo."""
    fuente = open(understat.__file__, encoding="utf-8").read()
    assert "async with UnderstatClient" not in fuente
    assert "await client." not in fuente


# ── 2 · si la fuente falla, se nota ───────────────────────────────

class _ClienteRoto:
    def __enter__(self):
        raise ConnectionError("understat.com no contesta")

    def __exit__(self, *a):
        return False


class _ClienteBueno:
    """Devuelve dos jugadores con la forma real de Understat."""

    FILAS = [
        {"id": "1", "player_name": "Jugador Uno", "team_title": "Equipo A",
         "position": "F S", "games": "10", "time": "900", "goals": "5",
         "xG": "4.321", "assists": "2", "xA": "1.5", "shots": "30",
         "key_passes": "12", "npg": "5", "npxG": "4.0",
         "xGChain": "6.1", "xGBuildup": "2.2"},
        {"id": "2", "player_name": "Jugador Dos", "team_title": "Equipo B",
         "position": "M C", "games": "9", "time": "450", "goals": "1",
         "xG": "0.8", "assists": "4", "xA": "3.2", "shots": "9",
         "key_passes": "25", "npg": "1", "npxG": "0.8",
         "xGChain": "5.0", "xGBuildup": "3.9"},
    ]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def league(self, league):
        return self

    def get_player_data(self, season):
        return self.FILAS


def _usar(cliente, monkeypatch):
    import understatapi
    monkeypatch.setattr(understatapi, "UnderstatClient", cliente)
    understat._cache.clear()


def test_fuente_caida_lanza_error_y_no_lista_vacia(monkeypatch):
    _usar(_ClienteRoto, monkeypatch)
    with pytest.raises(FuenteNoDisponible):
        asyncio.run(understat.get_league_players("PL", 2024))


def test_fuente_buena_devuelve_datos_parseados(monkeypatch):
    _usar(_ClienteBueno, monkeypatch)
    jug = asyncio.run(understat.get_league_players("PL", 2024))
    assert len(jug) == 2
    uno = jug[0]
    assert uno["name"] == "Jugador Uno"
    assert uno["xG"] == 4.32                      # redondeado a 2
    assert uno["time"] == 900
    # xG por 90 minutos: 4.321 / 900 * 90 = 0.432
    assert uno["xG_per90"] == pytest.approx(0.432, abs=1e-3)
    # goles menos xG: 5 - 4.321 = 0.68
    assert uno["goals_diff"] == pytest.approx(0.68, abs=1e-2)


def test_liga_no_cubierta_si_devuelve_vacio(monkeypatch):
    """Un vacío legítimo: Understat no cubre esa competición."""
    _usar(_ClienteBueno, monkeypatch)
    assert asyncio.run(understat.get_league_players("XXX", 2024)) == []


# ── 3 · la API: 503 cuando no se sabe, nunca 200 vacío ────────────

@pytest.fixture
def cliente():
    return TestClient(main.app, raise_server_exceptions=False)


def test_scouting_con_la_fuente_caida_da_503(cliente, monkeypatch):
    """LA PRUEBA QUE IMPORTA.

    Antes esto devolvía 200 con {"players": []}. Si alguien vuelve a
    tragarse la excepción, esta prueba se pone roja.
    """
    _usar(_ClienteRoto, monkeypatch)
    r = cliente.get("/api/scouting/PL?position=FW")
    assert r.status_code == 503, (
        "la fuente está caída y la API ha contestado %d: %s"
        % (r.status_code, r.text[:120]))
    assert "players" not in r.json(), "no puede devolver una lista de jugadores"


def test_jugadores_con_la_fuente_caida_da_503(cliente, monkeypatch):
    _usar(_ClienteRoto, monkeypatch)
    assert cliente.get("/api/players/PL").status_code == 503


def test_la_ruta_de_jugadores_se_puede_llamar_sin_parametros(cliente, monkeypatch):
    """Antes: 422, porque max_age valía 99 con un máximo de 50."""
    _usar(_ClienteBueno, monkeypatch)
    r = cliente.get("/api/players/PL")
    assert r.status_code != 422, "la ruta se rechaza a sí misma: " + r.text[:200]
    assert r.status_code == 200
    assert r.json()["total"] == 2


def test_ningun_valor_por_defecto_incumple_su_propio_limite():
    """Barre TODAS las rutas buscando el error que tuvimos, no sólo esa."""
    from fastapi.routing import APIRoute
    from fastapi.params import Query as QueryParam

    malos = []
    for ruta in main.app.routes:
        if not isinstance(ruta, APIRoute):
            continue
        for nombre, par in inspect.signature(ruta.endpoint).parameters.items():
            d = par.default
            if not isinstance(d, QueryParam) or d.default is ...:
                continue
            v = d.default
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                continue
            # Según la versión, los límites están como atributo o dentro
            # de .metadata (annotated-types). Se miran los dos sitios.
            tope = getattr(d, "le", None)
            suelo = getattr(d, "ge", None)
            for m in getattr(d, "metadata", []) or []:
                tope = getattr(m, "le", tope)
                suelo = getattr(m, "ge", suelo)
            if tope is not None and v > tope:
                malos.append(f"{ruta.path}:{nombre} por defecto {v} > le {tope}")
            if suelo is not None and v < suelo:
                malos.append(f"{ruta.path}:{nombre} por defecto {v} < ge {suelo}")
    assert not malos, "valores por defecto imposibles:\n  " + "\n  ".join(malos)


def test_health_responde_siempre(cliente):
    r = cliente.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


# ── 4 · el scouting: dos filtros que descartaban a todo el mundo ──
#
# Con Understat ya funcionando, /api/scouting SEGUÍA devolviendo
# {"players": []} con un 200. Por dos motivos independientes:
#
#   1. Understat no devuelve "FW". Devuelve "F S", "F M S", "D F M".
#      El filtro comparaba position == "FW" y coincidía con CERO de
#      los 447 jugadores de la Premier.
#   2. Understat no trae la edad. El filtro usaba 99 por defecto y
#      descartaba a todos contra un máximo de 25.
#
# Las posiciones de aquí abajo están copiadas de una respuesta real.

from backend.ml.scouting import puesto, run_scouting_pipeline  # noqa: E402

POSICIONES_REALES = {
    "F M": "FW", "F": "FW", "F S": "FW", "F M S": "FW",
    "M": "MF", "M S": "MF",
    "D": "DF", "D S": "DF", "D M": "DF", "D M S": "DF", "D F M": "DF",
    "GK": "GK", "": "", "S": "",
}


def test_las_posiciones_de_understat_se_traducen():
    malos = {c: puesto(c) for c, e in POSICIONES_REALES.items() if puesto(c) != e}
    assert not malos, "posiciones mal traducidas: %r" % malos


def test_ningun_jugador_real_vale_FW_tal_cual():
    """El error original: comparar con 'FW' no casa con nada."""
    assert all(c != "FW" for c in POSICIONES_REALES if c)


def _plantilla():
    """Jugadores con la forma real: con posición de Understat y SIN edad."""
    return [
        {"name": "Delantero Uno", "position": "F M", "time": 3000,
         "goals": 20, "xG": 18.0, "assists": 5, "xA": 4.0, "shots": 90,
         "key_passes": 40, "npg": 18, "npxG": 16.0, "xG_per90": 0.54,
         "xA_per90": 0.12, "xGChain": 22.0, "xGBuildup": 6.0, "games": 34},
        {"name": "Delantero Dos", "position": "F S", "time": 1200,
         "goals": 6, "xG": 7.5, "assists": 2, "xA": 2.5, "shots": 40,
         "key_passes": 18, "npg": 6, "npxG": 7.0, "xG_per90": 0.56,
         "xA_per90": 0.19, "xGChain": 9.0, "xGBuildup": 3.0, "games": 25},
        {"name": "Medio Uno", "position": "M S", "time": 2500,
         "goals": 4, "xG": 3.5, "assists": 9, "xA": 8.0, "shots": 30,
         "key_passes": 70, "npg": 4, "npxG": 3.5, "xG_per90": 0.13,
         "xA_per90": 0.29, "xGChain": 14.0, "xGBuildup": 9.0, "games": 30},
    ]


def test_el_scouting_encuentra_delanteros():
    """LA PRUEBA QUE IMPORTA: antes salían cero."""
    r = run_scouting_pipeline(_plantilla(), position="FW", min_minutes=500)
    nombres = [p["name"] for p in r["players"]]
    assert len(nombres) == 2, "esperaba 2 delanteros y salen %d: %r" % (
        len(nombres), nombres)
    assert "Medio Uno" not in nombres, "se ha colado un centrocampista"


def test_sin_edades_el_filtro_de_edad_no_borra_a_todos():
    """Antes, max_age=25 sin dato de edad dejaba la lista vacía."""
    r = run_scouting_pipeline(_plantilla(), position="FW", max_age=25,
                              min_minutes=500)
    assert len(r["players"]) == 2


def test_y_avisa_de_que_no_ha_aplicado_la_edad():
    """Ignorar un parámetro en silencio es mentir."""
    r = run_scouting_pipeline(_plantilla(), position="FW", max_age=21,
                              min_minutes=500)
    texto = " ".join(r.get("avisos", []))
    assert "edad" in texto.lower(), "no avisa de que se salta el filtro: %r" % r.get("avisos")


def test_si_no_hay_nadie_lo_explica():
    r = run_scouting_pipeline(_plantilla(), position="GK", min_minutes=500)
    assert r["players"] == []
    assert r.get("avisos"), "lista vacía sin explicar por qué"


# ── 5 · la edad de la plantilla ──────────────────────────────────
# football-data sí trae la fecha de nacimiento de cada jugador, así
# que la media de edad del equipo se puede calcular. Comprobado con
# el Arsenal: 25 jugadores, media 25,7, del 16 al 32.

from datetime import date  # noqa: E402

from backend.scrapers.football_data import edad, resumen_edades  # noqa: E402

HOY = date(2026, 10, 16)


def test_la_edad_son_anos_cumplidos():
    """Restar los años a secas da un año de más casi medio año."""
    assert edad("2000-12-31", HOY) == 25     # aún no los ha cumplido
    assert edad("2000-10-16", HOY) == 26     # justo hoy
    assert edad("2000-10-17", HOY) == 25     # mañana


def test_sin_fecha_devuelve_nada_y_no_un_cero():
    for malo in ("", None, "malo", "0000-00-00"):
        assert edad(malo, HOY) is None


def test_las_edades_imposibles_se_descartan():
    assert edad("1960-01-01", HOY) is None   # 66 años
    assert edad("2015-01-01", HOY) is None   # 11 años


def test_el_resumen_dice_sobre_cuantos_ha_contado():
    r = resumen_edades([20, 25, 30])
    assert r == {"media": 25.0, "mas_joven": 20, "mas_veterano": 30,
                 "con_fecha": 3}


def test_una_plantilla_sin_fechas_no_inventa_una_media():
    r = resumen_edades([])
    assert r["media"] is None and r["con_fecha"] == 0


# ── 6 · ninguna ruta puede inventarse los datos ──────────────────
#
# Había una ruta, /api/viz/shotmap-custom, que generaba las posiciones
# de los disparos con random.gauss, el xG con random.uniform y el pie
# con el que se remataba con random.choice. Devolvía un PNG igual que
# el de un mapa de tiro real, sin nada que avisara.
#
# El frontend no la usaba, pero estaba publicada. Estas pruebas están
# para que no vuelva ni ella ni ninguna parecida.

def test_no_existe_la_ruta_que_inventaba_tiros():
    rutas = [getattr(r, "path", "") for r in main.app.routes]
    assert "/api/viz/shotmap-custom" not in rutas


def test_main_no_genera_datos_al_azar():
    """`random` no pinta nada en una API que sirve datos medidos."""
    fuente = open(main.__file__, encoding="utf-8").read()
    # se ignoran los comentarios: ahí sí se explica lo que pasó
    codigo = "\n".join(l for l in fuente.split("\n")
                       if not l.strip().startswith("#"))
    for prohibido in ("random.gauss", "random.uniform", "random.choice",
                      "import random", "simulated_shots"):
        assert prohibido not in codigo, (
            "main.py vuelve a generar datos: %r" % prohibido)


def test_el_mapa_de_tiro_real_sigue_existiendo():
    rutas = [getattr(r, "path", "") for r in main.app.routes]
    assert "/api/viz/shotmap/{player_id}" in rutas


def test_los_nombres_de_liga_son_los_que_entiende_understatapi():
    """Comparado contra la lista de la PROPIA librería, no contra una
    copia escrita a mano aquí.

    Aquí ponía "La_liga" y understatapi espera "La_Liga". Una letra, y
    con ella toda la parte de jugadores de La Liga —cartas, scouting,
    comparador, watchlist— devolvía error. Sólo la de La Liga: las
    otras cinco iban bien, así que probando por encima no se veía.

    Si la librería cambia sus nombres o alguien añade una liga mal
    escrita, esto salta aquí y no en producción.
    """
    from understatapi.endpoints.base import BaseEndpoint

    from backend.scrapers.understat import UNDERSTAT_LEAGUES

    validas = set(BaseEndpoint.leagues)
    malas = {c: n for c, n in UNDERSTAT_LEAGUES.items() if n not in validas}
    assert not malas, (
        f"understatapi no conoce estos nombres: {malas}. "
        f"Los que acepta son: {sorted(validas)}")


def test_la_liga_esta_mapeada():
    """La que más se va a mirar desde España. Que no se caiga del
    diccionario en un refactor."""
    from backend.scrapers.understat import UNDERSTAT_LEAGUES
    assert UNDERSTAT_LEAGUES["PD"] == "La_Liga"


# ══════════════════════════════════════════════════════════════════
# LOS TIROS DE UN JUGADOR SON DE TODA SU CARRERA
# ══════════════════════════════════════════════════════════════════
#
# Esto no se vio hasta probarlo con datos reales. La ficha de Raphinha
# decía arriba "590 min en 8 partidos · 26 tiros" y debajo pintaba 550
# tiros, el primero de un Brest–Rennes de 2019: Understat devuelve en
# esa ruta los tiros de la CARRERA entera.
#
# O sea que la cabecera y el mapa contaban temporadas distintas, y el
# "goles menos xG" de debajo se calculaba sobre siete años. No es un
# mapa mal dibujado: es otra pregunta contestada sin avisar.

TIROS_DE_PRUEBA = [
    {"id": "1", "season": "2026", "minute": 10, "result": "Goal", "xG": 0.5},
    {"id": "2", "season": "2026", "minute": 20, "result": "SavedShot", "xG": 0.1},
    {"id": "3", "season": "2019", "minute": 30, "result": "Goal", "xG": 0.3},
    {"id": "4", "season": "2024", "minute": 40, "result": "MissedShots", "xG": 0.2},
]


def _tiros_falsos(monkeypatch):
    async def falso(player_id):
        return list(TIROS_DE_PRUEBA)
    monkeypatch.setattr(main, "get_player_shots", falso)


def test_los_tiros_sin_temporada_son_los_de_toda_la_carrera(cliente, monkeypatch):
    _tiros_falsos(monkeypatch)
    d = cliente.get("/api/player/999/shots").json()
    assert d["total"] == 4
    assert d["temporada"] is None
    # Y aunque no filtre, dice de qué años son: quien mire la respuesta
    # tiene que poder enterarse de que ahí dentro hay siete temporadas.
    assert d["por_temporada"] == {"2026": 2, "2019": 1, "2024": 1}


def test_los_tiros_con_temporada_son_solo_los_de_esa_temporada(cliente, monkeypatch):
    _tiros_falsos(monkeypatch)
    d = cliente.get("/api/player/999/shots?season=2026").json()
    assert d["total"] == 2
    assert [t["id"] for t in d["shots"]] == ["1", "2"]
    assert d["temporada"] == "2026/27"


def test_filtrar_los_tiros_no_esconde_lo_que_deja_fuera(cliente, monkeypatch):
    """Filtrar en silencio es tan malo como no filtrar.

    Si la ficha enseña 2 tiros de los 4 que hay, tiene que poder decir
    cuántos se ha dejado fuera y de qué años eran. Si no, el visitante
    cree que ése es todo el historial del jugador.
    """
    _tiros_falsos(monkeypatch)
    d = cliente.get("/api/player/999/shots?season=2026").json()
    assert d["total_carrera"] == 4
    assert d["total_carrera"] - d["total"] == 2
    assert d["por_temporada"]["2019"] == 1


def test_una_temporada_sin_tiros_da_lista_vacia_y_no_la_carrera(cliente, monkeypatch):
    """El fallo al revés: que al no encontrar nada enseñe todo."""
    _tiros_falsos(monkeypatch)
    d = cliente.get("/api/player/999/shots?season=2001").json()
    assert d["shots"] == []
    assert d["total_carrera"] == 4


def test_el_scouting_dice_el_ano_de_la_temporada_y_no_solo_el_texto(cliente, monkeypatch):
    """La ficha necesita el año suelto para pedir los tiros.

    Si sólo viniera "2026/27", la pantalla tendría que recortar la
    cadena, y eso es pedir que algún día se recorte mal.
    """
    _usar(_ClienteBueno, monkeypatch)
    d = cliente.get("/api/scouting/PD?position=FW&min_minutes=0").json()
    assert isinstance(d.get("season"), int)
    assert d["temporada"].startswith(str(d["season"]))


# ══════════════════════════════════════════════════════════════════
# LA RUTA DEL INFORME DE UN PARTIDO DE ESTA TEMPORADA
# ══════════════════════════════════════════════════════════════════
#
# Lo que se comprueba aquí es sobre todo que SE NIEGUE bien. Un
# informe del partido equivocado es el peor fallo posible de esta
# pantalla, porque el visitante no tiene forma de notarlo: vería un
# mapa de tiros perfectamente creíble de otro partido.

CALENDARIO = [
    {"match_id": "1", "jugado": True, "fecha": "2026-10-18",
     "local": "Barcelona", "visitante": "Girona",
     "clave_local": "barcelona", "clave_visitante": "girona",
     "goles_local": 2, "goles_visitante": 1, "xg_local": 1.9, "xg_visitante": 0.8},
    {"match_id": "2", "jugado": False, "fecha": "2026-10-25",
     "local": "Real Madrid", "visitante": "Getafe",
     "clave_local": "real madrid", "clave_visitante": "getafe",
     "goles_local": None, "goles_visitante": None},
]

TIROS_PARTIDO = {
    "home_shots": [{"minute": 20, "result": "Goal", "x": 88.0, "y": 50.0,
                    "xG": 0.3, "player": "A", "situation": "OpenPlay",
                    "shot_type": "RightFoot"},
                   {"minute": 60, "result": "Goal", "x": 90.0, "y": 48.0,
                    "xG": 0.5, "player": "B", "situation": "OpenPlay",
                    "shot_type": "Head"}],
    "away_shots": [{"minute": 70, "result": "Goal", "x": 85.0, "y": 55.0,
                    "xG": 0.25, "player": "C", "situation": "FromCorner",
                    "shot_type": "LeftFoot"}],
}


def _fuente_de_partidos(monkeypatch, calendario=None, tiros=None, roster=None):
    async def cal(code, season=None):
        return CALENDARIO if calendario is None else calendario
    async def sh(mid):
        return TIROS_PARTIDO if tiros is None else tiros
    async def ro(mid):
        if roster == "falla":
            raise main.FuenteNoDisponible("Understat", "se cayó")
        return roster or {"local": [], "visitante": []}
    monkeypatch.setattr(main, "get_league_fixtures", cal)
    monkeypatch.setattr(main, "get_match_shots", sh)
    monkeypatch.setattr(main, "get_match_roster", ro)


def _pedir(cliente, local="FC Barcelona", visitante="Girona FC",
           fecha="2026-10-18", code="PD"):
    return cliente.get(f"/api/informe-liga/{code}",
                       params={"local": local, "visitante": visitante,
                               "fecha": fecha})


def test_el_informe_de_liga_empareja_y_sale(cliente, monkeypatch):
    _fuente_de_partidos(monkeypatch)
    r = _pedir(cliente)
    assert r.status_code == 200
    d = r.json()
    assert d["local"] == "Barcelona" and d["visitante"] == "Girona"
    assert (d["goles_local"], d["goles_visitante"]) == (2, 1)
    assert d["fuente"] == "Understat"
    # el xG del gráfico y el del resumen, lo mismo
    assert round(d["carrera"][-1]["local"], 2) == d["equipos"]["Barcelona"]["xg"]


def test_el_informe_dice_de_que_no_tiene_datos(cliente, monkeypatch):
    _fuente_de_partidos(monkeypatch)
    d = _pedir(cliente).json()
    assert "red de pases" in d["sin_datos_de"]


def test_se_niega_si_no_encuentra_el_partido_y_dice_cuales_habia(cliente, monkeypatch):
    _fuente_de_partidos(monkeypatch)
    r = _pedir(cliente, local="Sevilla FC", visitante="Real Betis")
    assert r.status_code == 404
    d = r.json()["detail"]
    assert d["motivo"] == "nombres_no_encajan"
    # y enseña qué partidos SÍ había ese día, que es lo que necesita
    # quien está mirando para entender qué ha pasado
    assert "Barcelona - Girona" in d["partidos_ese_dia"]


def test_se_niega_si_ese_dia_no_hay_nada(cliente, monkeypatch):
    _fuente_de_partidos(monkeypatch)
    r = _pedir(cliente, fecha="2026-03-01")
    assert r.status_code == 404
    assert r.json()["detail"]["motivo"] == "sin_partidos_ese_dia"


def test_se_niega_con_un_partido_que_no_se_ha_jugado(cliente, monkeypatch):
    _fuente_de_partidos(monkeypatch)
    r = _pedir(cliente, local="Real Madrid CF", visitante="Getafe CF",
               fecha="2026-10-25")
    assert r.status_code == 404
    assert r.json()["detail"]["motivo"] == "todavia_no_jugado"


def test_una_competicion_que_understat_no_cubre_lo_dice(cliente, monkeypatch):
    _fuente_de_partidos(monkeypatch, calendario=[])
    r = _pedir(cliente, code="CL")
    assert r.status_code == 404
    d = r.json()["detail"]
    assert d["motivo"] == "sin_calendario"
    assert "Champions" in d["detalle"]


def test_si_understat_se_cae_es_503_y_no_un_informe_vacio(cliente, monkeypatch):
    async def cae(code, season=None):
        raise main.FuenteNoDisponible("Understat", "no contesta")
    monkeypatch.setattr(main, "get_league_fixtures", cae)
    r = _pedir(cliente)
    assert r.status_code == 503
    assert r.json()["detail"]["motivo"] == "fuente_caida"


def test_si_fallan_las_alineaciones_el_informe_sale_igual(cliente, monkeypatch):
    """Media respuesta buena vale más que un error entero."""
    _fuente_de_partidos(monkeypatch, roster="falla")
    r = _pedir(cliente)
    assert r.status_code == 200
    d = r.json()
    assert d["aviso_alineaciones"]
    assert d["equipos"]["Barcelona"]["xg"] > 0


def test_roster_in_y_roster_out_no_se_publican_como_minutos():
    """Lo parecían, y no lo son.

    Se publicaron como "entró en el minuto X" y en pantalla salió
    «Gerard Martín ▲806581». Son identificadores internos del cambio.
    El minuto del cambio NO está en esa respuesta de Understat.

    Esta prueba lee el código y comprueba que nadie los vuelve a
    sacar al exterior, porque el siguiente que los vea los tomará por
    minutos otra vez: se llaman "in" y "out" y son números pequeños
    en algunos partidos.
    """
    import inspect
    from backend.scrapers import understat
    fuente = inspect.getsource(understat.get_match_roster)
    assert '"entro"' not in fuente and '"salio"' not in fuente, (
        "roster_in/roster_out han vuelto a salir como si fueran minutos")
    assert '"suplente"' in fuente, (
        "falta el dato que SÍ es verdad: si salió de inicio o entró")
