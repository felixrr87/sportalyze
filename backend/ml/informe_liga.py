# -*- coding: utf-8 -*-
"""
INFORME DE UN PARTIDO DE ESTA TEMPORADA
=======================================
El informe post-partido que ya había usa StatsBomb, que es la mejor
fuente abierta que existe —pases, presiones, posiciones de todos los
jugadores— pero publica competiciones cerradas: Mundiales, Eurocopas,
temporadas de hace años. Del partido del sábado pasado no hay nada y
no lo va a haber.

Así que para los partidos de esta temporada hace falta otra fuente, y
la única abierta que los tiene es Understat. Understat da tiros: dónde
se tiró, con qué parte del cuerpo, desde qué jugada, y qué valía cada
tiro. Y por jugador, en ESE partido: minutos, goles, asistencias,
tiros, pases clave, xG, xA, xGChain y xGBuildup.

LO QUE ESTE INFORME NO PUEDE TENER, Y SE DICE ARRIBA
----------------------------------------------------
No hay red de pases, ni mapa de posiciones, ni presiones, ni
recuperaciones, ni duelos. Nada de eso está en Understat. El informe
de StatsBomb lo tiene y éste no, y la pantalla lo dice antes de que el
visitante se pregunte dónde está.

Poner un apartado "Red de pases" vacío, o dibujarla con los once de la
alineación colocados por su posición nominal, sería inventarse el
dato: esa red no se ha medido.

QUÉ SÍ TIENE, Y POR QUÉ CADA COSA
---------------------------------
  · el marcador y el xG de los dos, que es la pregunta de siempre:
    ¿ganó el que mereció ganar?
  · la carrera de xG minuto a minuto, que enseña CUÁNDO pasó: un 2-0
    de dos contras en el 85 no se parece en nada a un 2-0 de dominar
    noventa minutos, y en la tabla los dos son un 2-0
  · el mapa de tiros de los dos, cada uno atacando hacia su lado
  · la mejor ocasión de cada equipo
  · la tabla de jugadores con sus minutos y sus cifras
  · cuánto de los tiros vino de jugada, de balón parado y de penalti,
    porque un xG hinchado por un penalti no dice lo mismo
"""

# Los tiros de Understat vienen con X e Y de 0 a 100 (el scraper ya los
# multiplica). El campo del dibujo mide 120 x 80, como el de StatsBomb,
# para poder reaprovechar el mismo dibujo de campo.
LARGO = 120.0
ANCHO = 80.0

# Un tiro por encima de esto es "ocasión clarísima". No es un número
# oficial: es el que se usa habitualmente para hablar de "big chance",
# y va escrito aquí para que se pueda discutir en vez de estar
# escondido en medio de una cuenta.
OCASION_CLARA = 0.30


def _a_campo(x, y, visitante=False):
    """De las coordenadas de Understat a las del campo que se dibuja.

    Understat da SIEMPRE al que tira atacando hacia x=100, igual que
    StatsBomb hacia x=120. Para que en el dibujo cada equipo ataque
    hacia su lado, al visitante se le da la vuelta en los dos ejes.

    Darle la vuelta sólo en x es el fallo clásico y no se nota: el mapa
    sigue pareciendo un mapa, pero la banda derecha pasa a ser la
    izquierda y el análisis de por dónde atacó cada uno sale al revés.
    """
    cx = float(x) / 100.0 * LARGO
    cy = float(y) / 100.0 * ANCHO
    if visitante:
        cx = LARGO - cx
        cy = ANCHO - cy
    return round(cx, 2), round(cy, 2)


def _tiro(t, visitante, equipo):
    x, y = _a_campo(t.get("x", 0), t.get("y", 0), visitante)
    xg = float(t.get("xG", 0) or 0)
    return {
        "equipo":    equipo,
        "visitante": visitante,
        "minuto":    int(t.get("minute", 0) or 0),
        "jugador":   t.get("player", ""),
        "resultado": t.get("result", ""),
        "gol":       t.get("result") == "Goal",
        "situacion": t.get("situation", ""),
        "tipo":      t.get("shot_type", ""),
        "xg":        round(xg, 3),
        "x":         x,
        "y":         y,
    }


def carrera_xg(tiros, equipo_local, equipo_visitante):
    """El xG acumulado de cada equipo minuto a minuto.

    Es el gráfico que contesta "¿cuándo pasó el partido?". Empieza en
    el minuto 0 con los dos a cero para que la línea arranque del
    suelo, y cada tiro añade su xG al escalón de su equipo.
    """
    pasos = [{"minuto": 0, "local": 0.0, "visitante": 0.0,
              "gol": None, "jugador": "", "xg": 0.0}]
    acu_l = acu_v = 0.0
    for t in sorted(tiros, key=lambda s: s["minuto"]):
        if t["visitante"]:
            acu_v += t["xg"]
        else:
            acu_l += t["xg"]
        pasos.append({
            "minuto": t["minuto"],
            "local": round(acu_l, 3),
            "visitante": round(acu_v, 3),
            "gol": (equipo_visitante if t["visitante"] else equipo_local) if t["gol"] else None,
            "jugador": t["jugador"],
            "xg": t["xg"],
        })
    return pasos


