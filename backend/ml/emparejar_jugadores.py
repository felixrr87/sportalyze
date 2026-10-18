# -*- coding: utf-8 -*-
"""
EMPAREJAR UN JUGADOR ENTRE DOS FUENTES
======================================
La plantilla sale de football-data: nombre, fecha de nacimiento,
nacionalidad y puesto. Las cifras salen de Understat: tiros, goles,
xG, xA. Ninguna de las dos tiene lo de la otra.

football-data tiene la EDAD, que es justo lo que a Understat le falta
y por lo que el filtro de edad del scouting no existía. Y Understat
tiene las cifras, que es lo que a football-data le falta. Cruzarlos
arregla las dos cosas de una vez.

Para cruzarlos hay que emparejar por nombre, y los nombres casi
coinciden pero no del todo:

    football-data        Understat
    Eric García          Eric Garcia        sobra el acento
    Joan García          Joan Garcia
    Wojciech Szczęsny    Wojciech Szczesny
    Marc-André ter Stegen  Marc-Andre ter Stegen

EL PELIGRO AQUÍ TIENE NOMBRE Y APELLIDO
---------------------------------------
Dos jugadores del mismo equipo que se apellidan igual. En el Barça de
esta temporada hay un Eric García y un Joan García. Si el emparejado
se hiciera por apellido, la ficha de uno enseñaría los tiros del otro
— y como los dos son del mismo equipo y de la misma temporada, no
habría absolutamente nada en pantalla que delatara el cambiazo.

Por eso:

  1. Primero se intenta el nombre completo ya limpio. Si cuadra uno
     solo, ése es.
  2. Si no, se mira cuántos candidatos comparten el apellido. Si hay
     más de uno, se para: el apellido no distingue.
  3. Con un solo candidato por apellido, hace falta además que coincida
     la inicial del nombre de pila.

Y si nada de eso resuelve, se devuelve None con su motivo. Un jugador
sin cifras se dice; un jugador con las cifras de otro no se nota.
"""
import unicodedata


def limpia(nombre: str) -> str:
    """Un nombre reducido a letras minúsculas sin acentos."""
    s = unicodedata.normalize("NFKD", str(nombre or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = "".join(c if c.isalnum() or c.isspace() else " " for c in s)
    return " ".join(s.split())


# Partículas que no sirven para distinguir a nadie. "de", "van",
# "ter"... Se quitan sólo para buscar el apellido, nunca del nombre
# que se enseña en pantalla.
PARTICULAS = {"de", "del", "da", "dos", "van", "von", "der", "den",
              "ter", "la", "le", "di", "do", "al", "el", "bin", "ibn"}


def apellido(nombre: str) -> str:
    """La última palabra que de verdad identifica.

    'Marc-Andre ter Stegen' → 'stegen'. 'Frenkie de Jong' → 'jong'.
    """
    palabras = [p for p in limpia(nombre).split() if p not in PARTICULAS]
    return palabras[-1] if palabras else ""


def inicial(nombre: str) -> str:
    palabras = limpia(nombre).split()
    return palabras[0][0] if palabras and palabras[0] else ""


def emparejar_jugador(nombre, candidatos, clave=lambda c: c):
    """El candidato que es el mismo jugador, o (None, motivo).

    `candidatos` es la lista de la otra fuente y `clave` saca el nombre
    de cada uno. Devuelve (candidato, None) o (None, motivo).
    """
    if not nombre:
        return None, "sin_nombre"
    if not candidatos:
        return None, "sin_candidatos"

    objetivo = limpia(nombre)

    # 1. el nombre entero, ya limpio
    exactos = [c for c in candidatos if limpia(clave(c)) == objetivo]
    if len(exactos) == 1:
        return exactos[0], None
    if len(exactos) > 1:
        # Dos jugadores con el mismo nombre completo en la misma
        # plantilla. Rarísimo, pero si pasa no hay forma de elegir.
        return None, "nombre_repetido"

    # 2. por apellido, exigiendo que sea único
    ap = apellido(nombre)
    if not ap:
        return None, "sin_apellido"
    mismos = [c for c in candidatos if apellido(clave(c)) == ap]
    if not mismos:
        return None, "no_esta"
    if len(mismos) > 1:
        # El caso Eric García / Joan García. Se intenta desempatar con
        # la inicial, y si tampoco, se para.
        ini = inicial(nombre)
        con_inicial = [c for c in mismos if inicial(clave(c)) == ini]
        if len(con_inicial) == 1:
            return con_inicial[0], None
        return None, "apellido_repetido"

    # 3. un solo candidato con ese apellido: que coincida la inicial
    unico = mismos[0]
    if inicial(clave(unico)) == inicial(nombre):
        return unico, None

    # Mismo apellido, nombre de pila distinto. Puede ser un hermano, o
    # puede ser que una fuente use el nombre y la otra el apodo. No se
    # adivina.
    return None, "nombre_de_pila_distinto"


MOTIVOS = {
    "no_esta":
        "Understat no tiene a este jugador esta temporada. Normalmente "
        "quiere decir que no ha jugado ni un minuto en liga.",
    "apellido_repetido":
        "Hay más de un jugador con ese apellido en el equipo y no puedo "
        "distinguirlos con seguridad. Prefiero no enseñar nada a "
        "enseñarte las cifras del otro.",
    "nombre_de_pila_distinto":
        "Encuentro ese apellido pero con otro nombre de pila. No me "
        "arriesgo a que sean dos personas distintas.",
    "nombre_repetido":
        "Hay dos jugadores con el mismo nombre en la plantilla.",
    "sin_candidatos":
        "No he podido traer los jugadores de esa liga en Understat.",
    "sin_nombre": "Ese jugador viene sin nombre.",
    "sin_apellido": "Ese jugador viene sin nombre utilizable.",
}
