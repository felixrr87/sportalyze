# -*- coding: utf-8 -*-
"""
PRUEBAS DE QUÉ TEMPORADA ES HOY
===============================
    python3 -m pytest tests/test_temporada.py -v

EL FALLO QUE ESTAS PRUEBAS IMPIDEN

La temporada estaba escrita a mano como 2024 en cinco rutas y en el
scraper. Toda la parte de jugadores —Cartas FIFA, Scouting ML,
Comparador, Watchlist— enseñaba la temporada 2024/25, que acabó hace
año y medio, mientras la clasificación, los partidos y el Simulador
iban de la temporada en curso. Dos años distintos en la misma
pantalla.

Se vio comparando la plantilla del Barça entre las dos fuentes:
football-data decía Gabriel Jesus y Rodri, Understat decía Lewandowski
y Ter Stegen.

Medido el día que se encontró:

    temporada 2024   590 jugadores, hasta 3.114 minutos   (entera)
    temporada 2026   473 jugadores, hasta   720 minutos   (9 jornadas)

Y explica por qué los filtros iban raros: 400 minutos mínimos es un
filtro suave en una temporada entera y durísimo en octubre.
"""
import os
import sys
from datetime import date

import pytest

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(AQUI))

from backend.temporada import (MES_DE_CORTE, nombre_temporada,  # noqa: E402
                               temporada_actual)


@pytest.mark.parametrize("hoy,espera", [
    (date(2026, 10, 18), 2026),   # el día que se encontró el fallo
    (date(2026, 8, 15), 2026),    # agosto: ya hay jornadas jugadas
    (date(2026, 7, 1), 2026),     # julio: pretemporada, cuenta como nueva
    (date(2026, 6, 30), 2025),    # junio: la que acaba de terminar
    (date(2027, 1, 1), 2026),     # enero: sigue siendo la que empezó en 2026
    (date(2027, 5, 31), 2026),    # mayo: final de temporada
    (date(2027, 8, 1), 2027),     # y vuelta a empezar
])
def test_la_temporada_sale_de_la_fecha(hoy, espera):
    assert temporada_actual(hoy) == espera


def test_el_corte_esta_en_julio_y_no_en_agosto():
    """A propósito: a primeros de agosto ya hay jornadas jugadas en
    algunas ligas. Con el corte en agosto, pedir datos el 2 de agosto
    daría la temporada de hace un año ENTERA, que es exactamente el
    fallo que esto arregla."""
    assert MES_DE_CORTE == 7


def test_el_nombre_se_escribe_como_todo_el_mundo():
    assert nombre_temporada(2026) == "2026/27"
    assert nombre_temporada(1999) == "1999/00"


def test_no_queda_ninguna_temporada_escrita_a_mano():
    """La raíz del fallo: un 2024 clavado en seis sitios.

    Se mira el ÁRBOL DE SINTAXIS, no el texto. La primera versión de
    esta prueba buscaba el patrón «= 20xx» con una expresión regular y
    saltaba con una línea de documentación que decía «2026 = 2026/27»:
    un falso positivo de mi propia prueba. Con el árbol sólo se miran
    asignaciones y valores por defecto de verdad.
    """
    import ast

    raiz = os.path.dirname(AQUI)
    culpables = []

    def un_anyo(nodo):
        return (isinstance(nodo, ast.Constant)
                and isinstance(nodo.value, int)
                and 2010 <= nodo.value <= 2035)

    ficheros = [os.path.join(raiz, "main.py")]
    for carpeta, _, fs in os.walk(os.path.join(raiz, "backend")):
        if "__pycache__" in carpeta:
            continue
        ficheros += [os.path.join(carpeta, f) for f in fs
                     if f.endswith(".py") and f != "temporada.py"]

    for ruta in ficheros:
        with open(ruta, encoding="utf-8") as fh:
            arbol = ast.parse(fh.read(), ruta)
        for nodo in ast.walk(arbol):
            # valores por defecto de los argumentos: season=2024
            if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for d in list(nodo.args.defaults) + list(nodo.args.kw_defaults):
                    if un_anyo(d):
                        culpables.append(
                            f"{os.path.basename(ruta)}:{d.lineno}: "
                            f"{nodo.name}() trae {d.value} por defecto")
                    # Query(2024)
                    if isinstance(d, ast.Call):
                        for a in list(d.args) + [k.value for k in d.keywords]:
                            if un_anyo(a):
                                culpables.append(
                                    f"{os.path.basename(ruta)}:{a.lineno}: "
                                    f"{nodo.name}() trae {a.value} por defecto")
            # asignaciones: TEMPORADA = 2024
            if isinstance(nodo, ast.Assign) and un_anyo(nodo.value):
                culpables.append(f"{os.path.basename(ruta)}:{nodo.lineno}: "
                                 f"asignado {nodo.value.value}")

    assert not culpables, (
        "temporadas escritas a mano:\n  " + "\n  ".join(culpables))


def test_las_rutas_no_traen_temporada_por_defecto():
    """Deben traer None y resolverla, no un año fijo."""
    import main
    for ruta in main.app.routes:
        fn = getattr(ruta, "endpoint", None)
        if not fn:
            continue
        import inspect
        try:
            firma = inspect.signature(fn)
        except (TypeError, ValueError):
            continue
        p = firma.parameters.get("season")
        if p is None:
            continue
        por_defecto = getattr(p.default, "default", p.default)
        assert por_defecto is None, (
            f"{ruta.path} trae season={por_defecto!r} por defecto")


def test_la_respuesta_de_jugadores_dice_de_que_temporada_es(monkeypatch):
    """Quien mire las cifras tiene que poder saber de qué año son. Si
    no se dice, una pantalla puede quedarse anunciando un año y
    enseñando otro, que es lo que pasaba."""
    from fastapi.testclient import TestClient
    import main

    async def falsa(codigo, temporada=None):
        return [{"player_id": 1, "name": "Uno", "team": "Equipo",
                 "position": "F", "time": 900, "games": 10, "goals": 5,
                 "assists": 2, "xG": 4.0, "npxG": 3.5, "xA": 1.5,
                 "shots": 30, "key_passes": 20, "xGChain": 7.0,
                 "xGBuildup": 3.0}]

    monkeypatch.setattr(main, "get_league_players", falsa)
    d = TestClient(main.app).get("/api/players/PD?limit=10&min_minutes=0").json()
    assert d["season"] == temporada_actual()
    assert d["temporada"] == nombre_temporada(temporada_actual())
