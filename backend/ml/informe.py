# -*- coding: utf-8 -*-
"""
EL INFORME POST-PARTIDO
=======================
Toma los eventos de un partido y saca el informe entero: red de pases,
mapa de tiros con su xG, la carrera de xG minuto a minuto, las
estadísticas de los dos equipos comparadas y quién hizo qué.

Es el trabajo del cuaderno PostMatch, traído aquí y cambiado de fuente.

POR QUÉ CAMBIA LA FUENTE, Y ESTO HAY QUE LEERLO
-----------------------------------------------
El cuaderno original lee el HTML guardado de WhoScored y le saca por
dentro el JSON de eventos, que es de Opta.

Eso vale para mirar un partido en tu ordenador. NO vale para publicarlo.
Los datos de Opta son de licencia comercial y las condiciones de uso de
WhoScored prohíben expresamente extraerlos y redistribuirlos. Montar una
página pública que sirva esos eventos a quien entre no es una zona gris:
es exactamente lo que no se puede hacer.

Así que lo que se publica va sobre StatsBomb Open Data, que es gratis,
está pensado justo para esto y sólo pide que se diga de dónde viene
(por eso la atribución sale en pantalla y no en letra pequeña). Son
~3.500 partidos reales: Mundiales, Eurocopas, 18 temporadas de La Liga,
Champions, el fútbol femenino entero.

El cuaderno de WhoScored sigue valiendo para el análisis propio, en
local. Esto es lo que se enseña.

EL SISTEMA DE COORDENADAS
-------------------------
StatsBomb: campo de 120 × 80, origen arriba a la izquierda, y SIEMPRE
con el equipo en posesión atacando hacia x = 120. No hay que girar nada
al cambiar de parte, que es la equivocación clásica.

LA TANDA DE PENALTIS NO ES EL PARTIDO
-------------------------------------
Los penaltis de la tanda vienen como eventos normales, en el periodo 5,
y cada uno trae xG 0,783. Si se cuentan:

  · el marcador de la final del Mundial 2022 sale 7-5 en vez de 3-3
  · el xG de Francia sube 1,57 de golpe, sin haber tirado a puerta

Por eso todo lo que se calcula aquí descarta el periodo 5, y hay una
comprobación que lo dice: los goles que salen de los eventos tienen que
cuadrar con el marcador oficial del partido.
"""
import math
from collections import defaultdict

LARGO = 120.0
ANCHO = 80.0
TANDA = 5                      # periodo de la tanda de penaltis

# Un enlace de la red de pases por debajo de esto es ruido: dos
# jugadores que se pasaron el balón una vez no son una sociedad.
MIN_PASES_ENLACE = 3


class PartidoIncompleto(Exception):
    """Los eventos que han llegado no sirven para hacer el informe.

    Como en el simulador: antes nada que un informe con huecos que
    parezca completo.
    """


# ── utilidades ───────────────────────────────────────────────────────
def _en_juego(eventos):
    """Todo menos la tanda de penaltis."""
    return [e for e in eventos if e.get("period") != TANDA]


def _nombre_corto(nombre, apodo=None):
    """'Lionel Andrés Messi Cuccittini' -> 'Messi'.

    EL APODO LO DA STATSBOMB, NO LO ADIVINO YO. El fichero de
    alineaciones trae `player_nickname` ya normalizado a nombre de pila
    más apellido: "Lionel Messi", "Ángel Di María", "Nicolás Otamendi".
    De ahí se quita el nombre de pila y queda lo que se pinta.

    La primera versión no usaba el apodo y se lo inventaba cogiendo el
    penúltimo trozo del nombre completo. Resultado en la final del
    Mundial: "Ángel Fabián Di María Hernández" salía como **María**,
    "Randal Kolo Muani" como **Kolo**, y "Nicolás Hernán Otamendi" como
    **Hernán**. Tres nombres mal de los once de la red. Con nombres
    españoles y franceses no hay regla que valga: hay que preguntarle
    al dato.

    Sin apodo (nombres ya cortos, "Marcus Thuram") se quita igualmente
    el nombre de pila y queda el apellido, que es lo que se quiere.
    """
    base = (apodo or nombre or "").strip()
    trozos = base.split()
    if len(trozos) <= 1:
        return base
    return " ".join(trozos[1:])


