# -*- coding: utf-8 -*-
"""
PRUEBAS DE «CON ÉL Y SIN ÉL»
============================
    python3 -m pytest tests/test_onoff.py -v

Lo que importa aquí es que las cuentas cierren. Si el xG repartido
entre los jugadores no suma el del equipo, alguien está cargando con
tiros que no le tocan o librándose de los suyos, y el número resultante
es perfectamente creíble y completamente falso.

Y que el encogido haga su trabajo: que nadie con dos partidos buenos
se cuele por delante de quien lleva media temporada.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.ml.onoff import (
    K_ENCOGIDO, MINIMO_PARA_ENSENAR, acumular, encoger, por_90,
)


def j(nombre, minutos, suplente=False, puesto="DC"):
    return {"nombre": nombre, "minutos": minutos, "suplente": suplente,
            "puesto": puesto, "player_id": nombre}


def once(cambios=None):
    """Once titulares, todos los 90 minutos salvo los que se digan."""
    cambios = cambios or {}
    nombres = ["Portero", "Lateral", "Central1", "Central2", "Lateral2",
               "Medio1", "Medio2", "Medio3", "Extremo1", "Extremo2", "Punta"]
    plantilla = [j(n, cambios.get(n, 90)) for n in nombres]
    for n, m in cambios.items():
        if m < 90:
            plantilla.append(j("Sub_" + n, 90 - m, suplente=True))
    return plantilla


def partido(cambios=None, favor=None, contra=None, etiqueta="x"):
    return {"jugadores": once(cambios), "etiqueta": etiqueta,
            "tiros_favor": favor or [], "tiros_contra": contra or []}


# ── las cuentas cierran ───────────────────────────────────────────

def test_el_xg_repartido_suma_el_del_equipo():
    p = [partido(contra=[{"minuto": 10, "xg": 0.5}, {"minuto": 80, "xg": 0.3}],
                 favor=[{"minuto": 40, "xg": 0.9}])]
    r = acumular(p)
    assert r["equipo"]["xg_contra"] == 0.8
    for x in r["jugadores"]:
        assert abs(x["xg_contra_dentro"] + x["xg_contra_fuera"] - 0.8) < 1e-6, x["nombre"]


def test_los_minutos_de_cada_uno_no_pasan_de_los_del_equipo():
    r = acumular([partido(), partido(), partido()])
    assert r["equipo"]["minutos"] == 270
    for x in r["jugadores"]:
        assert x["minutos"] <= 270
        assert x["minutos"] + x["minutos_fuera"] == 270, x["nombre"]


def test_un_jugador_que_se_pierde_un_partido_entero_lo_cuenta_como_fuera():
    """El caso que es fácil hacer mal.

    Si "sin él" sólo mirase los ratos en que le cambiaron, estaría
    comparando media temporada suya contra veinte minutos sueltos. Los
    partidos que se perdió ENTEROS también son "sin él".
    """
    p1 = partido(contra=[{"minuto": 10, "xg": 1.0}], etiqueta="juega")
    # en el segundo partido no está: su sitio lo ocupa otro
    otros = [j(n, 90) for n in ["Portero", "Lateral", "Central1", "Central2",
                                "Lateral2", "Medio1", "Medio2", "Medio3",
                                "Extremo1", "Extremo2", "Suplente"]]
    p2 = {"jugadores": otros, "etiqueta": "no juega",
          "tiros_favor": [], "tiros_contra": [{"minuto": 50, "xg": 2.0}]}
    r = acumular([p1, p2])
    punta = next(x for x in r["jugadores"] if x["nombre"] == "Punta")
    assert punta["minutos"] == 90
    assert punta["minutos_fuera"] == 90
    assert punta["xg_contra_dentro"] == 1.0
    assert punta["xg_contra_fuera"] == 2.0
    assert punta["contra_90_con"] == 1.0
    assert punta["contra_90_sin"] == 2.0
    assert punta["diferencia_contra"] == -1.0


def test_un_jugador_que_juega_todos_los_minutos_no_tiene_sin_el():
    r = acumular([partido(contra=[{"minuto": 10, "xg": 0.5}])])
    p = next(x for x in r["jugadores"] if x["nombre"] == "Portero")
    assert p["minutos_fuera"] == 0
    assert p["contra_90_sin"] is None
    assert p["diferencia_contra"] is None


# ── el encogido ───────────────────────────────────────────────────

def test_encoger_con_cero_minutos_devuelve_lo_del_equipo():
    assert encoger(99.0, 0, 1.2) == 1.2


def test_a_los_450_minutos_pesa_la_mitad_cada_uno():
    assert encoger(2.0, K_ENCOGIDO, 1.0) == 1.5


def test_cuantos_mas_minutos_menos_se_mueve():
    pocos = encoger(0.2, 180, 1.4)
    muchos = encoger(0.2, 1800, 1.4)
    assert pocos > muchos, "con pocos minutos tiene que acercarse más al equipo"
    assert abs(muchos - 0.2) < abs(pocos - 0.2)


def test_el_encogido_evita_que_dos_partidos_buenos_manden():
    """El fallo que mata la credibilidad.

    Uno juega dos partidos en los que el rival no tiró. Sin encoger,
    sale con un 0,00 y se pone el primero de la lista por delante de
    quien lleva toda la temporada defendiendo bien de verdad.
    """
    # el equipo encaja mucho en general
    muchos = [partido(contra=[{"minuto": 20, "xg": 1.5}]) for _ in range(8)]
    # y en dos partidos no encaja nada, justo los que juega el novato
    sin_encajar = [
        {"jugadores": once() + [j("Novato", 90, suplente=True)],
         "etiqueta": "a", "tiros_favor": [], "tiros_contra": []},
    ]
    # (el novato entra en el once para que las cuentas cuadren)
    novato_once = [j(n, 90) for n in ["Portero", "Lateral", "Central1",
                                      "Central2", "Lateral2", "Medio1",
                                      "Medio2", "Medio3", "Extremo1",
                                      "Extremo2", "Novato"]]
    limpios = [{"jugadores": novato_once, "etiqueta": f"limpio{i}",
                "tiros_favor": [], "tiros_contra": []} for i in range(2)]

    r = acumular(muchos + limpios)
    d = {x["nombre"]: x for x in r["jugadores"]}
    novato = d["Novato"]
    veterano = d["Portero"]

    assert novato["minutos"] == 180
    assert novato["contra_90_con"] == 0.0, "sin encoger sale perfecto"

    # El encogido no tiene que ponerlo POR DETRÁS del veterano: tiene
    # que quitarle casi toda la ventaja que no se ha ganado. Con 180
    # minutos pesa 180/(180+450) = el 29 % él y el 71 % su equipo.
    #
    # (La primera versión de esta prueba exigía que el novato saliera
    # peor que el veterano, y eso era pedirle al encogido algo que no
    # hace. Estaba mal la prueba, no el código.)
    crudo = veterano["contra_90_con"] - novato["contra_90_con"]
    ajustado = veterano["contra_90_ajustado"] - novato["contra_90_ajustado"]
    assert crudo == 1.2, crudo
    assert ajustado < crudo * 0.35, (
        f"la ventaja no ganada baja de {crudo} a {ajustado}, poco")
    assert novato["contra_90_ajustado"] > 0.8, (
        "tiene que acercarse mucho a la media del equipo, que es 1,2")


def test_se_marca_a_quien_ha_jugado_poco():
    r = acumular([partido() for _ in range(2)])
    for x in r["jugadores"]:
        assert x["fiable"] == (x["minutos"] >= MINIMO_PARA_ENSENAR)


# ── cuando un partido no se puede reconstruir ─────────────────────

def test_un_partido_con_expulsion_se_descarta_y_se_dice():
    bueno = partido(contra=[{"minuto": 10, "xg": 1.0}], etiqueta="bueno")
    roto = {"jugadores": [j(f"J{i}", 90) for i in range(10)],
            "etiqueta": "con roja", "tiros_favor": [],
            "tiros_contra": [{"minuto": 50, "xg": 9.0}]}
    r = acumular([bueno, roto])
    assert len(r["descartados"]) == 1
    assert r["descartados"][0]["partido"] == "con roja"
    # y su xG no se ha colado en las cuentas
    assert r["equipo"]["xg_contra"] == 1.0
    assert r["equipo"]["partidos"] == 1


def test_si_no_se_puede_reconstruir_ninguno_no_revienta():
    roto = {"jugadores": [], "etiqueta": "vacío",
            "tiros_favor": [], "tiros_contra": []}
    r = acumular([roto, roto])
    assert r["jugadores"] == []
    assert len(r["descartados"]) == 2
    assert r["equipo"]["minutos"] == 0


def test_sin_partidos_devuelve_vacio_sin_quejarse():
    r = acumular([])
    assert r["jugadores"] == [] and r["equipo"]["partidos"] == 0


# ── orden y forma de la respuesta ─────────────────────────────────

def test_sale_ordenado_por_el_que_menos_encaja():
    r = acumular([partido(cambios={"Punta": 45},
                          contra=[{"minuto": 10, "xg": 0.1},
                                  {"minuto": 70, "xg": 1.9}])
                  for _ in range(6)])
    ajustados = [x["contra_90_ajustado"] for x in r["jugadores"]]
    assert ajustados == sorted(ajustados)


def test_la_respuesta_dice_el_k_que_ha_usado():
    """Para poder discutirlo en vez de tener que buscarlo en el código."""
    r = acumular([partido()])
    assert r["k_encogido"] == K_ENCOGIDO
    assert r["minimo_para_ensenar"] == MINIMO_PARA_ENSENAR


def test_por_90_es_por_90():
    assert por_90(1.0, 90) == 1.0
    assert por_90(1.0, 45) == 2.0
    assert por_90(1.0, 0) == 0.0


def test_el_puesto_no_se_queda_en_sub_para_siempre():
    """Salió con el Barça: Koundé aparecía como «Sub» toda la temporada.

    El programa se quedaba con el puesto del primer partido en que lo
    vio, y si ese día entró desde el banquillo, "Sub" se le quedaba
    pegado. "Sub" no es un puesto: es cómo entró ese día.
    """
    diez = [j(f"T{i}", 90) for i in range(10)]

    # Partido 1: Koundé entra en el 60 por un titular. 10×90 + 60 + 30 = 990
    p1 = {"jugadores": diez + [j("Titular", 60, False, "DR"),
                               j("Koundé", 30, True, "Sub")],
          "etiqueta": "p1", "tiros_favor": [], "tiros_contra": []}

    # Partidos 2 a 4: sale de inicio de lateral derecho
    resto = [{"jugadores": diez + [j("Koundé", 90, False, "DR")],
              "etiqueta": f"p{n}", "tiros_favor": [], "tiros_contra": []}
             for n in range(2, 5)]

    r = acumular([p1] + resto)
    assert not r["descartados"], r["descartados"]
    k = next(x for x in r["jugadores"] if x["nombre"] == "Koundé")
    assert k["puesto"] == "DR", k["puesto"]
    assert k["partidos_de_suplente"] == 1


def test_quien_solo_ha_jugado_de_suplente_lo_dice_sin_mentir():
    """Si de verdad nunca ha salido de inicio, no hay puesto que poner."""
    diez = [j(f"T{i}", 90) for i in range(10)]
    r = acumular([{"jugadores": diez + [j("Sale", 70, False, "DC"),
                                        j("Siempre", 20, True, "Sub")],
                   "etiqueta": "p", "tiros_favor": [], "tiros_contra": []}])
    assert not r["descartados"], r["descartados"]
    s = next(x for x in r["jugadores"] if x["nombre"] == "Siempre")
    assert s["puesto"] == "Sub"
    assert s["partidos_de_suplente"] == 1


def test_los_partidos_de_lectura_dudosa_se_cuentan_y_se_dicen():
    """Cuando los minutos admiten dos lecturas se usa la media.

    Eso no se puede callar: es información sobre lo fino que es el
    dato. Un partido medido a medias no es lo mismo que uno medido.
    """
    diez = [j(f"T{i}", 90) for i in range(10)]
    dudoso = {"jugadores": diez + [j("Sale60", 60), j("Corto", 5, True),
                                   j("Largo", 25, True)],
              "etiqueta": "el dudoso",
              "tiros_favor": [], "tiros_contra": [{"minuto": 62, "xg": 0.04}]}
    r = acumular([dudoso])
    assert not r["descartados"], r["descartados"]
    assert len(r["dudosos"]) == 1
    assert r["dudosos"][0]["partido"] == "el dudoso"
    assert r["dudosos"][0]["cuanto_baila"] == 0.04


def test_un_partido_claro_no_sale_como_dudoso():
    r = acumular([partido(contra=[{"minuto": 10, "xg": 0.5}])])
    assert r["dudosos"] == []


def test_si_la_duda_es_grande_se_descarta_en_vez_de_promediar():
    """0,9 de xG bailando entre dos jugadores ya no es un detalle."""
    diez = [j(f"T{i}", 90) for i in range(10)]
    gordo = {"jugadores": diez + [j("Sale60", 60), j("Corto", 5, True),
                                  j("Largo", 25, True)],
             "etiqueta": "duda gorda",
             "tiros_favor": [], "tiros_contra": [{"minuto": 62, "xg": 0.9}]}
    r = acumular([gordo])
    assert len(r["descartados"]) == 1
    assert r["descartados"][0]["motivo"] == "ambiguo"
    assert r["dudosos"] == []
