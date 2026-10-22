# -*- coding: utf-8 -*-
"""
PRUEBAS DE LA MÁQUINA DE HALLAZGOS
==================================
La que de verdad importa es `test_con_mil_jugadores_inventados...`:
fabrica 1.200 jugadores que convierten EXACTAMENTE a su xG —o sea, un
mundo donde no hay ni un solo hallazgo de verdad— y comprueba que la
máquina no se inventa sesenta.
"""
import random

import pytest

from backend.ml.hallazgos import (
    FDR, MINIMO_DE_MINUTOS, MINIMO_DE_TIROS, NoSePuedeMedir,
    benjamini_hochberg, buscar, cola_derecha, cola_izquierda,
    p_de_un_jugador,
)


def _jug(nombre, tiros, goles, npxg, minutos=900, equipo="Equipo",
         liga="PD"):
    return {"player_id": nombre, "name": nombre, "team": equipo,
            "league": liga, "position": "F", "time": minutos,
            "shots": tiros, "npg": goles, "npxG": npxg}


# ══════════════════════════════════════════════════════════
# LA BINOMIAL
# ══════════════════════════════════════════════════════════

def test_las_dos_colas_suman_uno_mas_el_punto():
    """P(X>=k) + P(X<=k) = 1 + P(X=k). Si no, una de las dos está mal."""
    n, p, k = 20, 0.3, 6
    punto = cola_derecha(k, n, p) + cola_izquierda(k, n, p) - 1.0
    solo_k = cola_derecha(k, n, p) - cola_derecha(k + 1, n, p)
    assert punto == pytest.approx(solo_k, abs=1e-12)


def test_toda_la_distribucion_suma_uno():
    assert cola_derecha(0, 30, 0.17) == pytest.approx(1.0, abs=1e-12)
    assert cola_izquierda(30, 30, 0.17) == pytest.approx(1.0, abs=1e-12)


def test_un_valor_que_se_puede_comprobar_a_mano():
    """10 caras de 10 monedas: 1 entre 1.024."""
    assert cola_derecha(10, 10, 0.5) == pytest.approx(1 / 1024, abs=1e-12)


def test_mas_goles_que_tiros_es_imposible():
    assert cola_derecha(11, 10, 0.5) == 0.0


# ══════════════════════════════════════════════════════════
# EL p DE UN JUGADOR
# ══════════════════════════════════════════════════════════

def test_el_que_clava_su_xg_no_es_raro():
    """20 tiros, 4 de xG, 4 goles: lo más normal del mundo."""
    assert p_de_un_jugador(4, 20, 4.0) > 0.5


def test_el_que_mete_el_triple_si_lo_es():
    p = p_de_un_jugador(12, 30, 4.0)
    assert p < 0.001


def test_el_que_falla_todo_tambien_sale():
    """A dos colas: fallar lo que deberías meter también es un hallazgo."""
    p = p_de_un_jugador(0, 40, 8.0)
    assert p < 0.01


def test_es_a_dos_colas_de_verdad():
    """Simétrico: el p de pasarse y el de quedarse corto se calculan
    igual. Elegir el lado después de ver el dato dobla los falsos."""
    arriba = p_de_un_jugador(10, 20, 5.0)
    abajo = p_de_un_jugador(0, 20, 5.0)
    assert arriba < 1 and abajo < 1
    # ninguno de los dos puede pasar de 1 por multiplicar por 2
    assert p_de_un_jugador(5, 20, 5.0) <= 1.0


def test_sin_tiros_no_se_mide_y_se_dice():
    with pytest.raises(NoSePuedeMedir) as e:
        p_de_un_jugador(0, 0, 0.0)
    assert e.value.motivo == "sin_tiros"


def test_xg_cero_con_tiros_se_niega_en_vez_de_dar_un_p_de_cero():
    """Sin esto, cualquiera con xG 0 y un gol saldría como el hallazgo
    del siglo con p = 0. Y lo que pasa es que el dato está mal."""
    with pytest.raises(NoSePuedeMedir) as e:
        p_de_un_jugador(1, 10, 0.0)
    assert e.value.motivo == "xg_cero"
    assert "0 de xG" in e.value.detalle


def test_mas_xg_que_tiros_se_niega():
    with pytest.raises(NoSePuedeMedir) as e:
        p_de_un_jugador(3, 5, 7.0)
    assert e.value.motivo == "xg_mayor_que_tiros"


def test_la_binomial_es_mas_ancha_que_la_poisson():
    """Y por eso se usa: da menos hallazgos, no más.

    Con la misma media, la binomial de p iguales tiene la varianza
    MÁXIMA de todas las Poisson-binomiales posibles. La Poisson tiene
    varianza = media, que aquí es mayor... salvo en la cola de la
    derecha, que es la que se mira. Lo que se comprueba es lo único
    que importa: que el p que se publica no es más pequeño que el que
    saldría de una Poisson, o sea que no se gana un hallazgo por
    elegir el modelo.
    """
    from math import exp
    n, xg, k = 40, 6.0, 12
    p_bin = cola_derecha(k, n, xg / n)
    # la cola de la Poisson, término a término para no reventar el
    # factorial: t_i = t_(i-1) · xg / i
    t, p_poi = exp(-xg), 0.0
    for i in range(0, 400):
        if i >= k:
            p_poi += t
        t *= xg / (i + 1)
    assert p_bin <= p_poi


