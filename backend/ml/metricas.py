# -*- coding: utf-8 -*-
"""
QUÉ SE PUEDE PUNTUAR CON UNDERSTAT, Y QUÉ NO
============================================
Las métricas del scouting, y la razón de que sean éstas y no otras.

LO QUE PASABA ANTES
-------------------
La tabla de métricas pedía, para un centrocampista: pases completados,
pases progresivos, presiones y duelos ganados. Para un defensa:
entradas, intercepciones, despejes, duelos aéreos y bloqueos. Para un
portero: paradas, xGA, PSxG y salidas.

Understat NO PUBLICA NINGUNA DE ESAS COSAS. Publica tiros y lo que
rodea a un tiro: goles, xG, npxG, asistencias, xA, pases clave,
xGChain y xGBuildup. Nada defensivo, nada de pases, nada de porteros.

Y el código las pedía con `player.get(clave, 0) or 0`. O sea: cuando
no estaban —que era casi siempre— valían cero y seguía adelante.

El resultado, medido:

    delanteros        llegaban 5 de 8 métricas
    centrocampistas   llegaban 2 de 8   -> todos al suelo
    defensas          llegaban 0 de 8   -> TODOS exactamente 40,0
    porteros          llegaban 0 de 8   -> TODOS exactamente 40,0

Una pantalla que se llama «Scouting ML» ordenaba a los defensas por un
número constante. El orden que salía era el orden en que venían de la
fuente, con pinta de ranking.

LO QUE HAY AHORA
----------------
Sólo métricas que Understat da de verdad, y POR 90 MINUTOS en vez de
totales. Un total premia a quien más ha jugado, no a quien mejor
juega: con totales, el suplente que entra 20 minutos y marca nunca
sube, y el titular mediocre que juega 3.000 minutos siempre está
arriba.

Y para defensas y porteros NO HAY PUNTUACIÓN. No es que esté pendiente:
es que con esta fuente no se puede, y un número inventado para un
defensa es peor que no tener la pantalla. Se dice y se acabó.

POR QUÉ PERCENTILES Y NO UNA SUMA PONDERADA
-------------------------------------------
Antes se sumaban las métricas multiplicadas por un peso y se
normalizaba. Eso mezcla unidades que no se pueden mezclar —goles con
tiros con xGChain— y el resultado depende de la escala de cada una:
los tiros, que son números grandes, pesaban mucho más que su peso.

Ahora cada métrica se convierte a percentil DENTRO DEL GRUPO que se
está mirando (los delanteros de esa liga con esos minutos) y se
promedian los percentiles con sus pesos. Un 90 quiere decir algo
concreto y comprobable: «mejor que el 90 % de los delanteros de esta
comparación». Es también lo que hacen los informes de scouting de
verdad.
"""

# Las claves son las que devuelve backend/scrapers/understat.py. Si
# alguna no está en el diccionario de un jugador, el puesto entero se
# considera no puntuable: no se rellena con ceros.
#
# Todas las de abajo son POR 90 MINUTOS, calculadas en scouting.py a
# partir de los totales y de los minutos jugados.
METRICAS_POR_PUESTO = {
    "FW": {
        "titulo": "Delanteros",
        "metricas": [
            # (clave, etiqueta, peso, se_normaliza_por_90)
            ("npxG",       "npxG/90",        0.30, True),
            ("goals",      "Goles/90",       0.20, True),
            ("xA",         "xA/90",          0.18, True),
            ("assists",    "Asistencias/90", 0.10, True),
            ("key_passes", "Pases clave/90", 0.10, True),
            ("shots",      "Tiros/90",       0.07, True),
            ("xGChain",    "xGChain/90",     0.05, True),
        ],
        "explica": (
            "npxG es el xG sin contar penaltis: mide lo que genera "
            "jugando, no lo que le regalan desde los once metros."),
    },
    "MF": {
        "titulo": "Centrocampistas",
        "metricas": [
            ("xA",         "xA/90",          0.24, True),
            ("key_passes", "Pases clave/90", 0.20, True),
            ("xGBuildup",  "xGBuildup/90",   0.18, True),
            ("xGChain",    "xGChain/90",     0.14, True),
            ("assists",    "Asistencias/90", 0.12, True),
            ("npxG",       "npxG/90",        0.07, True),
            ("goals",      "Goles/90",       0.05, True),
        ],
        "explica": (
            "xGBuildup es el xG de las jugadas en las que participó "
            "SIN contar su propio tiro ni su propia asistencia: mide al "
            "que construye y no acaba. Es lo más parecido a medir a un "
            "centrocampista que hay en esta fuente."),
    },
}

# Puestos que esta fuente no permite puntuar, y por qué. El texto sale
# tal cual en pantalla: la gente tiene derecho a saber por qué no hay
# número en vez de ver uno malo.
PUESTOS_SIN_DATOS = {
    "DF": (
        "Understat sólo publica datos de tiro: goles, xG, asistencias, "
        "pases clave y poco más. No publica entradas, ni intercepciones, "
        "ni despejes, ni duelos. Con eso no se puede puntuar a un "
        "defensa, así que no se puntúa. Antes esta pantalla les daba a "
        "todos un 40,0 y los ordenaba como si significara algo."),
    "GK": (
        "Understat no publica nada de porteros: ni paradas, ni xG "
        "evitado, ni salidas. Un ranking de porteros con esta fuente "
        "sería un ranking inventado."),
}

# Mínimo de jugadores para que un percentil quiera decir algo. Con
# ocho delanteros, estar en el percentil 90 es estar el primero de
# ocho, y decirlo como «mejor que el 90 %» infla lo que hay.
MINIMO_PARA_PERCENTILES = 12