def apodos(alineaciones):
    """{id de jugador: apodo} a partir del fichero de alineaciones.

    Trae además el dorsal, que en una red de pases vale más que el
    nombre cuando dos apellidos se parecen.
    """
    fuera = {}
    for equipo in alineaciones or []:
        for j in equipo.get("lineup", []):
            fuera[j["player_id"]] = {
                "apodo": j.get("player_nickname") or j.get("player_name"),
                "dorsal": j.get("jersey_number"),
            }
    return fuera


def _equipos(eventos):
    """Local y visitante, en el orden en que StatsBomb los lista.

    El evento 'Starting XI' sale dos veces al principio: el primero es
    el local. Es la única forma de saberlo con los eventos solos.
    """
    once = [e for e in eventos if e["type"]["name"] == "Starting XI"]
    if len(once) != 2:
        raise PartidoIncompleto(
            f"hay {len(once)} alineaciones iniciales y deberían ser 2")
    return ([once[0]["team"]["name"], once[1]["team"]["name"]], once)


def _primer_cambio(eventos, equipo):
    """Minuto del primer cambio de ese equipo, o el final del partido.

    La red de pases se dibuja con el once inicial: en cuanto entra un
    suplente, la posición media deja de significar nada. El minuto se
    devuelve para poder decirlo en pantalla.
    """
    ms = [e["minute"] for e in eventos
          if e["type"]["name"] == "Substitution"
          and e["team"]["name"] == equipo]
    return min(ms) if ms else max((e["minute"] for e in eventos), default=90)


# ── marcador ─────────────────────────────────────────────────────────
def marcador(eventos):
    """Goles de cada equipo, sin la tanda y contando los goles en propia.

    Un gol en propia viene como 'Own Goal For' en el equipo que se lo
    apunta y 'Own Goal Against' en el que lo encaja. Se cuenta el
    primero: si se contaran los dos, cada gol en propia valdría doble.
    """
    eq, _ = _equipos(eventos)
    goles = {e: 0 for e in eq}
    for e in _en_juego(eventos):
        t = e["type"]["name"]
        if t == "Shot" and (e.get("shot", {}).get("outcome", {})
                            .get("name") == "Goal"):
            goles[e["team"]["name"]] += 1
        elif t == "Own Goal For":
            goles[e["team"]["name"]] += 1
    return goles


# ── red de pases ─────────────────────────────────────────────────────
def red_pases(eventos, equipo, nombres=None):
    """Posición media de cada titular y los pases entre ellos.

    Sólo pases COMPLETADOS y sólo mientras estuvo el once inicial. La
    posición media de un jugador se calcula con los sitios desde donde
    dio el pase y desde donde lo recibió: con sólo los que dio, un
    delantero que apenas toca el balón se va al centro del campo.
    """
    hasta = _primer_cambio(eventos, equipo)
    once = next((e for e in eventos if e["type"]["name"] == "Starting XI"
                 and e["team"]["name"] == equipo), None)
    if once is None:
        raise PartidoIncompleto(f"no hay alineación inicial de {equipo}")
    titulares = {p["player"]["id"]: p["player"]["name"]
                 for p in once["tactics"]["lineup"]}
    puesto = {p["player"]["id"]: p["position"]["name"]
              for p in once["tactics"]["lineup"]}

    sitios = defaultdict(list)
    enlaces = defaultdict(int)
    dados = defaultdict(int)

    for e in _en_juego(eventos):
        if (e["type"]["name"] != "Pass" or e["team"]["name"] != equipo
                or e["minute"] > hasta):
            continue
        p = e["pass"]
        if p.get("outcome"):           # con 'outcome' el pase NO llegó
            continue
        de = (e.get("player") or {}).get("id")
        a = (p.get("recipient") or {}).get("id")
        if de not in titulares or a not in titulares:
            continue
        sitios[de].append(e["location"])
        if p.get("end_location"):
            sitios[a].append(p["end_location"][:2])
        dados[de] += 1
        enlaces[tuple(sorted((de, a)))] += 1

    nombres = nombres or {}
    nodos = []
    for pid, nombre in titulares.items():
        ss = sitios.get(pid, [])
        if not ss:
            continue
        ficha = nombres.get(pid, {})
        nodos.append({
            "id": pid,
            "nombre": nombre,
            "corto": _nombre_corto(nombre, ficha.get("apodo")),
            "dorsal": ficha.get("dorsal"),
            "puesto": puesto.get(pid, ""),
            "x": round(sum(s[0] for s in ss) / len(ss), 2),
            "y": round(sum(s[1] for s in ss) / len(ss), 2),
            "pases": dados.get(pid, 0),
            "toques_en_la_red": len(ss),
        })
    nodos.sort(key=lambda n: -n["pases"])

    vivos = {n["id"] for n in nodos}
    lineas = [{"de": a, "a": b, "pases": n}
              for (a, b), n in enlaces.items()
              if n >= MIN_PASES_ENLACE and a in vivos and b in vivos]
    lineas.sort(key=lambda l: -l["pases"])

    return {
        "equipo": equipo,
        "formacion": str(once["tactics"]["formation"]),
        "hasta_minuto": hasta,
        "motivo_corte": ("primer cambio" if any(
            e["type"]["name"] == "Substitution" and e["team"]["name"] == equipo
            for e in eventos) else "final del partido"),
        "min_pases_enlace": MIN_PASES_ENLACE,
        "nodos": nodos,
        "enlaces": lineas,
    }