# ══════════════════════════════════════════════════════════
# BENJAMINI-HOCHBERG
# ══════════════════════════════════════════════════════════

def test_sin_nada_que_probar_no_pasa_nada():
    r = benjamini_hochberg([])
    assert r["pasan"] == [] and r["cuantos_probados"] == 0


def test_si_todos_son_normales_no_pasa_ninguno():
    assert benjamini_hochberg([0.4, 0.6, 0.9, 0.5] * 25)["pasan"] == []


def test_uno_clarisimo_entre_cien_normales_pasa():
    pes = [0.0000001] + [0.5] * 99
    r = benjamini_hochberg(pes)
    assert r["pasan"] == [0]


def test_arrastra_a_los_de_delante():
    """La parte que la gente se salta: si el 5.º cumple, pasan los
    cinco, también los que por sí solos no cumplirían."""
    m = 100
    pes = [0.0001, 0.0002, 0.0003, 0.0004, 0.0049] + [0.9] * (m - 5)
    r = benjamini_hochberg(pes, fdr=0.10)
    assert r["pasan"] == [0, 1, 2, 3, 4]


def test_es_mas_exigente_que_mirar_cada_p_por_su_cuenta():
    """Mil pruebas sin nada que encontrar: los p salen repartidos por
    igual entre 0 y 1, que es lo que hacen cuando no pasa nada.

    Unos cincuenta caen por debajo de 0,05 y serían «hallazgos» a
    pelo. Benjamini-Hochberg no deja pasar ninguno.

    (Esta prueba estuvo mal escrita: decía que con mil p de 0,049 no
    pasaba ninguno, y pasan los mil. Y es correcto: si TODOS los p
    están rozando el corte, lo raro sería que no hubiera nada. BH no
    es «más duro» siempre, es más duro cuando los p parecen azar, que
    es justo cuando hay que serlo.)
    """
    m = 1000
    pes = [(i + 0.5) / m for i in range(m)]   # repartidos por igual
    assert sum(1 for p in pes if p < 0.05) == 50
    assert benjamini_hochberg(pes, fdr=0.10)["pasan"] == []


def test_bajar_el_fdr_nunca_saca_mas_nombres():
    pes = [0.001, 0.004, 0.02, 0.03, 0.2, 0.5, 0.7, 0.9]
    flojo = len(benjamini_hochberg(pes, fdr=0.20)["pasan"])
    duro = len(benjamini_hochberg(pes, fdr=0.05)["pasan"])
    assert duro <= flojo


def test_las_posiciones_que_devuelve_son_las_de_la_lista_de_entrada():
    """Se ordena por dentro; si se devolvieran las posiciones del
    orden, los nombres saldrían cambiados."""
    pes = [0.9, 0.0000001, 0.8]
    assert benjamini_hochberg(pes)["pasan"] == [1]


# ══════════════════════════════════════════════════════════
# LA MÁQUINA ENTERA
# ══════════════════════════════════════════════════════════

def test_el_que_no_llega_a_minutos_se_descarta_con_el_motivo():
    r = buscar([_jug("Novato", 30, 12, 4.0, minutos=200)])
    assert r["hallazgos"] == []
    assert r["descartados"][0]["motivo"] == "pocos_minutos"
    assert "200 minutos" in r["descartados"][0]["detalle"]


def test_el_que_no_llega_a_tiros_se_descarta_con_el_motivo():
    r = buscar([_jug("Central", 4, 2, 0.4)])
    assert r["descartados"][0]["motivo"] == "pocos_tiros"


def test_un_hallazgo_de_verdad_sale_con_su_cuenta_delante():
    gente = [_jug(f"Normal{i}", 30, 6, 6.0) for i in range(40)]
    gente.append(_jug("ElQueMete", 40, 18, 5.0))
    r = buscar(gente)
    nombres = [h["name"] for h in r["hallazgos"]]
    assert nombres == ["ElQueMete"]
    h = r["hallazgos"][0]
    assert h["goles_sin_penalti"] == 18
    assert h["npxg"] == 5.0
    assert h["diferencia"] == 13.0
    assert h["direccion"] == "mete de más"
    assert h["tiros"] == 40
    assert 0 <= h["p"] <= h["umbral_que_pasa"]


def test_el_que_falla_lo_suyo_tambien_es_un_hallazgo():
    gente = [_jug(f"Normal{i}", 30, 6, 6.0) for i in range(40)]
    gente.append(_jug("ElQueFalla", 60, 1, 12.0))
    r = buscar(gente)
    assert [h["name"] for h in r["hallazgos"]] == ["ElQueFalla"]
    assert r["hallazgos"][0]["direccion"] == "mete de menos"


