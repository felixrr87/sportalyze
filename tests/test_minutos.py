# -*- coding: utf-8 -*-
"""
PRUEBAS DE QUIÉN ESTABA EN EL CAMPO EN CADA MINUTO
==================================================
    python3 -m pytest tests/test_minutos.py -v

La alineación del Barça del Betis–Barcelona del 17 de octubre de 2026,
copiada tal cual de Understat. Sirve de prueba y de demostración: los
minutos suman 990 y cada cambio cuadra con su complemento.

Lo que de verdad se comprueba aquí es que, cuando las cuentas NO
cuadran —una expulsión—, el código se niegue en vez de adivinar. Un
tramo mal reconstruido reparte el xG del rival a quien no estaba en el
campo, y eso no se nota mirando: sale un número perfectamente creíble.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.ml.minutos import (
    MINUTOS_PARTIDO, NoSePuedeReconstruir, reparto_de_un_partido,
    tramos, xg_en_el_tramo,
)


def j(nombre, minutos, suplente=False, puesto="DC"):
    return {"nombre": nombre, "minutos": minutos, "suplente": suplente,
            "puesto": puesto, "player_id": nombre}


# El Barça de verdad de aquel partido.
BARCA = [
    j("Joan García", 90, puesto="GK"), j("Jules Koundé", 90),
    j("Pau Cubarsí", 90), j("Gerard Martín", 53), j("Xavi Espart", 90),
    j("Rodri", 90), j("Pedri", 90), j("Lamine Yamal", 77),
    j("Fermín López", 69), j("Karim Adeyemi", 69), j("Gabriel Jesus", 86),
    j("Anthony Gordon", 21, True), j("Dani Olmo", 21, True),
    j("Eric García", 37, True), j("Raphinha", 13, True), j("Gavi", 4, True),
    j("Marc Bernal", 0, True), j("Szczęsny", 0, True),
]


def test_los_minutos_del_partido_real_suman_990():
    assert sum(x["minutos"] for x in BARCA) == 11 * MINUTOS_PARTIDO


def test_cada_titular_empieza_en_el_cero():
    for t in tramos(BARCA):
        if not t["suplente"]:
            assert t["desde"] == 0, t["nombre"]


def test_cada_suplente_acaba_en_el_noventa():
    for t in tramos(BARCA):
        if t["suplente"]:
            assert t["hasta"] == 90, t["nombre"]


def test_los_cambios_del_partido_real_cuadran():
    """Gerard Martín sale en el 53 y Eric García entra con 37 minutos."""
    d = {t["nombre"]: t for t in tramos(BARCA)}
    assert d["Gerard Martín"]["hasta"] == 53
    assert d["Eric García"]["desde"] == 53
    assert d["Lamine Yamal"]["hasta"] == 77
    assert d["Raphinha"]["desde"] == 77
    assert d["Gabriel Jesus"]["hasta"] == 86
    assert d["Gavi"]["desde"] == 86


def test_en_cada_minuto_hay_once_en_el_campo():
    """La comprobación que de verdad valida la reconstrucción.

    Que los totales sumen no basta: podrían sumar con los tramos
    colocados mal. Que haya once en cada minuto, sí.
    """
    ts = tramos(BARCA)
    for m in range(90):
        assert sum(1 for t in ts if t["desde"] <= m < t["hasta"]) == 11, m


def test_los_que_no_jugaron_no_salen():
    nombres = [t["nombre"] for t in tramos(BARCA)]
    assert "Marc Bernal" not in nombres
    assert "Szczęsny" not in nombres
    assert len(nombres) == 16


# ══════════════════════════════════════════════════════════════════
# CUANDO NO SE PUEDE, NO SE INVENTA
# ══════════════════════════════════════════════════════════════════

def test_una_expulsion_hace_que_se_niegue():
    """El caso que rompe la aritmética.

    El expulsado se va y nadie entra en su sitio: los minutos ya no
    suman 990 y el complemento de ese titular no existe. Si se
    reconstruyera igual, el xG del rival de los últimos veinte minutos
    se le repartiría a once jugadores de los que uno no estaba.
    """
    con_roja = [x for x in BARCA if x["nombre"] != "Eric García"]
    con_roja = [dict(x, minutos=60) if x["nombre"] == "Gerard Martín" else x
                for x in con_roja]
    with pytest.raises(NoSePuedeReconstruir) as e:
        tramos(con_roja)
    assert e.value.motivo in ("minutos_no_cuadran", "once_imposible")


def test_si_faltan_titulares_se_niega():
    with pytest.raises(NoSePuedeReconstruir) as e:
        tramos([x for x in BARCA if x["nombre"] != "Pedri"])
    assert e.value.motivo in ("titulares_raros", "minutos_no_cuadran")


def test_sin_alineacion_se_niega():
    with pytest.raises(NoSePuedeReconstruir) as e:
        tramos([])
    assert e.value.motivo == "sin_alineacion"


def test_doce_titulares_se_niega():
    with pytest.raises(NoSePuedeReconstruir):
        tramos(BARCA + [j("Un Doceavo", 90)])


def test_un_cambio_mal_apuntado_se_caza_por_el_once():
    """Totales que suman pero tramos imposibles.

    Si un titular sale en el 53 y el suplente que entra trae 30
    minutos en vez de 37, los totales bajan 7 y el hueco se nota en
    el recuento por minuto.
    """
    malo = [dict(x, minutos=30) if x["nombre"] == "Eric García" else x
            for x in BARCA]
    with pytest.raises(NoSePuedeReconstruir):
        tramos(malo)


# ── el xG en cada tramo ───────────────────────────────────────────

TIROS_RIVAL = [
    {"minuto": 26, "xg": 0.553}, {"minuto": 38, "xg": 0.363},
    {"minuto": 49, "xg": 0.111}, {"minuto": 52, "xg": 0.296},
    {"minuto": 74, "xg": 0.014}, {"minuto": 75, "xg": 0.016},
]
TIROS_PROPIOS = [
    {"minuto": 13, "xg": 0.743}, {"minuto": 46, "xg": 0.451},
    {"minuto": 66, "xg": 0.491}, {"minuto": 80, "xg": 0.15},
]


def test_el_xg_de_un_tramo_son_los_tiros_de_ese_tramo():
    assert xg_en_el_tramo(TIROS_RIVAL, 0, 90) == round(sum(
        t["xg"] for t in TIROS_RIVAL), 4)
    assert xg_en_el_tramo(TIROS_RIVAL, 0, 53) == round(
        0.553 + 0.363 + 0.111 + 0.296, 4)
    assert xg_en_el_tramo(TIROS_RIVAL, 53, 90) == round(0.014 + 0.016, 4)


def test_el_minuto_de_salida_no_cuenta_para_el_que_sale():
    """Un tiro en el minuto 53 es del que entra, no del que sale.

    El tramo va de `desde` incluido a `hasta` excluido. Si contara
    para los dos, el xG total repartido no cuadraría con el del
    partido.
    """
    tiro = [{"minuto": 53, "xg": 0.5}]
    assert xg_en_el_tramo(tiro, 0, 53) == 0.0
    assert xg_en_el_tramo(tiro, 53, 90) == 0.5


def test_lo_que_encaja_dentro_mas_lo_de_fuera_es_el_total():
    """Nada se pierde y nada se cuenta dos veces."""
    r = reparto_de_un_partido(BARCA, TIROS_PROPIOS, TIROS_RIVAL)
    total_c = round(sum(t["xg"] for t in TIROS_RIVAL), 4)
    total_f = round(sum(t["xg"] for t in TIROS_PROPIOS), 4)
    for pid, d in r.items():
        assert abs(d["xg_contra_dentro"] + d["xg_contra_fuera"] - total_c) < 1e-6, pid
        assert abs(d["xg_favor_dentro"] + d["xg_favor_fuera"] - total_f) < 1e-6, pid


def test_los_minutos_dentro_y_fuera_suman_noventa():
    for pid, d in reparto_de_un_partido(BARCA, TIROS_PROPIOS, TIROS_RIVAL).items():
        assert d["minutos_dentro"] + d["minutos_fuera"] == 90, pid


def test_el_que_juega_los_noventa_no_tiene_nada_fuera():
    r = reparto_de_un_partido(BARCA, TIROS_PROPIOS, TIROS_RIVAL)
    pedri = r["Pedri"]
    assert pedri["minutos_fuera"] == 0
    assert pedri["xg_contra_fuera"] == 0
    assert pedri["xg_contra_dentro"] == round(sum(t["xg"] for t in TIROS_RIVAL), 4)


def test_el_que_entra_tarde_solo_carga_con_lo_de_su_rato():
    """Gavi entró en el 86: sólo le tocan los tiros del 86 al 90."""
    r = reparto_de_un_partido(BARCA, TIROS_PROPIOS, TIROS_RIVAL)
    gavi = r["Gavi"]
    assert gavi["minutos_dentro"] == 4
    assert gavi["xg_contra_dentro"] == 0.0     # el rival no tiró en esos 4
    assert gavi["xg_contra_fuera"] == round(sum(t["xg"] for t in TIROS_RIVAL), 4)


# ══════════════════════════════════════════════════════════════════
# UN SUPLENTE TAMBIÉN PUEDE SER SUSTITUIDO
# ══════════════════════════════════════════════════════════════════
#
# La regla sencilla —«un suplente acaba en el 90»— se rompe cuando a
# alguien que entró le cambian después. Salió probando con el Barça:
# dos de sus nueve partidos daban doce y trece jugadores en el campo
# en el minuto 89.

def test_un_suplente_al_que_cambian_despues():
    """Entra en el 60 y le cambian en el 85: juega 25, no 30."""
    plantilla = [j(f"T{i}", 90) for i in range(10)]
    plantilla.append(j("Sale60", 60))          # titular, sale en el 60
    plantilla.append(j("Entra60", 25, True))   # entra 60, sale 85
    plantilla.append(j("Entra85", 5, True))    # entra 85, acaba
    ts = {t["nombre"]: t for t in tramos(plantilla)}
    assert ts["Sale60"]["hasta"] == 60
    assert (ts["Entra60"]["desde"], ts["Entra60"]["hasta"]) == (60, 85)
    assert (ts["Entra85"]["desde"], ts["Entra85"]["hasta"]) == (85, 90)


def test_con_cambios_encadenados_sigue_habiendo_once_en_cada_minuto():
    plantilla = [j(f"T{i}", 90) for i in range(8)]
    plantilla += [j("A", 45), j("B", 70), j("C", 60)]      # tres titulares
    plantilla += [j("SubA", 45, True), j("SubB", 20, True),
                  j("SubC", 15, True), j("SubC2", 15, True)]
    ts = tramos(plantilla)
    for m in range(90):
        assert sum(1 for t in ts if t["desde"] <= m < t["hasta"]) == 11, m


def test_cuando_de_verdad_no_cuadra_se_sigue_negando():
    """El arreglo no puede volver permisivo al comprobador."""
    plantilla = [j(f"T{i}", 90) for i in range(10)]
    plantilla.append(j("Sale60", 60))
    plantilla.append(j("Entra", 50, True))   # 60 + 50 = 110, imposible
    with pytest.raises(NoSePuedeReconstruir):
        tramos(plantilla)


def test_los_minutos_de_los_tramos_son_los_minutos_jugados():
    """Lo que dice la fuente y lo que sale del reparto, igual."""
    plantilla = [j(f"T{i}", 90) for i in range(10)]
    plantilla += [j("Sale60", 60), j("Entra60", 25, True), j("Entra85", 5, True)]
    for t in tramos(plantilla):
        assert t["hasta"] - t["desde"] == t["minutos"], t["nombre"]


# ══════════════════════════════════════════════════════════════════
# CUANDO LOS MINUTOS ADMITEN MÁS DE UNA LECTURA
# ══════════════════════════════════════════════════════════════════
#
# Un hueco a los 60 y dos suplentes de 25 y 5 minutos se pueden leer
# de dos maneras, y las dos cuadran con lo que publica Understat:
#
#   A) entra el de 25 en el 60 y le cambian en el 85; entra el de 5
#   B) entra el de 5 en el 60 y le cambian en el 65; entra el de 25
#
# No hay forma de saber cuál es. Lo que sí se puede saber es si la
# duda CAMBIA EL RESULTADO: si no hubo tiros entre el 60 y el 85, las
# dos lecturas reparten exactamente el mismo xG y da igual.

from backend.ml.minutos import soluciones

AMBIGUO = ([j(f"T{i}", 90) for i in range(10)] +
           [j("Sale60", 60), j("Corto", 5, True), j("Largo", 25, True)])


def test_un_reparto_dudoso_da_mas_de_una_solucion():
    s = soluciones(AMBIGUO)
    assert len(s) >= 2, "esas dos lecturas son las dos posibles"
    for una in s:
        for m in range(90):
            assert sum(1 for t in una if t["desde"] <= m < t["hasta"]) == 11


def test_la_primera_solucion_es_la_que_menos_cambios_encadena():
    """Que a un suplente le cambien es raro, así que va la última."""
    primera = soluciones(AMBIGUO)[0]
    d = {t["nombre"]: t for t in primera}
    assert d["Largo"]["desde"] == 60, "lo normal es que el de 25 entre antes"


def test_si_los_tiros_caen_fuera_de_la_duda_NO_se_tira_el_partido():
    """Lo importante: la ambigüedad sólo molesta si cambia la cuenta.

    Con tiros en el 20 y en el 88, las dos lecturas dan lo mismo: el
    de 25 y el de 5 están los dos en el campo en el 88 según una y
    según la otra... no, pero el xG que les toca sí coincide.
    """
    r = reparto_de_un_partido(AMBIGUO, [], [{"minuto": 20, "xg": 0.9}])
    assert r["T0"]["xg_contra_dentro"] == 0.9
    # ninguno de los dos suplentes estaba en el minuto 20
    assert r["Corto"]["xg_contra_dentro"] == 0.0
    assert r["Largo"]["xg_contra_dentro"] == 0.0


def test_si_los_tiros_caen_justo_en_la_duda_se_para():
    """Los minutos en disputa son el 60–65 y el 85–90, no el 70.

    En el 70 están los dos de acuerdo en que juega el de 25, así que
    ahí no hay problema. Donde discrepan es al principio y al final
    del tramo: un tiro en el 62 es del de 5 en una lectura y del de
    25 en la otra.
    """
    # en el 70 coinciden: no se queja
    r = reparto_de_un_partido(AMBIGUO, [], [{"minuto": 70, "xg": 0.9}])
    assert r["Largo"]["xg_contra_dentro"] == 0.9
    assert r["Corto"]["xg_contra_dentro"] == 0.0

    # en el 62 discrepan: se para
    with pytest.raises(NoSePuedeReconstruir) as e:
        reparto_de_un_partido(AMBIGUO, [], [{"minuto": 62, "xg": 0.9}])
    assert e.value.motivo == "ambiguo"


def test_sin_ambiguedad_nunca_se_queja():
    """El arreglo no puede volver quisquilloso al caso normal."""
    r = reparto_de_un_partido(BARCA, TIROS_PROPIOS, TIROS_RIVAL)
    assert len(r) == 16


# ══════════════════════════════════════════════════════════════════
# UNDERSTAT REDONDEA LOS MINUTOS
# ══════════════════════════════════════════════════════════════════
#
# El caso real del Barcelona 5-2 Rayo: los titulares salen en los
# minutos 68, 68, 81 y 81, o sea huecos de 22, 22, 9 y 9 minutos, que
# suman 62. Y los suplentes traen 1, 9, 9, 22 y 22 minutos, que suman
# 63. Sobra un minuto: el del cambio dentro de un cambio.
#
# Exigiendo cuadre exacto se perdían dos de los nueve partidos del
# Barça. Un minuto de margen por hueco los recupera.

RAYO = ([j(f"T{i}", 90) for i in range(7)] +
        [j("Sale68a", 68), j("Sale68b", 68), j("Sale81a", 81), j("Sale81b", 81)] +
        [j("S22a", 22, True), j("S22b", 22, True), j("S9a", 9, True),
         j("S9b", 9, True), j("S1", 1, True)])


def test_el_partido_real_del_rayo_se_reconstruye():
    """Antes se descartaba entero por un minuto de redondeo."""
    ts = tramos(RAYO)
    assert len(ts) == 16
    for m in range(90):
        assert sum(1 for t in ts if t["desde"] <= m < t["hasta"]) == 11, m


def test_los_que_entran_tarde_entran_donde_salio_alguien():
    d = {t["nombre"]: t for t in tramos(RAYO)}
    for n in ("S22a", "S22b"):
        assert d[n]["desde"] == 68, n
    assert {d["S9a"]["desde"], d["S9b"]["desde"], d["S1"]["desde"]} <= {81, 82}


def test_el_margen_no_se_pasa_de_generoso():
    """Un minuto, no cinco. Si se admite cualquier cosa, deja de ser
    una comprobación y pasa a ser un adorno."""
    from backend.ml.minutos import MARGEN_POR_HUECO
    assert MARGEN_POR_HUECO == 1

    # con tres minutos de desajuste ya no cuadra
    malo = ([j(f"T{i}", 90) for i in range(10)] + [j("Sale60", 60)] +
            [j("Entra", 25, True)])          # el hueco pide 30
    with pytest.raises(NoSePuedeReconstruir):
        tramos(malo)


def test_el_mensaje_de_error_lleva_los_numeros():
    """Para no tener que ir a mirar el partido a mano."""
    malo = ([j(f"T{i}", 90) for i in range(10)] + [j("Sale60", 60)] +
            [j("Entra", 20, True)])
    try:
        tramos(malo)
        assert False, "tenía que haber fallado"
    except NoSePuedeReconstruir as e:
        assert "60" in e.detalle or "30" in e.detalle, e.detalle
        assert "20" in e.detalle, e.detalle


def test_al_promediar_lecturas_los_minutos_siguen_siendo_enteros():
    """Un «288,67 minutos» en pantalla no se lo cree nadie."""
    plantilla = ([j(f"T{i}", 90) for i in range(10)] + [j("Sale60", 60)] +
                 [j("Corto", 5, True), j("Largo", 25, True)])
    r = reparto_de_un_partido(plantilla, [], [{"minuto": 62, "xg": 0.03}])
    for pid, d in r.items():
        assert isinstance(d["minutos_dentro"], int), pid
        assert isinstance(d["minutos_fuera"], int), pid
        assert d["minutos_dentro"] + d["minutos_fuera"] == 90, pid