# ── tiros ────────────────────────────────────────────────────────────
def tiros(eventos, nombres=None):
    """Todos los tiros del partido, con su xG y dónde acabaron."""
    nombres = nombres or {}
    fuera = []
    for e in _en_juego(eventos):
        if e["type"]["name"] != "Shot":
            continue
        s = e["shot"]
        res = (s.get("outcome") or {}).get("name", "")
        j = e.get("player") or {}
        fuera.append({
            "equipo": e["team"]["name"],
            "jugador": j.get("name", ""),
            "corto": _nombre_corto(j.get("name", ""),
                                   nombres.get(j.get("id"), {}).get("apodo")),
            "minuto": e["minute"],
            "periodo": e["period"],
            "x": round(e["location"][0], 2),
            "y": round(e["location"][1], 2),
            "xg": round(float(s.get("statsbomb_xg") or 0.0), 4),
            "resultado": res,
            "gol": res == "Goal",
            "a_puerta": res in ("Goal", "Saved", "Saved To Post"),
            "tipo": (s.get("type") or {}).get("name", ""),
            "parte": (s.get("body_part") or {}).get("name", ""),
            "penalti": (s.get("type") or {}).get("name") == "Penalty",
        })
    return fuera


def carrera_xg(ts, eq):
    """El xG acumulado minuto a minuto, para pintar la carrera.

    Se añade un punto en el minuto 0 para que la línea arranque en
    cero, y otro al final para que no se corte en el último tiro.
    """
    fin = max([t["minuto"] for t in ts], default=90)
    fuera = {}
    for e in eq:
        acum, serie = 0.0, [{"minuto": 0, "xg": 0.0, "gol": False}]
        for t in sorted((t for t in ts if t["equipo"] == e),
                        key=lambda t: (t["minuto"], t["periodo"])):
            acum += t["xg"]
            serie.append({"minuto": t["minuto"], "xg": round(acum, 4),
                          "gol": t["gol"], "jugador": t["corto"]})
        serie.append({"minuto": fin, "xg": round(acum, 4), "gol": False})
        fuera[e] = serie
    return fuera


# ── estadísticas comparadas ──────────────────────────────────────────
def _dentro_del_area(x, y):
    """El área grande rival: de x=102 a 120, de y=18 a 62."""
    return x >= 102.0 and 18.0 <= y <= 62.0


