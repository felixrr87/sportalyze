# -*- coding: utf-8 -*-
"""
PRUEBAS DE LA PUNTUACIÓN DE SCOUTING
====================================
    python3 -m pytest tests/test_puntuar.py -v

Sin red.

LO QUE HABÍA, MEDIDO
--------------------
La versión anterior sumaba métricas por un peso y daba por cero las
que no venían. Las que pedía para centrocampistas, defensas y porteros
—entradas, intercepciones, presiones, paradas— Understat no las
publica. Resultado:

    delanteros        llegaban 5 de 8  -> puntuación distorsionada
    centrocampistas   llegaban 2 de 8  -> todos al suelo
    defensas          llegaban 0 de 8  -> TODOS exactamente 40,0
    porteros          llegaban 0 de 8  -> TODOS exactamente 40,0

O sea: una pantalla llamada «Scouting ML» ordenaba a los defensas por
un número constante, y el orden que salía era el orden en que venían
de la fuente.

Estas pruebas existen para que eso no pueda volver. La que más
importa es la última de cada bloque: la que comprueba que el sistema
SE NIEGA en vez de rellenar con ceros.
"""
import os
import sys

import pytest

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(AQUI))

from backend.ml import metricas as M                    # noqa: E402
from backend.ml.puntuar import (PuestoSinDatos, por_90, puntuar,
                                faltan_metricas, _percentiles)  # noqa: E402
from backend.ml.scouting import run_scouting_pipeline    # noqa: E402

# Los campos que Understat devuelve DE VERDAD, ni uno más.
CAMPOS = ("time", "games", "goals", "assists", "xG", "npxG", "xA",
          "shots", "key_passes", "xGChain", "xGBuildup")


def jugador(i, minutos=1800, **extra):
    base = {"player_id": i, "id": i, "name": f"Jugador {i}",
            "team": "Equipo", "position": "F", "time": minutos,
            "games": minutos // 90, "goals": 5, "assists": 3, "xG": 4.5,
            "npxG": 4.0, "xA": 2.5, "shots": 40, "key_passes": 30,
            "xGChain": 9.0, "xGBuildup": 4.0}
    base.update(extra)
    return base


@pytest.fixture
def delanteros():
    # treinta delanteros distintos, para que los percentiles signifiquen algo
    return [jugador(i, minutos=600 + i * 70, goals=i % 17, assists=i % 9,
                    npxG=1.0 + i * 0.4, xA=0.5 + i * 0.25,
                    shots=10 + i * 3, key_passes=5 + i * 2,
                    xGChain=2.0 + i * 0.7) for i in range(30)]


# ════════════════════════════════════════════════════════════════
# POR 90 MINUTOS, NO TOTALES
# ════════════════════════════════════════════════════════════════

def test_por_90_es_por_90():
    assert por_90({"goals": 10, "time": 900}, "goals") == pytest.approx(1.0)
    assert por_90({"goals": 10, "time": 1800}, "goals") == pytest.approx(0.5)


def test_sin_minutos_no_se_divide_por_cero():
    assert por_90({"goals": 3, "time": 0}, "goals") == 0.0
    assert por_90({"goals": 3}, "goals") == 0.0


def test_el_que_juega_la_mitad_y_marca_lo_mismo_puntua_mas():
    """Con totales, quien más juega siempre gana. Ése era el problema:
    la lista salía ordenada por minutos con pinta de ranking."""
    js = [jugador(0, minutos=3000, goals=10, npxG=9.0, xA=4.0,
                  assists=4, shots=60, key_passes=40, xGChain=14.0),
          jugador(1, minutos=1500, goals=10, npxG=9.0, xA=4.0,
                  assists=4, shots=60, key_passes=40, xGChain=14.0)]
    puntuar(js, "FW")
    assert js[1]["score"] > js[0]["score"]


# ════════════════════════════════════════════════════════════════
# PERCENTILES
# ════════════════════════════════════════════════════════════════

