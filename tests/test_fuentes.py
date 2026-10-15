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