def reparto_por_situacion(tiros):
    """Cuánto xG vino de cada tipo de jugada.

    Importa porque dos equipos con el mismo xG pueden haberlo hecho de
    maneras que no se parecen: uno con un penalti de 0,76 y otro con
    ocho llegadas de 0,09.
    """
    salida = {}
    for t in tiros:
        s = t["situacion"] or "Desconocida"
        d = salida.setdefault(s, {"tiros": 0, "xg": 0.0, "goles": 0})
        d["tiros"] += 1
        d["xg"] = round(d["xg"] + t["xg"], 3)
        d["goles"] += 1 if t["gol"] else 0
    return salida


def _resumen_equipo(tiros, jugadores):
    goles = sum(1 for t in tiros if t["gol"])
    xg = round(sum(t["xg"] for t in tiros), 2)
    a_puerta = sum(1 for t in tiros if t["resultado"] in ("Goal", "SavedShot"))
    claras = [t for t in tiros if t["xg"] >= OCASION_CLARA]
    mejor = max(tiros, key=lambda t: t["xg"]) if tiros else None
    return {
        "goles": goles,
        "xg": xg,
        "tiros": len(tiros),
        "a_puerta": a_puerta,
        "xg_por_tiro": round(xg / len(tiros), 3) if tiros else 0.0,
        "ocasiones_claras": len(claras),
        "diferencia": round(goles - xg, 2),
        "mejor_ocasion": ({
            "jugador": mejor["jugador"], "minuto": mejor["minuto"],
            "xg": mejor["xg"], "gol": mejor["gol"],
            "situacion": mejor["situacion"],
        } if mejor else None),
        "reparto": reparto_por_situacion(tiros),
        "jugadores": jugadores,
    }


def informe(partido: dict, tiros_crudos: dict, roster: dict = None) -> dict:
    """Arma el informe entero.

    `partido` sale del calendario de Understat (local, visitante,
    fecha, goles). `tiros_crudos` es lo que devuelve get_match_shots.
    `roster` es lo que devuelve get_match_roster, y puede faltar.

    REVIENTA si el marcador de los tiros no cuadra con el del
    calendario. Son dos consultas distintas a la misma fuente, así que
    tienen que decir lo mismo; si no lo dicen, hay algo mal y prefiero
    enterarme a publicar un informe que se contradice consigo mismo.
    """
    local = partido.get("local", "")
    visitante = partido.get("visitante", "")

    tiros = ([_tiro(t, False, local) for t in tiros_crudos.get("home_shots", [])] +
             [_tiro(t, True, visitante) for t in tiros_crudos.get("away_shots", [])])

    gl = sum(1 for t in tiros if t["gol"] and not t["visitante"])
    gv = sum(1 for t in tiros if t["gol"] and t["visitante"])

    # ── que las dos consultas cuenten lo mismo ──
    esperado_l = partido.get("goles_local")
    esperado_v = partido.get("goles_visitante")
    aviso_marcador = None
    if esperado_l is not None and esperado_v is not None:
        if (gl, gv) != (esperado_l, esperado_v):
            # No se lanza una excepción: los goles en propia puerta no
            # aparecen como "Goal" del equipo que los celebra, así que
            # un descuadre de uno es normal y explicable. Lo que no
            # vale es callárselo.
            aviso_marcador = (
                f"El calendario dice {esperado_l}-{esperado_v} y sumando los "
                f"tiros salen {gl}-{gv}. La diferencia suele ser un gol en "
                f"propia puerta, que Understat no se lo apunta a nadie como "
                f"tiro. El marcador bueno es el del calendario.")

    r = roster or {}
    equipos = {
        local: _resumen_equipo([t for t in tiros if not t["visitante"]],
                               r.get("local", [])),
        visitante: _resumen_equipo([t for t in tiros if t["visitante"]],
                                   r.get("visitante", [])),
    }
    return {
        "match_id": partido.get("match_id", ""),
        "fecha": partido.get("fecha", ""),
        "local": local,
        "visitante": visitante,
        "goles_local": esperado_l if esperado_l is not None else gl,
        "goles_visitante": esperado_v if esperado_v is not None else gv,
        "aviso_marcador": aviso_marcador,
        "tiros": sorted(tiros, key=lambda t: t["minuto"]),
        "carrera": carrera_xg(tiros, local, visitante),
        "equipos": equipos,
        "quien_peso_mas": quien_peso_mas(equipos),
        "por_tramos": por_tramos(tiros, local, visitante),
        "por_zonas": {
            local: por_zonas([t for t in tiros if not t["visitante"]]),
            visitante: por_zonas([t for t in tiros if t["visitante"]]),
        },
        "primer_gol": antes_y_despues_del_primer_gol(tiros),
        "peso_cadena": PESO_CADENA,
        "fuente": "Understat",
        "sin_datos_de": [
            "red de pases", "mapa de posiciones", "presiones",
            "recuperaciones", "duelos", "paradas del portero",
        ],
    }