def test_los_percentiles_van_de_cero_a_cien():
    p = _percentiles([1, 2, 3, 4, 5])
    assert p[0] == 0.0 and p[-1] == 100.0


def test_los_empates_comparten_percentil():
    """Si tres jugadores tienen cero asistencias, los tres valen lo
    mismo. Darles 0, 25 y 50 según el orden de la lista sería inventar
    una diferencia que no existe."""
    p = _percentiles([0, 0, 0, 5])
    assert p[0] == p[1] == p[2]
    assert p[3] == 100.0


def test_un_solo_jugador_no_tiene_percentil():
    assert _percentiles([7]) == [50.0]


def test_la_puntuacion_reparte(delanteros):
    puntuar(delanteros, "FW")
    scores = [j["score"] for j in delanteros]
    assert min(scores) < 25 and max(scores) > 75
    assert len(set(scores)) > 20, "casi todos iguales: no está repartiendo"


def test_cada_jugador_lleva_sus_percentiles(delanteros):
    """Un número sin su desglose no se puede comprobar."""
    ficha = puntuar(delanteros, "FW")
    etiquetas = {m["etiqueta"] for m in ficha["metricas"]}
    for j in delanteros:
        assert set(j["percentiles"]) == etiquetas
        assert set(j["por_90"]) == etiquetas
        assert all(0 <= v <= 100 for v in j["percentiles"].values())


def test_el_score_sale_de_sus_percentiles(delanteros):
    """A mano, para uno: si esto falla, el número de pantalla no es el
    promedio que dice ser."""
    ficha = puntuar(delanteros, "FW")
    pesos = {m["etiqueta"]: m["peso"] for m in ficha["metricas"]}
    j = delanteros[7]
    esperado = (sum(j["percentiles"][e] * pesos[e] for e in pesos)
                / sum(pesos.values()))
    assert j["score"] == pytest.approx(round(esperado, 1), abs=0.05)


# ════════════════════════════════════════════════════════════════
# LO QUE NO SE PUEDE PUNTUAR, NO SE PUNTÚA
# ════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("puesto", ["DF", "GK"])
def test_defensas_y_porteros_no_se_puntuan(delanteros, puesto):
    """ESTA es la prueba que impide que vuelva el 40,0 para todos."""
    with pytest.raises(PuestoSinDatos) as e:
        puntuar(delanteros, puesto)
    assert "Understat" in str(e.value)
    assert e.value.puesto == puesto


def test_el_motivo_explica_por_que_y_no_dice_proximamente():
    """No es un «todavía no»: es que esos datos no existen en la
    fuente. La diferencia importa para quien lo está leyendo."""
    for puesto, motivo in M.PUESTOS_SIN_DATOS.items():
        assert "Understat" in motivo
        assert "próximamente" not in motivo.lower()
        assert len(motivo) > 80, puesto


def test_si_falta_una_metrica_revienta_en_vez_de_poner_cero(delanteros):
    """El fallo original en una línea: `p.get(clave, 0) or 0`."""
    sin_xa = [{k: v for k, v in j.items() if k != "xA"} for j in delanteros]
    with pytest.raises(ValueError) as e:
        puntuar(sin_xa, "FW")
    assert "xA" in str(e.value)


def test_faltan_metricas_mira_los_datos_y_no_una_lista(delanteros):
    assert faltan_metricas(delanteros, "FW") == []
    sin = [{k: v for k, v in j.items() if k not in ("xA", "xGChain")}
           for j in delanteros]
    assert set(faltan_metricas(sin, "FW")) == {"xA", "xGChain"}


# ════════════════════════════════════════════════════════════════
# TODAS LAS MÉTRICAS TIENEN QUE EXISTIR DE VERDAD
# ════════════════════════════════════════════════════════════════

