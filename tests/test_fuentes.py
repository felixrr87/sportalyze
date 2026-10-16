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
