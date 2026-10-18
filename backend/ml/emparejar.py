# -*- coding: utf-8 -*-
"""
EMPAREJAR UN PARTIDO ENTRE DOS FUENTES
======================================
El calendario sale de football-data y los tiros de Understat. Cada uno
tiene sus identificadores de partido y no se parecen en nada, así que
para ir de uno al otro hay que emparejarlos por lo único que comparten:
la fecha y los dos equipos.

POR QUÉ NO VALE COMPARAR NOMBRES A SECAS
----------------------------------------
Porque no coinciden, y no coinciden de maneras distintas:

    football-data              Understat
    FC Barcelona               Barcelona          sobra "FC"
    Paris Saint-Germain FC     Paris Saint Germain   guion contra espacio
    1. FC Köln                 FC Cologne         es otro idioma
    RCD Espanyol de Barcelona  Espanyol           sobra media frase

Limpiar y comparar resuelve los dos primeros y se estrella con los dos
últimos. Y una tabla de equivalencias a mano se queda vieja en cuanto
asciende un equipo.

CÓMO SE HACE AQUÍ
-----------------
Primero la FECHA, que es un dato duro: dos equipos pueden jugar dos
veces en la temporada, pero no el mismo día. Eso deja los partidos de
esa jornada, diez como mucho.

Entre esos pocos se busca el que más se parezca, contando palabras en
común entre los nombres de los dos equipos. "Köln" y "Cologne" no
comparten ninguna, pero es que tampoco hace falta que la comparta ese:
el OTRO equipo del partido casi siempre sí, y con un solo partido de
esa jornada que encaje a medias, ya es ése.

Y SI HAY DUDA, NO SE ADIVINA
----------------------------
Si el mejor no le saca ventaja clara al segundo, se devuelve None y la
pantalla dice que no ha podido emparejarlo. Un informe del partido
equivocado es mucho peor que no tener informe: el visitante no tiene
forma de darse cuenta.

El margen de un día existe porque un partido de las 21:00 del sábado
en España es del domingo en hora UTC, y las dos fuentes no siempre
usan el mismo huso.
"""
from datetime import date, datetime, timedelta

# Cuánto tiene que ganarle el mejor al segundo para fiarse de él.
VENTAJA_MINIMA = 0.25

# Por debajo de esto no se considera ni candidato.
PARECIDO_MINIMO = 0.40

# Y cada equipo por separado tiene que llegar a esto.
#
# Esto es lo que evita el fallo peligroso de verdad. "Real Madrid" y
# "Real Sociedad" comparten la palabra "Real", así que se parecen un
# 0,50. Si busco Real Madrid–Getafe un día en que sólo hay Real
# Sociedad–Getafe, la media sale (0,50 + 1,00) / 2 = 0,75, pasa el
# suelo del partido, no hay segundo candidato con quien compararlo, y
# se devuelve un partido que no es.
#
# Exigiendo 0,60 a CADA equipo, ese caso se cae: Real Madrid contra
# Real Sociedad no llega. Y los emparejados buenos no sufren, porque
# todos los nombres reales comprobados salen a 1,00 una vez
# normalizados y traducidos.
PARECIDO_MINIMO_POR_EQUIPO = 0.60

# Días de margen por la diferencia de huso horario entre las fuentes.
MARGEN_DIAS = 1


def _fecha(valor) -> date:
    """Acepta '2026-10-18', '2026-10-18T19:00:00Z' o un date."""
    if isinstance(valor, date) and not isinstance(valor, datetime):
        return valor
    if isinstance(valor, datetime):
        return valor.date()
    texto = str(valor or "")[:10]
    try:
        return datetime.strptime(texto, "%Y-%m-%d").date()
    except ValueError:
        return None


def parecido(a: str, b: str) -> float:
    """De 0 a 1, cuánto se parecen dos nombres ya normalizados.

    Palabras en común sobre las del más corto, no sobre el total: así
    "espanyol" contra "rcd espanyol barcelona" sale 1, que es lo que
    queremos, porque el nombre corto está entero dentro del largo.
    """
    pa = set(str(a or "").split())
    pb = set(str(b or "").split())
    if not pa or not pb:
        return 0.0
    comunes = len(pa & pb)
    if comunes:
        return comunes / min(len(pa), len(pb))
    # Ninguna palabra en común: puede ser otro idioma (Köln/Cologne) o
    # que uno sea el principio del otro (Gladbach/M.Gladbach).
    for x in pa:
        for y in pb:
            if len(x) >= 4 and len(y) >= 4 and (x.startswith(y) or y.startswith(x)):
                return 0.5
    return 0.0


def emparejar(fecha, local: str, visitante: str, candidatos: list) -> dict:
    """El partido de `candidatos` que es el mismo que el de fuera.

    `local` y `visitante` vienen ya normalizados. Cada candidato es un
    diccionario con 'fecha', 'clave_local' y 'clave_visitante'.

    Devuelve el candidato, o None si no hay ninguno lo bastante claro.
    """
    f = _fecha(fecha)
    if f is None or not candidatos:
        return None

    puntuados = []
    for c in candidatos:
        fc = _fecha(c.get("fecha"))
        if fc is None or abs((fc - f).days) > MARGEN_DIAS:
            continue
        pl = parecido(local, c.get("clave_local", ""))
        pv = parecido(visitante, c.get("clave_visitante", ""))
        if pl < PARECIDO_MINIMO_POR_EQUIPO or pv < PARECIDO_MINIMO_POR_EQUIPO:
            continue
        p = (pl + pv) / 2
        if p >= PARECIDO_MINIMO:
            puntuados.append((p, c))

    if not puntuados:
        return None

    puntuados.sort(key=lambda x: -x[0])
    mejor, candidato = puntuados[0]
    if len(puntuados) > 1:
        segundo = puntuados[1][0]
        if mejor - segundo < VENTAJA_MINIMA:
            # Dos partidos encajan casi igual de bien. Antes que elegir
            # uno a cara o cruz, no se elige.
            return None
    return candidato


def emparejar_con_motivo(fecha, local: str, visitante: str, candidatos: list):
    """Como `emparejar`, pero explicando por qué cuando falla.

    El motivo va a la pantalla: "no hay partidos ese día" y "hay dos
    que encajan igual" son dos problemas distintos y el visitante
    merece saber cuál de los dos le ha tocado.
    """
    f = _fecha(fecha)
    if f is None:
        return None, "fecha_ilegible"
    if not candidatos:
        return None, "sin_calendario"

    delimites = [c for c in candidatos
                 if _fecha(c.get("fecha")) is not None
                 and abs((_fecha(c["fecha"]) - f).days) <= MARGEN_DIAS]
    if not delimites:
        return None, "sin_partidos_ese_dia"

    elegido = emparejar(fecha, local, visitante, candidatos)
    if elegido is None:
        return None, "nombres_no_encajan"
    return elegido, None