def test_ninguna_metrica_pide_algo_que_understat_no_da():
    """La raíz del problema: la tabla pedía entradas, intercepciones y
    paradas. Esta prueba compara contra lo que el scraper devuelve de
    verdad, así que si alguien vuelve a meter una métrica inventada,
    salta aquí y no en producción."""
    for puesto, ficha in M.METRICAS_POR_PUESTO.items():
        for clave, etiqueta, peso, _ in ficha["metricas"]:
            assert clave in CAMPOS, f"{puesto}: «{clave}» no la da Understat"
            assert 0 < peso <= 1, f"{puesto}/{clave}: peso {peso}"


def test_los_pesos_de_cada_puesto_suman_uno():
    for puesto, ficha in M.METRICAS_POR_PUESTO.items():
        suma = sum(m[2] for m in ficha["metricas"])
        assert suma == pytest.approx(1.0, abs=0.001), (puesto, suma)


def test_las_claves_del_scraper_son_las_que_creo():
    """Si Understat cambia y el scraper deja de devolver un campo, esto
    salta antes de que nadie vea una puntuación rara."""
    import inspect

    from backend.scrapers import understat
    fuente = inspect.getsource(understat)
    for clave in CAMPOS:
        assert f'"{clave}"' in fuente, f"el scraper ya no devuelve {clave}"


# ════════════════════════════════════════════════════════════════
# AVISOS HONESTOS
# ════════════════════════════════════════════════════════════════

def test_con_pocos_jugadores_se_avisa():
    """Percentil 90 sobre ocho jugadores es «el primero de ocho». Si no
    se dice, el número engaña."""
    ficha = puntuar([jugador(i) for i in range(6)], "FW")
    assert ficha["avisos"]
    assert "6" in ficha["avisos"][0]


def test_con_bastantes_jugadores_no_sobra_el_aviso(delanteros):
    assert puntuar(delanteros, "FW")["avisos"] == []


def test_se_dice_que_no_hay_ajuste_por_edad(delanteros):
    """Understat no da la edad. El código viejo ponía 25 por defecto y
    le subía un 2 % a todo el mundo: un ajuste calculado sobre una edad
    inventada."""
    puntuar(delanteros, "FW")
    assert all(j["ajustado_por_edad"] is False for j in delanteros)


def test_la_ficha_dice_como_se_ha_calculado(delanteros):
    ficha = puntuar(delanteros, "FW")
    assert "percentil" in ficha["metodo"]
    assert "90 minutos" in ficha["metodo"]
    assert ficha["comparados"] == 30
    assert ficha["explica"]


# ════════════════════════════════════════════════════════════════
# EL PIPELINE ENTERO
# ════════════════════════════════════════════════════════════════

def test_el_pipeline_puntua_delanteros_y_centrocampistas():
    js = []
    for i in range(80):
        p = jugador(i, minutos=700 + i * 25, goals=i % 15, assists=i % 8,
                    npxG=0.8 + i * 0.2, xA=0.4 + i * 0.12,
                    shots=8 + i * 2, key_passes=4 + i,
                    xGChain=1.5 + i * 0.3, xGBuildup=0.6 + i * 0.18)
        p["position"] = "F M" if i % 2 else "M S"
        js.append(p)
    for puesto in ("FW", "MF"):
        r = run_scouting_pipeline(js, puesto, max_age=25, min_minutes=500)
        assert r["players"], puesto
        scores = [p["score"] for p in r["players"]]
        assert len(set(scores)) > 10, puesto
        assert scores == sorted(scores, reverse=True), "no viene ordenado"


@pytest.mark.parametrize("puesto", ["DF", "GK"])
def test_el_pipeline_tambien_se_niega(delanteros, puesto):
    for j in delanteros:
        j["position"] = "D" if puesto == "DF" else "GK"
    with pytest.raises(PuestoSinDatos):
        run_scouting_pipeline(delanteros, puesto, max_age=25, min_minutes=0)


def test_el_agrupamiento_usa_los_percentiles(delanteros):
    """Con totales, el agrupamiento separaba por minutos jugados: el
    que más juega tiene los números más grandes en todo. Eso agrupa por
    titularidad, no por tipo de jugador."""
    r = run_scouting_pipeline(delanteros, "FW", max_age=25, min_minutes=0)
    ps = r["players"]
    minutos = [p["time"] for p in ps if p.get("cluster") == 0]
    assert len({p.get("cluster") for p in ps}) > 1
    # el mejor grupo no puede ser simplemente "los que más minutos tienen"
    if minutos:
        assert min(minutos) < max(p["time"] for p in ps)


