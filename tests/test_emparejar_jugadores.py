# -*- coding: utf-8 -*-
"""
PRUEBAS DE EMPAREJAR UN JUGADOR ENTRE DOS FUENTES
=================================================
    python3 -m pytest tests/test_emparejar_jugadores.py -v

La prueba que de verdad importa es la del Barça de esta temporada:
tiene un Eric García y un Joan García. Si el emparejado se hace por
apellido, la ficha de uno enseña los tiros del otro, y como los dos
son del mismo equipo y la misma temporada NO HAY NADA en pantalla que
lo delate.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.ml.emparejar_jugadores import (
    MOTIVOS, apellido, emparejar_jugador, inicial, limpia,
)

# Los nombres reales de Understat en el Barça de 2026/27.
BARCA_UNDERSTAT = [
    "Dani Olmo", "Raphinha", "Lamine Yamal", "Fermín López",
    "Karim Adeyemi", "Marc Bernal", "Pedri", "Rodri", "Gabriel Jesus",
    "Anthony Gordon", "Gavi", "João Cancelo", "Jules Koundé",
    "Eric Garcia", "Joan Garcia", "Pau Cubarsí", "Frenkie de Jong",
    "Marc-Andre ter Stegen", "Wojciech Szczesny",
]


def empareja(nombre, candidatos=None):
    return emparejar_jugador(nombre, candidatos or BARCA_UNDERSTAT)


# ── limpieza de nombres ───────────────────────────────────────────

def test_quita_acentos_y_mayusculas():
    assert limpia("Eric García") == "eric garcia"
    assert limpia("Wojciech Szczęsny") == "wojciech szczesny"
    assert limpia("Marc-André ter Stegen") == "marc andre ter stegen"


def test_el_apellido_salta_las_particulas():
    assert apellido("Frenkie de Jong") == "jong"
    assert apellido("Marc-André ter Stegen") == "stegen"
    assert apellido("João Cancelo") == "cancelo"
    assert apellido("Pedri") == "pedri"


def test_la_inicial_es_la_del_nombre_de_pila():
    assert inicial("Eric García") == "e"
    assert inicial("Joan García") == "j"


# ── emparejados buenos ────────────────────────────────────────────

def test_empareja_aunque_cambien_los_acentos():
    c, m = empareja("Jules Koundé")
    assert m is None and c == "Jules Koundé"

    c, m = empareja("Wojciech Szczęsny")
    assert m is None and c == "Wojciech Szczesny"


def test_empareja_un_nombre_de_una_sola_palabra():
    c, m = empareja("Pedri")
    assert m is None and c == "Pedri"


def test_empareja_con_particulas_en_medio():
    c, m = empareja("Frenkie de Jong")
    assert m is None and c == "Frenkie de Jong"


def test_empareja_aunque_una_fuente_escriba_el_acento_y_la_otra_no():
    # football-data: "Marc-André ter Stegen" · Understat: sin acento
    c, m = empareja("Marc-André ter Stegen")
    assert m is None and c == "Marc-Andre ter Stegen"


# ══════════════════════════════════════════════════════════════════
# EL CASO QUE DA MIEDO: DOS GARCÍA EN LA MISMA PLANTILLA
# ══════════════════════════════════════════════════════════════════

def test_distingue_a_eric_garcia_de_joan_garcia():
    """Los dos están en el Barça. Por apellido serían el mismo.

    Y si se equivoca, la ficha de un central enseña los tiros de un
    portero, en el mismo equipo y la misma temporada: nada en pantalla
    lo delataría.
    """
    c, m = empareja("Eric García")
    assert m is None and c == "Eric Garcia"

    c, m = empareja("Joan García")
    assert m is None and c == "Joan Garcia"


def test_si_el_apellido_se_repite_y_la_inicial_tambien_se_niega():
    candidatos = ["Eric Garcia", "Enzo Garcia"]
    c, m = emparejar_jugador("Emilio García", candidatos)
    assert c is None
    assert m == "apellido_repetido"
    assert "otro" in MOTIVOS[m]


def test_mismo_apellido_pero_otro_nombre_de_pila_no_empareja():
    c, m = emparejar_jugador("Thiago Alcántara", ["Rafinha Alcantara"])
    assert c is None and m == "nombre_de_pila_distinto"


def test_un_jugador_que_no_esta_en_understat_se_dice():
    c, m = empareja("Xavi Espart")
    assert c is None and m == "no_esta"
    assert "no ha jugado" in MOTIVOS[m]


def test_dos_jugadores_con_el_mismo_nombre_completo_no_se_eligen():
    c, m = emparejar_jugador("Luis Suárez", ["Luis Suarez", "Luis Suárez"])
    assert c is None and m == "nombre_repetido"


def test_sin_candidatos_o_sin_nombre_no_revienta():
    assert emparejar_jugador("Pedri", []) == (None, "sin_candidatos")
    assert emparejar_jugador("", BARCA_UNDERSTAT) == (None, "sin_nombre")
    assert emparejar_jugador(None, BARCA_UNDERSTAT) == (None, "sin_nombre")


def test_cada_motivo_tiene_su_explicacion():
    """Los motivos van a la pantalla, así que todos tienen que existir."""
    usados = ["no_esta", "apellido_repetido", "nombre_de_pila_distinto",
              "nombre_repetido", "sin_candidatos", "sin_nombre", "sin_apellido"]
    for m in usados:
        assert m in MOTIVOS and len(MOTIVOS[m]) > 20, m


# ── sobre diccionarios, que es como se usa de verdad ──────────────

def test_funciona_sacando_el_nombre_de_un_diccionario():
    jugadores = [{"name": "Eric Garcia", "player_id": "1"},
                 {"name": "Joan Garcia", "player_id": "2"}]
    c, m = emparejar_jugador("Joan García", jugadores, clave=lambda x: x["name"])
    assert m is None and c["player_id"] == "2"


def test_la_plantilla_entera_se_empareja_sin_confundir_a_nadie():
    """Cada jugador de Understat se usa como mucho una vez.

    Si dos nombres distintos de la plantilla apuntaran al mismo
    jugador de Understat, uno de los dos estaría enseñando cifras
    ajenas.
    """
    plantilla = ["Eric García", "Joan García", "Pedri", "Jules Koundé",
                 "Frenkie de Jong", "Marc-André ter Stegen", "Gavi",
                 "Wojciech Szczęsny", "Pau Cubarsí"]
    vistos = []
    for n in plantilla:
        c, m = empareja(n)
        assert m is None, f"{n}: {m}"
        vistos.append(c)
    assert len(set(vistos)) == len(vistos), "hay un jugador emparejado dos veces"
