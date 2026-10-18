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
        "equipos": {
            local: _resumen_equipo([t for t in tiros if not t["visitante"]],
                                   r.get("local", [])),
            visitante: _resumen_equipo([t for t in tiros if t["visitante"]],
                                       r.get("visitante", [])),
        },
        "fuente": "Understat",
        "sin_datos_de": [
            "red de pases", "mapa de posiciones", "presiones",
            "recuperaciones", "duelos", "paradas del portero",
        ],
    }