# ════════════════════════════════════════════════════════════════
# EL RECORTE NO PUEDE COMERSE UN PUESTO ENTERO
# ════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_el_recorte_deja_jugadores_de_todos_los_puestos(monkeypatch):
    """Salió probando La Liga con datos reales: «200 con nota, 0 sin
    nota».

    La ruta ordenaba por nota —con los sin nota al final— y luego
    cortaba por `limit`. Como en La Liga hay más de 200 jugadores con
    nota, los defensas y porteros se caían ENTEROS del corte: en la
    pantalla de Cartas no aparecía ni un central.

    No se vio en la Premier porque allí había menos de 200 con nota y
    los sin nota entraban por los pelos. Un fallo que depende de
    cuántos jugadores tenga la liga.
    """
    from fastapi.testclient import TestClient
    import main

    # 400 jugadores: 150 delanteros, 150 centros, 80 defensas, 20 porteros.
    # Con el bug, los 200 primeros serían todos delanteros y centros.
    falsos = []
    for i in range(400):
        pos = ("F" if i < 150 else "M" if i < 300 else "D" if i < 380 else "GK")
        falsos.append(jugador(i, minutos=500 + i, goals=i % 20,
                              assists=i % 11, npxG=0.5 + i * 0.05,
                              xA=0.3 + i * 0.03, shots=5 + i,
                              key_passes=3 + i, xGChain=1.0 + i * 0.07,
                              xGBuildup=0.4 + i * 0.04))
        falsos[-1]["position"] = pos

    async def falsa(codigo, temporada=2024):
        return falsos

    monkeypatch.setattr(main, "get_league_players", falsa)
    cli = TestClient(main.app)
    r = cli.get("/api/players/PD?limit=200&min_minutes=0")
    assert r.status_code == 200, r.text
    d = r.json()

    reparto = d["reparto_por_puesto"]
    assert set(reparto) == {"FW", "MF", "DF", "GK"}, reparto
    assert reparto["DF"] > 0 and reparto["GK"] > 0, (
        f"el recorte se ha comido un puesto entero: {reparto}")
    assert len(d["players"]) <= 200

    # y los que no se pueden puntuar siguen saliendo sin nota, no con cero
    sin = [p for p in d["players"] if p["score"] is None]
    assert sin, "no sale ningún jugador sin nota"
    assert set(d["puestos_sin_nota"]) == {"DF", "GK"}


@pytest.mark.asyncio
async def test_dentro_de_cada_puesto_salen_los_mejores(monkeypatch):
    """Repartir por puesto no puede significar coger a cualquiera: de
    cada puesto tienen que salir los de más nota."""
    from fastapi.testclient import TestClient
    import main

    falsos = []
    for i in range(120):
        p = jugador(i, minutos=600 + i * 10, goals=i % 18,
                    npxG=0.3 + i * 0.08, xA=0.2 + i * 0.05,
                    assists=i % 9, shots=4 + i, key_passes=2 + i,
                    xGChain=0.8 + i * 0.1, xGBuildup=0.3 + i * 0.06)
        p["position"] = "F" if i % 2 else "M"
        falsos.append(p)

    async def falsa(codigo, temporada=2024):
        return falsos

    monkeypatch.setattr(main, "get_league_players", falsa)
    cli = TestClient(main.app)
    todos = cli.get("/api/players/PD?limit=200&min_minutes=0").json()["players"]
    pocos = cli.get("/api/players/PD?limit=20&min_minutes=0").json()["players"]

    mejores = {p["name"] for p in todos[:10]}
    salen = {p["name"] for p in pocos}
    assert len(mejores & salen) >= 8, (
        "al recortar se están perdiendo los mejores")
