# -*- coding: utf-8 -*-
"""
QUÉ TEMPORADA ES HOY
====================
Una sola función, y existe por un fallo que costó caro de ver.

LO QUE PASABA
-------------
La temporada estaba escrita a mano como 2024 en seis sitios: cinco
rutas y el scraper. O sea que toda la parte de jugadores —Cartas,
Scouting ML, Comparador, Watchlist— enseñaba la temporada 2024/25,
que acabó hace año y medio, mientras la clasificación, los partidos y
el Simulador iban de la temporada en curso.

En la misma aplicación convivían dos años distintos. Se vio comparando
la plantilla del Barça entre las dos fuentes: football-data decía
Gabriel Jesus y Rodri, Understat decía Lewandowski y Ter Stegen.

Medido el día que se encontró:

    temporada 2024   590 jugadores, hasta 3.114 minutos   (entera)
    temporada 2026   473 jugadores, hasta   720 minutos   (9 jornadas)

Y de paso explica por qué los filtros iban raros: 400 minutos mínimos
es un filtro suave en una temporada entera y durísimo en octubre.

CÓMO SE CALCULA
---------------
Understat llama a la temporada por el año en que EMPIEZA: 2026 es la
2026/27. Las ligas europeas arrancan en agosto, así que de enero a
julio la temporada en curso es la que empezó el año anterior.

Julio es el mes de corte y no agosto a propósito: a primeros de agosto
ya hay jornadas jugadas en algunas ligas, y pedir la temporada vieja
en agosto daría la de hace un año con todos sus minutos, que es el
fallo que se está arreglando aquí.
"""
from datetime import date

# Mes a partir del cual se considera que ya es la temporada nueva.
MES_DE_CORTE = 7


def temporada_actual(hoy: date = None) -> int:
    """El año en que empezó la temporada que se está jugando.

    >>> temporada_actual(date(2026, 10, 18))
    2026
    >>> temporada_actual(date(2027, 3, 1))
    2026
    >>> temporada_actual(date(2027, 8, 15))
    2027
    """
    hoy = hoy or date.today()
    return hoy.year if hoy.month >= MES_DE_CORTE else hoy.year - 1


def nombre_temporada(anyo: int = None) -> str:
    """'2026/27', para enseñarlo en pantalla."""
    anyo = anyo if anyo is not None else temporada_actual()
    return f"{anyo}/{str(anyo + 1)[-2:]}"