# ══════════════════════════════════════════════════════════════════
# QUIÉN PESÓ MÁS EN LAS OCASIONES
# ══════════════════════════════════════════════════════════════════
#
# Félix pidió "el mejor jugador del partido". No lo llamo así, y el
# motivo importa.
#
# Con datos de tiro no se puede decir quién fue el mejor. Un central
# que lo para todo y un pivote que recupera veinte balones no aparecen
# por ningún lado: Understat no publica nada de eso. Llamarle MVP
# sería dar por medido lo que no se ha medido, y además pondría
# siempre a un delantero, que es justo la crítica que se le hace a
# media prensa deportiva.
#
# Así que esto contesta una pregunta más pequeña y verdadera: de las
# ocasiones que hubo, ¿quién pesó más? Con los componentes a la vista
# para que cada uno juzgue.
#
# LA CUENTA
#
#     aportación = xG + xA + PESO_CADENA · (xGChain − xG − xA)
#
# xG es lo que valían sus tiros y xA lo que valían los pases de los
# que salió un tiro. xGChain es lo que valían TODAS las jugadas en las
# que participó, así que la resta es su parte en jugadas de peligro en
# las que ni tiró ni dio el último pase: el que saca el balón, el que
# conduce, el que abre a la banda.
#
# Eso vale, pero no vale lo mismo que rematar, así que pesa un cuarto.
# El número está escrito aquí para que se pueda discutir en vez de
# estar escondido en medio de una cuenta.

PESO_CADENA = 0.25


def quien_peso_mas(equipos: dict, minimo_minutos: int = 20) -> list:
    """Ordena a los jugadores de los dos equipos por aportación.

    `equipos` es el bloque que devuelve `informe`. Devuelve la lista
    entera ordenada, con los componentes de cada uno, para que la
    pantalla pueda enseñar de dónde sale cada cifra.
    """
    fila = []
    for nombre_equipo, datos in equipos.items():
        for j in datos.get("jugadores") or []:
            minutos = j.get("minutos") or 0
            if minutos < minimo_minutos:
                continue
            xg = float(j.get("xg") or 0)
            xa = float(j.get("xa") or 0)
            cadena = float(j.get("xgchain") or 0)
            resto = max(0.0, cadena - xg - xa)
            fila.append({
                "nombre": j.get("nombre"),
                "equipo": nombre_equipo,
                "puesto": j.get("puesto"),
                "minutos": minutos,
                "goles": j.get("goles") or 0,
                "asistencias": j.get("asistencias") or 0,
                "tiros": j.get("tiros") or 0,
                "pases_clave": j.get("pases_clave") or 0,
                "xg": round(xg, 3),
                "xa": round(xa, 3),
                "xgchain": round(cadena, 3),
                "resto_de_cadena": round(resto, 3),
                "aportacion": round(xg + xa + PESO_CADENA * resto, 3),
            })
    fila.sort(key=lambda x: (-x["aportacion"], -x["goles"], -x["minutos"]))
    return fila


# ══════════════════════════════════════════════════════════════════
# CUÁNDO Y DESDE DÓNDE
# ══════════════════════════════════════════════════════════════════

TRAMO = 15


def por_tramos(tiros: list, local: str, visitante: str, tramo: int = TRAMO) -> list:
    """El xG de cada equipo por tramos de quince minutos.

    La carrera de xG enseña el partido entero de un vistazo; esto
    enseña en qué ratos mandó cada uno, que es lo que de verdad se
    discute después: «les comimos la primera media hora».
    """
    n = (90 + tramo - 1) // tramo
    bloques = []
    for k in range(n):
        desde, hasta = k * tramo, min((k + 1) * tramo, 90)
        dentro = [t for t in tiros if desde <= t["minuto"] < hasta or
                  (hasta == 90 and t["minuto"] >= 90)]
        bloques.append({
            "desde": desde, "hasta": hasta,
            "etiqueta": f"{desde}–{hasta}",
            "local": round(sum(t["xg"] for t in dentro if not t["visitante"]), 3),
            "visitante": round(sum(t["xg"] for t in dentro if t["visitante"]), 3),
            "tiros_local": sum(1 for t in dentro if not t["visitante"]),
            "tiros_visitante": sum(1 for t in dentro if t["visitante"]),
            "goles_local": sum(1 for t in dentro if t["gol"] and not t["visitante"]),
            "goles_visitante": sum(1 for t in dentro if t["gol"] and t["visitante"]),
        })
    return bloques