def estadisticas(eventos, eq):
    """Las cifras de los dos equipos, todas sacadas de los eventos.

    La posesión se calcula POR PASES INTENTADOS, no por tiempo, y hay
    que decirlo: con eventos no hay cronómetro de balón, y repartir el
    tiempo entre posesiones da un número parecido pero inventado. Por
    pases es una medida real y comprobable, aunque no sea exactamente
    la que sale en televisión.
    """
    s = {e: defaultdict(float) for e in eq}
    for e in _en_juego(eventos):
        t = e["type"]["name"]
        nombre = e.get("team", {}).get("name")
        if nombre not in s:
            continue
        d = s[nombre]
        loc = e.get("location")
        if t == "Pass":
            p = e["pass"]
            d["pases"] += 1
            if not p.get("outcome"):
                d["pases_bien"] += 1
                fin = p.get("end_location")
                if loc and fin:
                    if loc[0] < 80.0 <= fin[0]:
                        d["entradas_ultimo_tercio"] += 1
                    if not _dentro_del_area(*loc[:2]) and _dentro_del_area(*fin[:2]):
                        d["pases_al_area"] += 1
                if p.get("cross"):
                    d["centros"] += 1
                    if not p.get("outcome"):
                        d["centros_bien"] += 1
            if p.get("shot_assist"):
                d["pases_clave"] += 1
            if p.get("goal_assist"):
                d["asistencias"] += 1
        elif t == "Shot":
            d["tiros"] += 1
            d["xg"] += float(e["shot"].get("statsbomb_xg") or 0.0)
            res = (e["shot"].get("outcome") or {}).get("name", "")
            if res in ("Goal", "Saved", "Saved To Post"):
                d["tiros_a_puerta"] += 1
        elif t == "Carry" and loc:
            if _dentro_del_area(*loc[:2]):
                d["toques_en_area"] += 1
        elif t == "Ball Receipt*" and loc and _dentro_del_area(*loc[:2]):
            d["toques_en_area"] += 1
        elif t in ("Interception", "Ball Recovery", "Clearance", "Block"):
            d["acciones_defensivas"] += 1
        elif t == "Pressure":
            d["presiones"] += 1
        elif t == "Foul Committed":
            d["faltas"] += 1
        elif t == "Duel":
            d["duelos"] += 1
            if (e.get("duel", {}).get("outcome", {})
                    .get("name", "")).startswith(("Won", "Success")):
                d["duelos_ganados"] += 1

    total_pases = sum(s[e]["pases"] for e in eq) or 1
    fuera = {}
    for e in eq:
        d = s[e]
        fuera[e] = {
            "posesion": round(100 * d["pases"] / total_pases, 1),
            "pases": int(d["pases"]),
            "pases_bien": int(d["pases_bien"]),
            "precision": round(100 * d["pases_bien"] / d["pases"], 1) if d["pases"] else 0.0,
            "tiros": int(d["tiros"]),
            "tiros_a_puerta": int(d["tiros_a_puerta"]),
            "xg": round(d["xg"], 3),
            "pases_clave": int(d["pases_clave"]),
            "asistencias": int(d["asistencias"]),
            "entradas_ultimo_tercio": int(d["entradas_ultimo_tercio"]),
            "pases_al_area": int(d["pases_al_area"]),
            "toques_en_area": int(d["toques_en_area"]),
            "centros": int(d["centros"]),
            "acciones_defensivas": int(d["acciones_defensivas"]),
            "presiones": int(d["presiones"]),
            "faltas": int(d["faltas"]),
            "duelos": int(d["duelos"]),
            "duelos_ganados": int(d["duelos_ganados"]),
        }
    return fuera


# ── quién hizo qué ───────────────────────────────────────────────────
def jugadores(eventos, eq, nombres=None):
    """Una fila por jugador con lo que se puede contar de los eventos."""
    d = defaultdict(lambda: defaultdict(float))
    quien = {}
    for e in _en_juego(eventos):
        j = e.get("player")
        if not j:
            continue
        pid = j["id"]
        quien[pid] = (j["name"], e.get("team", {}).get("name", ""))
        t = e["type"]["name"]
        x = d[pid]
        x["acciones"] += 1
        if t == "Pass":
            p = e["pass"]
            x["pases"] += 1
            if not p.get("outcome"):
                x["pases_bien"] += 1
                loc, fin = e.get("location"), p.get("end_location")
                # Pase progresivo: acerca el balón a la portería rival
                # al menos un 25 % de lo que quedaba. Es la definición
                # de uso común, y conviene decir cuál se usa porque hay
                # media docena distintas por ahí.
                if loc and fin and (120.0 - fin[0]) <= 0.75 * (120.0 - loc[0]) \
                        and fin[0] > loc[0] + 5:
                    x["pases_progresivos"] += 1
            if p.get("shot_assist"):
                x["pases_clave"] += 1
            if p.get("goal_assist"):
                x["asistencias"] += 1
        elif t == "Shot":
            x["tiros"] += 1
            x["xg"] += float(e["shot"].get("statsbomb_xg") or 0.0)
            if (e["shot"].get("outcome") or {}).get("name") == "Goal":
                x["goles"] += 1
        elif t in ("Interception", "Ball Recovery", "Clearance", "Block",
                   "Duel"):
            x["acciones_defensivas"] += 1
        elif t == "Dribble":
            x["regates"] += 1
            if (e.get("dribble", {}).get("outcome", {})
                    .get("name") == "Complete"):
                x["regates_bien"] += 1

    nombres = nombres or {}
    fuera = []
    for pid, v in d.items():
        nombre, equipo = quien[pid]
        ficha = nombres.get(pid, {})
        fuera.append({
            "id": pid, "nombre": nombre,
            "corto": _nombre_corto(nombre, ficha.get("apodo")),
            "dorsal": ficha.get("dorsal"),
            "equipo": equipo,
            "acciones": int(v["acciones"]),
            "pases": int(v["pases"]), "pases_bien": int(v["pases_bien"]),
            "pases_progresivos": int(v["pases_progresivos"]),
            "pases_clave": int(v["pases_clave"]),
            "asistencias": int(v["asistencias"]),
            "tiros": int(v["tiros"]), "goles": int(v["goles"]),
            "xg": round(v["xg"], 3),
            "acciones_defensivas": int(v["acciones_defensivas"]),
            "regates": int(v["regates"]), "regates_bien": int(v["regates_bien"]),
        })
    fuera.sort(key=lambda j: (-j["goles"], -j["xg"], -j["pases"]))
    return fuera


