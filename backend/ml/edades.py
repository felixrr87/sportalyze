# -*- coding: utf-8 -*-
"""
LA EDAD, QUE UNDERSTAT NO DA
============================
Understat publica tiros y minutos. No publica la fecha de nacimiento
de nadie. football-data sí la publica, en la plantilla de cada equipo.

Hasta hoy eso dejaba el filtro de edad en una promesa a medias:

  · `/api/scouting` lo pedía, no había edades, y AVISABA de que no se
    había aplicado. Honesto, pero inútil.
  · `/api/players` lo pedía en la firma y no lo aplicaba NI AVISABA.
    Eso ya no es honesto: la documentación de la ruta decía
    «Filtros: posición, minutos mínimos, edad máxima» y el tercero no
    existía. Un filtro que no filtra y no lo dice es peor que no
    tenerlo.

POR QUÉ ESTO ES UN FICHERO Y NO UNA LLAMADA EN VIVO
---------------------------------------------------
La plantilla de un equipo es UNA petición a football-data. Una liga
son veinte equipos; las cinco grandes, noventa y ocho. Con nueve
peticiones por minuto, eso son dos minutos para una liga y once para
las cinco — cada vez que alguien abriera el Scouting.

No se puede hacer en vivo, y fingir que sí sería mentir con otro
disfraz. Así que se baja UNA vez con `herramientas/descargar_edades.py`
y se guarda. La aplicación lee el fichero y, si no está, lo dice y no
filtra.

LO QUE SE GUARDA ES LA FECHA DE NACIMIENTO, NO LA EDAD
------------------------------------------------------
Guardar «24» sería tener a medio mundo con un año de menos en cuanto
pasara su cumpleaños, sin que nadie se enterara. La fecha no caduca:
la edad se calcula al preguntar.

Lo que SÍ caduca es la plantilla — en enero hay mercado. Por eso el
fichero lleva la fecha en que se bajó y, pasados DIAS_PARA_AVISAR, se
dice en los avisos. No se bloquea: una edad de hace dos meses sigue
siendo mejor que ninguna, mientras se sepa de cuándo es.
"""
from __future__ import annotations

import json
import os
from datetime import date

# Carpeta donde viven los ficheros bajados. Fuera de backend/ml para
# que se vea que son DATOS y no código.
CARPETA = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "datos")

# A partir de aquí el fichero se considera viejo y se avisa. Cuarenta y
# cinco días es poco más de un mercado de invierno: lo suficiente para
# que haya cambiado alguna plantilla.
DIAS_PARA_AVISAR = 45


def ruta(liga: str, season) -> str:
    return os.path.join(CARPETA, f"edades_{str(liga).upper()}_{season}.json")


def edad_a_dia_de_hoy(nacimiento: str, hoy: date = None) -> int:
    """Años CUMPLIDOS. Devuelve None si la fecha falta o viene rota.

    Años cumplidos y no la resta de años: quien nació el 31 de
    diciembre de 2000 no tiene 25 el 1 de enero de 2025. Y None, nunca
    un cero: un cero se cuela por cualquier filtro de edad máxima y
    convierte a un veterano en una perla de dieciséis.
    """
    if not nacimiento:
        return None
    try:
        a, m, d = (int(x) for x in str(nacimiento)[:10].split("-"))
    except (ValueError, TypeError):
        return None
    hoy = hoy or date.today()
    try:
        cumple = date(hoy.year, m, d)
    except ValueError:                      # 29 de febrero en año normal
        cumple = date(hoy.year, 3, 1)
    return hoy.year - a - (1 if hoy < cumple else 0)


def cargar(liga: str, season):
    """El fichero de una liga, o None si no está.

    None y no una excepción: que no haya edades es una situación
    normal —nadie ha bajado el fichero todavía— y lo que toca es
    avisar y seguir, no tirar la pantalla entera.
    """
    try:
        with open(ruta(liga, season), encoding="utf-8") as fh:
            d = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    if not isinstance(d, dict) or "jugadores" not in d:
        return None
    return d


def dias_desde(fichero, hoy: date = None) -> int:
    """Cuántos días tiene el fichero. None si no lo dice."""
    cuando = (fichero or {}).get("descargado")
    if not cuando:
        return None
    try:
        a, m, d = (int(x) for x in str(cuando)[:10].split("-"))
    except (ValueError, TypeError):
        return None
    return ((hoy or date.today()) - date(a, m, d)).days


def poner_edades(players, fichero, hoy: date = None):
    """Pega la edad a cada jugador de Understat. Devuelve los avisos.

    Toca `players` en el sitio: añade `age`, `birth` y `nationality` a
    los que se encuentran. A los que no, NO les pone nada — ni un cero
    ni un «desconocido» que luego alguien compare con un número.
    """
    avisos = []
    if not fichero:
        return 0, avisos

    jug = fichero.get("jugadores") or {}
    puestos = 0
    for p in players:
        # `player_id` primero: es la clave de Understat y la que usa el
        # fichero. `id` sólo como respaldo, porque algunas listas
        # internas lo traen con ese nombre.
        d = jug.get(str(p.get("player_id") or p.get("id") or ""))
        if not d:
            continue
        edad = edad_a_dia_de_hoy(d.get("nacimiento"), hoy)
        if edad is None:
            continue
        p["age"] = edad
        p["birth"] = d.get("nacimiento")
        if d.get("nacionalidad"):
            p["nationality"] = d["nacionalidad"]
        puestos += 1

    dias = dias_desde(fichero, hoy)
    if dias is not None and dias > DIAS_PARA_AVISAR:
        avisos.append(
            f"Las fechas de nacimiento se bajaron hace {dias} días. Las "
            f"edades siguen bien —se calculan hoy—, pero un fichaje "
            f"posterior no está en la lista.")
    return puestos, avisos


def aviso_de_cobertura(puestos: int, total: int, max_age) -> str:
    """La frase que explica a quién se le ha aplicado el filtro.

    Existe porque «quedan 40 jugadores» significa cosas muy distintas
    según si se ha filtrado a los 400 o sólo a los 120 que tenían edad.
    """
    if total == 0:
        return None
    if puestos == 0:
        return (f"Ningún jugador tiene fecha de nacimiento, así que el "
                f"filtro de edad máxima ({max_age}) NO se ha aplicado. "
                f"Falta bajar las edades de esta liga.")
    if puestos < total:
        return (f"{puestos} de {total} jugadores tienen fecha de "
                f"nacimiento. El filtro de edad se ha aplicado sólo a "
                f"ésos; los {total - puestos} sin fecha se quedan, "
                f"porque descartarlos sería dar por viejo a quien no "
                f"se ha podido emparejar.")
    return None
