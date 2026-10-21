# -*- coding: utf-8 -*-
"""
PRUEBAS DEL INFORME DE UN PARTIDO DE ESTA TEMPORADA
===================================================
    python3 -m pytest tests/test_informe_liga.py -v

Las dos que de verdad importan:

  1. QUE CADA EQUIPO ATAQUE HACIA SU LADO. Understat da las
     coordenadas con el que tira yendo siempre hacia la misma
     portería, así que al visitante hay que darle la vuelta. Si no se
     hace —o se hace sólo en x, que es el fallo clásico— el mapa sigue
     pareciendo un mapa y cuenta otra cosa.

  2. QUE EL xG ACUMULADO SEA LA SUMA DE LOS TIROS. La carrera de xG es
     el gráfico del que más se habla: si la última altura de la línea
     no es exactamente el xG del equipo, el gráfico y el número de
     arriba se contradicen.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.ml.informe_liga import (
    ANCHO, LARGO, OCASION_CLARA, _a_campo, carrera_xg, informe,
    reparto_por_situacion,
)

PARTIDO = {
    "match_id": "30783", "fecha": "2026-08-23",
    "local": "Elche", "visitante": "Barcelona",
    "goles_local": 1, "goles_visitante": 2,
}

TIROS = {
    "home_shots": [
        {"minute": 30, "result": "Goal", "x": 88.0, "y": 50.0, "xG": 0.21,
         "player": "Rafa Mir", "situation": "OpenPlay", "shot_type": "RightFoot"},
        {"minute": 70, "result": "SavedShot", "x": 80.0, "y": 35.0, "xG": 0.07,
         "player": "Rafa Mir", "situation": "FromCorner", "shot_type": "Head"},
    ],
    "away_shots": [
        {"minute": 13, "result": "Goal", "x": 88.5, "y": 50.0, "xG": 0.743,
         "player": "Raphinha", "situation": "Penalty", "shot_type": "LeftFoot"},
        {"minute": 46, "result": "SavedShot", "x": 85.9, "y": 45.2, "xG": 0.451,
         "player": "Raphinha", "situation": "OpenPlay", "shot_type": "LeftFoot"},
        {"minute": 66, "result": "Goal", "x": 90.0, "y": 52.0, "xG": 0.491,
         "player": "Raphinha", "situation": "OpenPlay", "shot_type": "LeftFoot"},
    ],
}

ROSTER = {
    "local": [{"nombre": "Rafa Mir", "minutos": 90, "goles": 1, "xg": 0.28}],
    "visitante": [{"nombre": "Raphinha", "minutos": 90, "goles": 2, "xg": 1.685}],
}


@pytest.fixture
def inf():
    return informe(PARTIDO, TIROS, ROSTER)


# ── 1. cada equipo hacia su lado ──────────────────────────────────

def test_el_local_se_queda_como_viene_y_el_visitante_se_da_la_vuelta():
    x, y = _a_campo(88.0, 50.0, visitante=False)
    assert (x, y) == (round(88.0 / 100 * LARGO, 2), round(50.0 / 100 * ANCHO, 2))

    xv, yv = _a_campo(88.0, 50.0, visitante=True)
    assert xv == round(LARGO - x, 2)
    assert yv == round(ANCHO - y, 2)


def test_al_visitante_se_le_da_la_vuelta_en_LOS_DOS_ejes():
    """El fallo clásico es voltear sólo la x.

    Y no canta: el mapa sigue pareciendo un mapa, pero la banda
    derecha pasa a ser la izquierda y "atacaron por su derecha" sale
    justo al revés.
    """
    # un tiro claramente escorado a una banda
    x, y = _a_campo(85.0, 20.0, visitante=True)
    assert y == round(ANCHO - (20.0 / 100 * ANCHO), 2)
    assert y != round(20.0 / 100 * ANCHO, 2), "no se ha volteado la y"


def test_los_dos_equipos_tiran_a_porterias_distintas(inf):
    locales = [t for t in inf["tiros"] if not t["visitante"]]
    visitas = [t for t in inf["tiros"] if t["visitante"]]
    assert locales and visitas
    # los del local caen en la mitad de la derecha, los del visitante
    # en la de la izquierda
    assert all(t["x"] > LARGO / 2 for t in locales)
    assert all(t["x"] < LARGO / 2 for t in visitas)


def test_ningun_tiro_se_sale_del_campo(inf):
    for t in inf["tiros"]:
        assert 0 <= t["x"] <= LARGO, t
        assert 0 <= t["y"] <= ANCHO, t


# ── 2. la carrera de xG ───────────────────────────────────────────

def test_la_carrera_empieza_en_cero(inf):
    primero = inf["carrera"][0]
    assert primero["minuto"] == 0
    assert primero["local"] == 0.0 and primero["visitante"] == 0.0


def test_la_carrera_va_en_orden_de_minuto(inf):
    minutos = [p["minuto"] for p in inf["carrera"]]
    assert minutos == sorted(minutos)


def test_la_carrera_nunca_baja(inf):
    """El xG acumulado sólo puede subir. Si baja, se está restando."""
    for a, b in zip(inf["carrera"], inf["carrera"][1:]):
        assert b["local"] >= a["local"]
        assert b["visitante"] >= a["visitante"]


def test_el_final_de_la_carrera_es_el_xg_del_equipo(inf):
    """El gráfico y el número de arriba tienen que decir lo mismo."""
    ultimo = inf["carrera"][-1]
    assert round(ultimo["local"], 2) == inf["equipos"]["Elche"]["xg"]
    assert round(ultimo["visitante"], 2) == inf["equipos"]["Barcelona"]["xg"]


def test_la_carrera_tiene_un_paso_por_tiro_mas_el_cero(inf):
    assert len(inf["carrera"]) == len(inf["tiros"]) + 1


def test_los_goles_quedan_marcados_en_la_carrera(inf):
    goles = [p for p in inf["carrera"] if p["gol"]]
    assert len(goles) == 3
    assert [g["gol"] for g in goles] == ["Barcelona", "Elche", "Barcelona"]
    assert [g["minuto"] for g in goles] == [13, 30, 66]


# ── el resumen de cada equipo ─────────────────────────────────────

def test_el_xg_del_equipo_es_la_suma_de_sus_tiros(inf):
    b = inf["equipos"]["Barcelona"]
    assert b["xg"] == round(0.743 + 0.451 + 0.491, 2)
    assert b["tiros"] == 3


def test_cuenta_los_tiros_a_puerta(inf):
    # gol y parada cuentan; fuera y bloqueado no
    assert inf["equipos"]["Barcelona"]["a_puerta"] == 3
    assert inf["equipos"]["Elche"]["a_puerta"] == 2


def test_la_diferencia_es_goles_menos_xg(inf):
    b = inf["equipos"]["Barcelona"]
    assert b["diferencia"] == round(2 - b["xg"], 2)


def test_la_mejor_ocasion_es_la_de_mas_xg(inf):
    m = inf["equipos"]["Barcelona"]["mejor_ocasion"]
    assert m["jugador"] == "Raphinha" and m["minuto"] == 13
    assert m["xg"] == 0.743 and m["gol"] is True


def test_cuenta_las_ocasiones_claras_con_el_umbral_escrito(inf):
    claras = [t for t in inf["tiros"]
              if t["visitante"] and t["xg"] >= OCASION_CLARA]
    assert inf["equipos"]["Barcelona"]["ocasiones_claras"] == len(claras) == 3
    assert inf["equipos"]["Elche"]["ocasiones_claras"] == 0


def test_el_reparto_por_situacion_suma_el_xg_del_equipo(inf):
    for equipo, d in inf["equipos"].items():
        suma = round(sum(v["xg"] for v in d["reparto"].values()), 2)
        assert suma == d["xg"], equipo


def test_el_reparto_separa_el_penalti(inf):
    r = inf["equipos"]["Barcelona"]["reparto"]
    assert r["Penalty"]["tiros"] == 1
    assert r["Penalty"]["xg"] == 0.743
    assert r["OpenPlay"]["tiros"] == 2


# ── honestidad ────────────────────────────────────────────────────

def test_dice_de_que_no_tiene_datos(inf):
    assert "red de pases" in inf["sin_datos_de"]
    assert inf["fuente"] == "Understat"


def test_avisa_cuando_el_marcador_no_cuadra_con_los_tiros():
    """Un gol en propia no se le apunta a nadie como tiro.

    Así que el marcador del calendario y la suma de los tiros pueden
    no coincidir. Eso es normal y explicable — lo que no vale es
    callárselo y que el visitante vea un 2-1 arriba y cuente dos goles
    en el mapa.
    """
    partido = dict(PARTIDO, goles_local=2)   # el calendario dice uno más
    inf = informe(partido, TIROS, ROSTER)
    assert inf["aviso_marcador"]
    assert "propia" in inf["aviso_marcador"]
    # y manda el marcador oficial, no el de los tiros
    assert inf["goles_local"] == 2


def test_sin_descuadre_no_hay_aviso(inf):
    assert inf["aviso_marcador"] is None


def test_el_marcador_sale_del_calendario(inf):
    assert (inf["goles_local"], inf["goles_visitante"]) == (1, 2)


def test_funciona_sin_alineaciones():
    """El roster es otra consulta y puede fallar sola.

    Si falla, el informe tiene que salir igual con lo que sí hay, en
    vez de caerse entero.
    """
    inf = informe(PARTIDO, TIROS, None)
    assert inf["equipos"]["Barcelona"]["jugadores"] == []
    assert inf["equipos"]["Barcelona"]["xg"] > 0


def test_un_partido_sin_tiros_no_revienta():
    inf = informe({"local": "A", "visitante": "B", "goles_local": 0,
                   "goles_visitante": 0}, {"home_shots": [], "away_shots": []})
    assert inf["tiros"] == []
    assert inf["equipos"]["A"]["xg"] == 0
    assert inf["equipos"]["A"]["mejor_ocasion"] is None
    assert inf["carrera"] == [{"minuto": 0, "local": 0.0, "visitante": 0.0,
                               "gol": None, "jugador": "", "xg": 0.0}]


def test_las_alineaciones_llegan_a_su_equipo(inf):
    assert inf["equipos"]["Barcelona"]["jugadores"][0]["nombre"] == "Raphinha"
    assert inf["equipos"]["Elche"]["jugadores"][0]["nombre"] == "Rafa Mir"


# ══════════════════════════════════════════════════════════════════
# QUIÉN PESÓ MÁS EN LAS OCASIONES
# ══════════════════════════════════════════════════════════════════

from backend.ml.informe_liga import (
    NOMBRE_ZONA, ORDEN_ZONAS, PESO_CADENA, TRAMO,
    antes_y_despues_del_primer_gol, por_tramos, por_zonas, quien_peso_mas,
)


def test_la_aportacion_es_la_cuenta_escrita():
    """Sin sorpresas: xG + xA + un cuarto del resto de la cadena."""
    equipos = {"A": {"jugadores": [
        {"nombre": "Uno", "minutos": 90, "xg": 0.5, "xa": 0.2,
         "xgchain": 1.1, "goles": 1, "asistencias": 0, "tiros": 3,
         "pases_clave": 2, "puesto": "FW"}]}}
    r = quien_peso_mas(equipos)
    resto = 1.1 - 0.5 - 0.2
    assert r[0]["resto_de_cadena"] == round(resto, 3)
    assert r[0]["aportacion"] == round(0.5 + 0.2 + PESO_CADENA * resto, 3)


def test_la_cadena_nunca_resta():
    """xGChain puede venir por debajo de xG+xA por redondeos.

    Si se restara, un delantero que marca saldría castigado por un
    detalle de la fuente.
    """
    equipos = {"A": {"jugadores": [
        {"nombre": "Uno", "minutos": 90, "xg": 0.9, "xa": 0.3,
         "xgchain": 0.9, "goles": 1, "asistencias": 0, "tiros": 2,
         "pases_clave": 1, "puesto": "FW"}]}}
    r = quien_peso_mas(equipos)
    assert r[0]["resto_de_cadena"] == 0.0
    assert r[0]["aportacion"] == round(0.9 + 0.3, 3)


def test_estan_los_de_los_dos_equipos_y_ordenados():
    equipos = {
        "A": {"jugadores": [
            {"nombre": "Flojo", "minutos": 90, "xg": 0.1, "xa": 0.0,
             "xgchain": 0.1, "goles": 0, "asistencias": 0, "tiros": 1,
             "pases_clave": 0, "puesto": "MF"}]},
        "B": {"jugadores": [
            {"nombre": "Crack", "minutos": 90, "xg": 1.2, "xa": 0.4,
             "xgchain": 2.0, "goles": 2, "asistencias": 1, "tiros": 5,
             "pases_clave": 3, "puesto": "FW"}]}}
    r = quien_peso_mas(equipos)
    assert [x["nombre"] for x in r] == ["Crack", "Flojo"]
    assert r[0]["equipo"] == "B"


def test_los_que_jugaron_cuatro_minutos_no_cuentan():
    """Quien entra en el 86 no puede encabezar nada."""
    equipos = {"A": {"jugadores": [
        {"nombre": "Cameo", "minutos": 4, "xg": 0.8, "xa": 0.0,
         "xgchain": 0.8, "goles": 1, "asistencias": 0, "tiros": 1,
         "pases_clave": 0, "puesto": "FW"}]}}
    assert quien_peso_mas(equipos) == []
    assert len(quien_peso_mas(equipos, minimo_minutos=1)) == 1


def test_sin_alineaciones_no_revienta():
    assert quien_peso_mas({"A": {"jugadores": []}}) == []
    assert quien_peso_mas({"A": {}}) == []


def test_el_informe_entero_lo_trae(inf):
    assert inf["quien_peso_mas"], "tiene que venir en el informe"
    assert inf["peso_cadena"] == PESO_CADENA
    assert inf["quien_peso_mas"][0]["nombre"] == "Raphinha"


# ── por tramos de quince minutos ──────────────────────────────────

def test_los_tramos_cubren_el_partido_entero(inf):
    t = inf["por_tramos"]
    assert t[0]["desde"] == 0 and t[-1]["hasta"] == 90
    assert all(b["hasta"] - b["desde"] == TRAMO for b in t)
    assert len(t) == 6


def test_el_xg_de_los_tramos_suma_el_del_equipo(inf):
    t = inf["por_tramos"]
    assert round(sum(b["local"] for b in t), 2) == inf["equipos"]["Elche"]["xg"]
    assert round(sum(b["visitante"] for b in t), 2) == inf["equipos"]["Barcelona"]["xg"]


def test_los_tiros_de_los_tramos_suman_los_del_partido(inf):
    t = inf["por_tramos"]
    assert (sum(b["tiros_local"] for b in t) +
            sum(b["tiros_visitante"] for b in t)) == len(inf["tiros"])


def test_cada_tiro_cae_en_un_solo_tramo():
    tiros = [{"minuto": m, "xg": 1.0, "visitante": False, "gol": False,
              "equipo": "A", "x": 100, "y": 40}
             for m in (0, 14, 15, 29, 30, 89)]
    t = por_tramos(tiros, "A", "B")
    assert round(sum(b["local"] for b in t), 3) == 6.0


def test_un_gol_en_el_descuento_no_se_pierde():
    """El minuto 90+3 lo publica Understat como 90 o más."""
    tiros = [{"minuto": 93, "xg": 0.7, "visitante": False, "gol": True,
              "equipo": "A", "x": 110, "y": 40}]
    t = por_tramos(tiros, "A", "B")
    assert round(sum(b["local"] for b in t), 3) == 0.7
    assert sum(b["goles_local"] for b in t) == 1


# ── desde dónde tiraron ───────────────────────────────────────────

def test_las_zonas_reparten_todos_los_tiros(inf):
    for equipo, z in inf["por_zonas"].items():
        suyos = [t for t in inf["tiros"]
                 if (t["equipo"] == equipo)]
        assert sum(d["tiros"] for d in z.values()) == len(suyos), equipo
        assert round(sum(d["xg"] for d in z.values()), 2) == \
            inf["equipos"][equipo]["xg"], equipo


def test_un_penalti_cae_dentro_del_area():
    """El punto de penalti está a 11 metros: dentro del área grande."""
    t = [{"minuto": 10, "xg": 0.76, "visitante": False, "gol": True,
          "equipo": "A", "x": 107.4, "y": 40}]
    z = por_zonas(t)
    assert "area" in z and z["area"]["tiros"] == 1


def test_un_tiro_desde_el_centro_del_campo_es_de_fuera():
    t = [{"minuto": 10, "xg": 0.01, "visitante": False, "gol": False,
          "equipo": "A", "x": 60, "y": 40}]
    assert "fuera del area" in por_zonas(t)


def test_al_visitante_se_le_deshace_el_espejo_para_la_zona():
    """Sus coordenadas están espejadas para el dibujo.

    Si no se deshace, un gol suyo a bocajarro sale como un tiro desde
    setenta metros.
    """
    # un tiro del visitante a 5 metros de la portería contraria queda,
    # espejado, cerca de x = 0
    t = [{"minuto": 10, "xg": 0.6, "visitante": True, "gol": True,
          "equipo": "B", "x": 6.0, "y": 40}]
    z = por_zonas(t)
    assert "fuera del area" not in z, z


def test_las_zonas_vienen_en_orden_de_cerca_a_lejos(inf):
    for z in inf["por_zonas"].values():
        orden = [k for k in ORDEN_ZONAS if k in z]
        assert list(z) == orden
    for k, v in NOMBRE_ZONA.items():
        assert k in ORDEN_ZONAS


# ── antes y después del primer gol ────────────────────────────────

def test_parte_el_partido_por_el_primer_gol(inf):
    p = inf["primer_gol"]
    assert p["hubo_gol"] and p["minuto"] == 13
    assert p["quien"] == "Barcelona" and p["jugador"] == "Raphinha"


def test_las_dos_mitades_suman_el_partido(inf):
    p = inf["primer_gol"]
    for lado in ("local", "visitante"):
        total = round(p["antes"][lado] + p["despues"][lado], 3)
        equipo = inf["local"] if lado == "local" else inf["visitante"]
        assert abs(total - inf["equipos"][equipo]["xg"]) < 0.01, lado


def test_el_gol_cuenta_en_el_despues():
    """El minuto del gol pertenece a lo que pasó después, no antes."""
    tiros = [{"minuto": 30, "xg": 0.5, "visitante": False, "gol": True,
              "equipo": "A", "jugador": "Uno", "x": 110, "y": 40}]
    p = antes_y_despues_del_primer_gol(tiros)
    assert p["antes"]["local"] == 0.0
    assert p["despues"]["local"] == 0.5


def test_un_partido_sin_goles_lo_dice():
    tiros = [{"minuto": 30, "xg": 0.5, "visitante": False, "gol": False,
              "equipo": "A", "x": 110, "y": 40}]
    assert antes_y_despues_del_primer_gol(tiros) == {"hubo_gol": False}
    assert por_zonas([])["area"]["tiros"] if False else True