# ── el informe entero ────────────────────────────────────────────────
def informe(eventos, partido=None, alineaciones=None):
    """Todo lo que la pantalla necesita, y nada que no salga de los datos.

    `partido` es la ficha de StatsBomb (marcador oficial, competición,
    fecha). Si viene, se usa para COMPROBAR que los goles que salen de
    los eventos cuadran con el resultado oficial. Si no cuadran, esto
    revienta: un informe con el marcador mal no es un informe.

    `alineaciones` es el fichero de lineups, de donde salen los apodos
    y los dorsales. Sin él todo funciona, pero los nombres de la red
    salen con el nombre de pila quitado a pelo y algún apellido
    compuesto queda raro.
    """
    if not eventos:
        raise PartidoIncompleto("no han llegado eventos")
    eq, _ = _equipos(eventos)
    local, visitante = eq

    nombres = apodos(alineaciones)
    goles = marcador(eventos)
    ts = tiros(eventos, nombres)
    est = estadisticas(eventos, eq)
    js = jugadores(eventos, eq, nombres)

    aviso_marcador = None
    if partido:
        oficial = (partido.get("home_score"), partido.get("away_score"))
        salen = (goles[local], goles[visitante])
        if None not in oficial and tuple(oficial) != salen:
            raise PartidoIncompleto(
                f"los eventos dan {salen[0]}-{salen[1]} y el marcador "
                f"oficial es {oficial[0]}-{oficial[1]}. No publico un "
                f"informe cuyo resultado no cuadra con el del partido.")

    tanda = [e for e in eventos if e.get("period") == TANDA]
    if tanda:
        aviso_marcador = (
            "Hubo tanda de penaltis. No entra en ninguna cifra de este "
            "informe: ni en el marcador, ni en el xG, ni en los tiros.")

    minutos = max((e["minute"] for e in _en_juego(eventos)), default=90)
    return {
        "fuente": "StatsBomb Open Data",
        "atribucion": "Datos de StatsBomb (open data), usados con atribución.",
        "local": local, "visitante": visitante,
        "goles_local": goles[local], "goles_visitante": goles[visitante],
        "competicion": (partido or {}).get("competition", {}).get("competition_name", ""),
        "temporada": (partido or {}).get("season", {}).get("season_name", ""),
        "fase": (partido or {}).get("competition_stage", {}).get("name", ""),
        "fecha": (partido or {}).get("match_date", ""),
        "estadio": ((partido or {}).get("stadium") or {}).get("name", ""),
        "minutos": minutos,
        "aviso": aviso_marcador,
        "eventos": len(eventos),
        "estadisticas": est,
        "red": {local: red_pases(eventos, local, nombres),
                visitante: red_pases(eventos, visitante, nombres)},
        "tiros": ts,
        "carrera_xg": carrera_xg(ts, eq),
        "jugadores": js,
        "campo": {"largo": LARGO, "ancho": ANCHO},
    }