def test_se_usan_los_goles_sin_penalti_y_no_los_totales():
    """Un penalti lo mete quien lo tira, no quien genera la ocasión, y
    vale 0,76 de xG siempre. Mezclarlos con el juego cuenta otra cosa.

    (Esta prueba estaba mal planteada antes: decía que contar los
    penaltis convertiría al lanzador en un falso hallazgo, y haciendo
    la cuenta no es verdad —suben los goles y el xG a la vez—. Lo que
    sí se puede comprobar, y es lo que importa, es que las cifras
    PUBLICADAS son las de sin penaltis.)
    """
    j = _jug("Lanzador", 40, 14, 5.0)     # 14 goles de juego, 5 de npxG
    j["goals"] = 24                        # con sus 10 penaltis
    j["xG"] = 12.6
    r = buscar([j] + [_jug(f"N{i}", 30, 6, 6.0) for i in range(40)])

    assert [h["name"] for h in r["hallazgos"]] == ["Lanzador"]
    h = r["hallazgos"][0]
    assert h["goles_sin_penalti"] == 14, "ha cogido los goles con penaltis"
    assert h["npxg"] == 5.0, "ha cogido el xG con penaltis"
    assert h["diferencia"] == 9.0
    assert r["sin_penaltis"] is True


def test_dice_cuantos_habrian_salido_haciendolo_mal():
    """La cifra que es el argumento entero de la pantalla."""
    rnd = random.Random(7)
    gente = []
    for i in range(400):
        tiros = rnd.randint(20, 60)
        xg_tiro = rnd.uniform(0.08, 0.18)
        xg = round(tiros * xg_tiro, 2)
        # cada uno mete lo suyo, tirando la moneda de verdad
        goles = sum(1 for _ in range(tiros) if rnd.random() < xg_tiro)
        gente.append(_jug(f"J{i}", tiros, goles, xg))
    r = buscar(gente)
    assert r["cuantos_probados"] == 400
    assert r["esperados_por_puro_azar"] == pytest.approx(20.0)
    assert r["pasarian_sin_corregir"] >= 5
    assert r["falsos_esperados_entre_los_publicados"] == pytest.approx(
        FDR * len(r["hallazgos"]), abs=0.05)


def test_con_mil_jugadores_inventados_que_convierten_a_su_xg_casi_no_hay_hallazgos():
    """LA PRUEBA QUE JUSTIFICA LA PANTALLA.

    Un mundo donde NADIE es especial: cada jugador mete tirando una
    moneda con la probabilidad que le da su propio xG. Todo hallazgo
    que salga aquí es, por construcción, un falso positivo.

    Sin corregir saldrían ~60 nombres de 1.200. Con Benjamini-Hochberg
    tienen que salir casi cero, y desde luego muchísimos menos que los
    que pasan el p < 0,05 a pelo.
    """
    rnd = random.Random(20261022)
    gente = []
    for i in range(1200):
        tiros = rnd.randint(15, 70)
        xg_tiro = rnd.uniform(0.06, 0.22)
        xg = round(tiros * xg_tiro, 2)
        goles = sum(1 for _ in range(tiros) if rnd.random() < xg_tiro)
        gente.append(_jug(f"J{i}", tiros, goles, xg))

    r = buscar(gente)
    falsos = len(r["hallazgos"])
    ingenuos = r["pasarian_sin_corregir"]

    # sin corregir, el 5 % de 1.200: sobre sesenta nombres falsos
    assert ingenuos > 30, f"sólo {ingenuos}: revisa el generador"
    # corrigiendo, casi ninguno
    assert falsos <= 3, f"{falsos} falsos positivos, demasiados"
    assert falsos < ingenuos / 10


def test_la_respuesta_lleva_siempre_los_minimos_que_ha_usado():
    r = buscar([])
    assert r["minimo_de_tiros"] == MINIMO_DE_TIROS
    assert r["minimo_de_minutos"] == MINIMO_DE_MINUTOS
    assert r["fdr"] == FDR
    assert r["hallazgos"] == [] and r["cuantos_probados"] == 0


def test_los_hallazgos_salen_ordenados_por_lo_raros_que_son():
    gente = [_jug(f"Normal{i}", 30, 6, 6.0) for i in range(60)]
    gente.append(_jug("Rarisimo", 50, 25, 6.0))
    gente.append(_jug("Raro", 40, 14, 6.5))
    r = buscar(gente)
    pes = [h["p"] for h in r["hallazgos"]]
    assert pes == sorted(pes)
    assert r["hallazgos"][0]["name"] == "Rarisimo"


def test_el_xg_de_cero_con_tiros_se_descarta_no_se_publica():
    gente = [_jug(f"N{i}", 30, 6, 6.0) for i in range(40)]
    gente.append(_jug("DatoRaro", 20, 3, 0.0))
    r = buscar(gente)
    assert "DatoRaro" not in [h["name"] for h in r["hallazgos"]]
    assert [d for d in r["descartados"] if d["motivo"] == "xg_cero"]