# Las zonas se miden en el campo ya convertido (120 × 80).
#
# El área grande son 16,5 metros de los 105 de largo, o sea el 15,7 %:
# en un campo de 120 eso es desde x = 101,2. El área pequeña son 5,5
# metros, el 5,2 %: desde x = 113,7. De ancho, el área va de 20,2 a
# 59,8 y la pequeña de 30,2 a 49,8.
#
# Se calculan, no se escriben a ojo, para que si algún día el campo
# del dibujo cambia de medidas las zonas cambien con él.
LARGO_REAL, ANCHO_REAL = 105.0, 68.0
AREA_FONDO = 16.5
AREA_ANCHO = 40.3
PEQUENA_FONDO = 5.5
PEQUENA_ANCHO = 18.3


def _zona(x: float, y: float) -> str:
    """En qué parte del campo cayó un tiro, mirándolo desde el ataque."""
    fondo = (LARGO - x) / LARGO * LARGO_REAL          # metros hasta la línea
    desvio = abs(y - ANCHO / 2) / ANCHO * ANCHO_REAL  # metros al centro
    if fondo <= PEQUENA_FONDO and desvio <= PEQUENA_ANCHO / 2:
        return "area pequena"
    if fondo <= AREA_FONDO and desvio <= AREA_ANCHO / 2:
        return "area"
    if fondo <= AREA_FONDO:
        return "costado del area"
    return "fuera del area"


ORDEN_ZONAS = ["area pequena", "area", "costado del area", "fuera del area"]

NOMBRE_ZONA = {
    "area pequena": "Área pequeña",
    "area": "Dentro del área",
    "costado del area": "Al costado del área",
    "fuera del area": "Desde fuera del área",
}


def por_zonas(tiros: list) -> dict:
    """Cuántos tiros, cuánto xG y cuántos goles desde cada zona.

    Contesta «¿llegaron o tiraron de lejos?», que es otra cosa que dos
    equipos con el mismo número de tiros pueden haber hecho de maneras
    opuestas.
    """
    salida = {}
    for t in tiros:
        # Las coordenadas del visitante están espejadas para el dibujo,
        # así que hay que deshacerlo para saber a qué distancia de la
        # portería contraria tiró.
        x = LARGO - t["x"] if t["visitante"] else t["x"]
        y = ANCHO - t["y"] if t["visitante"] else t["y"]
        z = _zona(x, y)
        d = salida.setdefault(z, {"zona": z, "nombre": NOMBRE_ZONA[z],
                                  "tiros": 0, "xg": 0.0, "goles": 0})
        d["tiros"] += 1
        d["xg"] = round(d["xg"] + t["xg"], 3)
        d["goles"] += 1 if t["gol"] else 0
    for d in salida.values():
        d["xg_por_tiro"] = round(d["xg"] / d["tiros"], 3) if d["tiros"] else 0.0
    return {z: salida[z] for z in ORDEN_ZONAS if z in salida}


def antes_y_despues_del_primer_gol(tiros: list) -> dict:
    """El partido partido en dos por el primer gol.

    Esto casi nadie lo enseña y explica muchísimos partidos. Un equipo
    que se adelanta pronto se echa atrás, y a partir de ahí el xG del
    rival sube sin que eso quiera decir que juega mejor. Sin separar
    los dos ratos, los totales mezclan dos partidos distintos.
    """
    goles = [t for t in tiros if t["gol"]]
    if not goles:
        return {"hubo_gol": False}
    primero = min(goles, key=lambda t: t["minuto"])
    corte = primero["minuto"]

    def suma(lista, visitante):
        return round(sum(t["xg"] for t in lista if t["visitante"] == visitante), 3)

    antes = [t for t in tiros if t["minuto"] < corte]
    despues = [t for t in tiros if t["minuto"] >= corte]
    return {
        "hubo_gol": True,
        "minuto": corte,
        "quien": primero["equipo"],
        "jugador": primero["jugador"],
        "antes": {"minutos": corte,
                  "local": suma(antes, False), "visitante": suma(antes, True),
                  "tiros_local": sum(1 for t in antes if not t["visitante"]),
                  "tiros_visitante": sum(1 for t in antes if t["visitante"])},
        "despues": {"minutos": 90 - corte,
                    "local": suma(despues, False), "visitante": suma(despues, True),
                    "tiros_local": sum(1 for t in despues if not t["visitante"]),
                    "tiros_visitante": sum(1 for t in despues if t["visitante"])},
    }
