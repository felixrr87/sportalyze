# -*- coding: utf-8 -*-
"""
PRUEBAS DE EMPAREJAR UN PARTIDO ENTRE DOS FUENTES
=================================================
    python3 -m pytest tests/test_emparejar.py -v

Lo que de verdad se comprueba aquí no es que empareje bien los fáciles
—eso lo hace cualquier cosa—, sino que NO empareje cuando no está
seguro. Devolver el partido equivocado es el único fallo de verdad
grave de este archivo: enseñaría el informe de otro partido y nadie
tendría forma de notarlo.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.ml.emparejar import (
    MARGEN_DIAS, PARECIDO_MINIMO, VENTAJA_MINIMA,
    emparejar, emparejar_con_motivo, parecido,
)
from backend.scrapers.understat import _normaliza


def c(fecha, local, visitante, mid="x"):
    return {"fecha": fecha, "match_id": mid,
            "clave_local": _normaliza(local),
            "clave_visitante": _normaliza(visitante)}


# ── los nombres que de verdad trae cada fuente ────────────────────

PAREJAS_REALES = [
    ("FC Barcelona",              "Barcelona"),
    ("Real Madrid CF",            "Real Madrid"),
    ("Club Atlético de Madrid",   "Atletico Madrid"),
    ("RCD Espanyol de Barcelona", "Espanyol"),
    ("Paris Saint-Germain FC",    "Paris Saint Germain"),
    ("1. FC Köln",                "FC Cologne"),
    ("Bayer 04 Leverkusen",       "Bayer Leverkusen"),
    ("SSC Napoli",                "Napoli"),
    ("Borussia Mönchengladbach",  "Borussia M.Gladbach"),
    ("VfB Stuttgart",             "VfB Stuttgart"),
    ("Real Sociedad de Fútbol",   "Real Sociedad"),
    ("Manchester City FC",        "Manchester City"),
]


def test_los_nombres_reales_de_las_dos_fuentes_se_parecen_lo_bastante():
    """Cada pareja tiene que llegar a la mitad por lo menos.

    El suelo de verdad (PARECIDO_MINIMO) se le aplica al partido, que
    es la media de los dos equipos. Pero si un equipo se queda en cero,
    el partido entero depende de que el otro salga perfecto, y eso es
    ir demasiado justo. Media es el mínimo decente por equipo.
    """
    flojos = []
    for fd, un in PAREJAS_REALES:
        p = parecido(_normaliza(fd), _normaliza(un))
        if p < 0.5:
            flojos.append(f"{fd} / {un}: {p:.2f} → {_normaliza(fd)!r} vs {_normaliza(un)!r}")
    assert not flojos, "no se parecen lo bastante: " + " · ".join(flojos)


def test_las_traducciones_son_traducciones_y_no_se_pueden_deducir():
    """Que nadie borre la lista pensando que sobra.

    Quitando acentos, "Köln" se queda en "koln". De ahí a "Cologne" no
    se llega con ninguna regla: son dos idiomas.
    """
    from backend.scrapers.understat import TRADUCCIONES
    assert TRADUCCIONES["koln"] == "cologne"
    assert _normaliza("1. FC Köln") == _normaliza("FC Cologne")
    assert _normaliza("FC Bayern München") == _normaliza("Bayern Munich")


def test_un_nombre_corto_dentro_de_uno_largo_vale_entero():
    # "espanyol" está entero dentro de "rcd espanyol barcelona"
    assert parecido("espanyol", "rcd espanyol barcelona") == 1.0


def test_dos_equipos_distintos_no_se_parecen():
    assert parecido(_normaliza("Real Madrid"), _normaliza("Real Sociedad")) < 1.0
    assert parecido(_normaliza("Sevilla FC"), _normaliza("Valencia CF")) == 0.0


# ── emparejar de verdad ───────────────────────────────────────────

def test_empareja_el_partido_aunque_los_nombres_esten_escritos_distinto():
    candidatos = [
        c("2026-10-18", "Barcelona", "Girona", "1"),
        c("2026-10-18", "Real Madrid", "Getafe", "2"),
        c("2026-10-18", "Espanyol", "Elche", "3"),
    ]
    elegido = emparejar("2026-10-18T19:00:00Z",
                        _normaliza("RCD Espanyol de Barcelona"),
                        _normaliza("Elche CF"), candidatos)
    assert elegido["match_id"] == "3"


def test_empareja_aunque_un_equipo_este_en_otro_idioma():
    """Köln contra Cologne no comparten ni una letra del principio.

    Pero el otro equipo del partido sí encaja, y eso basta: por eso se
    puntúa el partido entero y no cada equipo por su cuenta.
    """
    candidatos = [
        c("2026-10-18", "FC Cologne", "Bayern Munich", "1"),
        c("2026-10-18", "Hamburger SV", "Werder Bremen", "2"),
    ]
    elegido = emparejar("2026-10-18",
                        _normaliza("1. FC Köln"),
                        _normaliza("FC Bayern München"), candidatos)
    assert elegido["match_id"] == "1"


def test_el_margen_de_un_dia_por_el_huso_horario():
    """Un partido de las 21:00 del sábado en España cae en domingo UTC."""
    candidatos = [c("2026-10-19", "Barcelona", "Girona", "1")]
    assert emparejar("2026-10-18", _normaliza("FC Barcelona"),
                     _normaliza("Girona FC"), candidatos)["match_id"] == "1"
    # pero dos días ya no
    lejos = [c("2026-10-21", "Barcelona", "Girona", "1")]
    assert emparejar("2026-10-18", _normaliza("FC Barcelona"),
                     _normaliza("Girona FC"), lejos) is None


# ── lo importante: cuándo NO tiene que emparejar ──────────────────

def test_no_empareja_un_partido_de_otro_dia():
    candidatos = [c("2026-05-02", "Barcelona", "Girona", "1")]
    assert emparejar("2026-10-18", _normaliza("FC Barcelona"),
                     _normaliza("Girona FC"), candidatos) is None


def test_no_empareja_si_los_equipos_estan_al_reves():
    """Barcelona–Girona y Girona–Barcelona no son el mismo partido.

    Y en el informe importa: el mapa de tiros dibuja a cada equipo
    atacando hacia un lado.
    """
    candidatos = [c("2026-10-18", "Girona", "Barcelona", "1")]
    elegido = emparejar("2026-10-18", _normaliza("FC Barcelona"),
                        _normaliza("Girona FC"), candidatos)
    assert elegido is None


def test_no_elige_a_cara_o_cruz_entre_dos_que_encajan_igual():
    """El caso que de verdad da miedo.

    Si dos candidatos puntúan casi lo mismo, elegir uno es acertar la
    mitad de las veces y enseñar el informe de otro partido la otra
    mitad, sin que se note. Mejor no enseñar nada.
    """
    candidatos = [
        c("2026-10-18", "Real Madrid", "Getafe", "1"),
        c("2026-10-18", "Real Madrid", "Getafe", "2"),
    ]
    assert emparejar("2026-10-18", _normaliza("Real Madrid CF"),
                     _normaliza("Getafe CF"), candidatos) is None


def test_no_empareja_con_un_calendario_vacio():
    assert emparejar("2026-10-18", "barcelona", "girona", []) is None


def test_una_fecha_ilegible_no_empareja_nada():
    candidatos = [c("2026-10-18", "Barcelona", "Girona", "1")]
    assert emparejar("el sábado", "barcelona", "girona", candidatos) is None
    assert emparejar(None, "barcelona", "girona", candidatos) is None


def test_un_candidato_sin_fecha_se_ignora_en_vez_de_reventar():
    candidatos = [
        {"fecha": None, "clave_local": "barcelona", "clave_visitante": "girona",
         "match_id": "roto"},
        c("2026-10-18", "Barcelona", "Girona", "bueno"),
    ]
    assert emparejar("2026-10-18", "barcelona", "girona",
                     candidatos)["match_id"] == "bueno"


# ── los motivos, que van a la pantalla ────────────────────────────

def test_cada_fallo_tiene_su_motivo():
    candidatos = [c("2026-10-18", "Barcelona", "Girona", "1")]

    _, m = emparejar_con_motivo("2026-05-02", "sevilla", "betis", candidatos)
    assert m == "sin_partidos_ese_dia"

    _, m = emparejar_con_motivo("2026-10-18", "sevilla", "betis", candidatos)
    assert m == "nombres_no_encajan"

    _, m = emparejar_con_motivo("2026-10-18", "barcelona", "girona", [])
    assert m == "sin_calendario"

    _, m = emparejar_con_motivo("ayer", "barcelona", "girona", candidatos)
    assert m == "fecha_ilegible"

    elegido, m = emparejar_con_motivo("2026-10-18", "barcelona", "girona", candidatos)
    assert m is None and elegido["match_id"] == "1"


def test_los_umbrales_estan_puestos_a_mano_y_son_razonables():
    """Si alguien los toca sin pensar, que se entere aquí."""
    assert 0 < PARECIDO_MINIMO < 1
    assert 0 < VENTAJA_MINIMA < 1
    assert MARGEN_DIAS == 1


# ══════════════════════════════════════════════════════════════════
# EL FALLO PELIGROSO: EMPAREJAR CON UN EQUIPO PARECIDO
# ══════════════════════════════════════════════════════════════════
#
# No es que no empareje: es que empareje MAL y nadie lo note. Pasaría
# así: busco Real Madrid–Getafe un día en que ese partido no está en
# Understat todavía, pero sí está Real Sociedad–Getafe. Comparten la
# palabra "Real" y comparten el Getafe entero. La media pasa el suelo,
# no hay otro candidato con quien compararlo, y se devuelve el partido
# del Real Sociedad con el escudo del Real Madrid encima.

def test_no_confunde_real_madrid_con_real_sociedad():
    candidatos = [c("2026-10-18", "Real Sociedad", "Getafe", "otro")]
    assert emparejar("2026-10-18", _normaliza("Real Madrid CF"),
                     _normaliza("Getafe CF"), candidatos) is None


def test_no_confunde_los_dos_de_manchester():
    candidatos = [c("2026-10-18", "Manchester United", "Arsenal", "otro")]
    assert emparejar("2026-10-18", _normaliza("Manchester City FC"),
                     _normaliza("Arsenal FC"), candidatos) is None


def test_no_confunde_atletico_con_real_madrid():
    candidatos = [c("2026-10-18", "Real Madrid", "Osasuna", "otro")]
    assert emparejar("2026-10-18", _normaliza("Club Atlético de Madrid"),
                     _normaliza("CA Osasuna"), candidatos) is None


def test_pero_sigue_emparejando_el_de_verdad_cuando_está():
    """El guardia nuevo no puede cargarse los emparejados buenos."""
    candidatos = [
        c("2026-10-18", "Real Sociedad", "Getafe", "parecido"),
        c("2026-10-18", "Real Madrid", "Getafe", "bueno"),
    ]
    assert emparejar("2026-10-18", _normaliza("Real Madrid CF"),
                     _normaliza("Getafe CF"), candidatos)["match_id"] == "bueno"


def test_todas_las_parejas_reales_pasan_el_suelo_por_equipo():
    """Si alguna no llega, ese equipo no se podrá emparejar nunca."""
    from backend.ml.emparejar import PARECIDO_MINIMO_POR_EQUIPO
    flojos = [f"{fd} / {un}" for fd, un in PAREJAS_REALES
              if parecido(_normaliza(fd), _normaliza(un)) < PARECIDO_MINIMO_POR_EQUIPO]
    assert not flojos, "no llegan al suelo por equipo: " + " · ".join(flojos)
