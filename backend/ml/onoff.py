# -*- coding: utf-8 -*-
"""
CON ÉL Y SIN ÉL
===============
La respuesta a «¿cómo medimos a los defensas?» con los datos que de
verdad tenemos.

EL PROBLEMA
-----------
Understat publica tiros. De un central no hay entradas, ni
intercepciones, ni despejes, ni duelos: su ficha salía sin nota, con
un cartel diciendo que esta fuente no da para eso. Y las fuentes que
sí lo publican —FBref, WhoScored— son datos de Opta con licencia:
mirarlos es gratis, reproducirlos en una página propia no.

LA SALIDA
---------
No hace falta ver lo que hace el defensa para medir algo real. Basta
con saber cuándo estaba en el campo.

    · backend/ml/minutos.py reconstruye el tramo de cada jugador
    · cada tiro del rival tiene minuto y xG

Juntando las dos cosas sale cuánto xG encaja su equipo mientras él
juega, por 90 minutos. Y, lo que de verdad importa, cuánto encaja
cuando NO está. La diferencia entre las dos cifras es lo único que
empieza a parecerse a una medida de él y no de su equipo.

    con él    0,84 de xG encajado por 90
    sin él    1,46
    ───────────────
    diferencia  −0,62   (su equipo encaja 0,62 menos con él)

LO QUE ESTO NO ES
-----------------
No es una nota de defensa. Dicho sin rodeos:

  · mide al EQUIPO mientras él está, no a él. Un central malo en un
    equipo que defiende bien sale bien.
  · está lleno de ruido: quién más está en el campo, contra quién se
    juega, cómo va el marcador. Un equipo que gana 3-0 en el 60 se
    echa atrás y encaja más, y eso se le apunta a quien esté jugando.
  · con pocos minutos no dice nada. Por eso está el encogido.

Pero es un dato de verdad, calculado con datos de verdad, para los
once jugadores. Y eso es más de lo que había, que era nada.

EL ENCOGIDO
-----------
Un jugador con 180 minutos puede salir con un −1,8 espectacular
porque el rival no tiró en esos dos partidos. No es que defienda: es
que no ha jugado lo bastante como para saberlo.

Así que cada cifra se acerca a la media de su equipo en proporción a
lo poco que ha jugado:

    ajustado = (minutos · suyo + K · del equipo) / (minutos + K)

Con K = 450 minutos, cinco partidos. Un jugador con 450 minutos pesa
la mitad él y la mitad su equipo; con 1.800 pesa el 80 % él. Nadie con
dos partidos se cuela arriba, y el que lleva media temporada casi no
se mueve.

K está escrito aquí arriba a propósito, para que se pueda discutir en
vez de estar escondido en medio de una cuenta.
"""
from backend.ml.minutos import (
    MINUTOS_PARTIDO, NoSePuedeReconstruir, reparto_de_un_partido,
)

# Minutos a los que un jugador pesa la mitad él y la mitad su equipo.
K_ENCOGIDO = 450

# Por debajo de esto no se enseña cifra: se dice que no se sabe.
MINIMO_PARA_ENSENAR = 180


def por_90(valor: float, minutos: int) -> float:
    if not minutos:
        return 0.0
    return round(valor / minutos * 90, 3)


def encoger(tasa_suya: float, minutos: int, tasa_equipo: float,
            k: int = K_ENCOGIDO) -> float:
    """Acerca la tasa de un jugador a la de su equipo según lo que jugó."""
    if minutos <= 0:
        return round(tasa_equipo, 3)
    return round((minutos * tasa_suya + k * tasa_equipo) / (minutos + k), 3)


def acumular(partidos: list) -> dict:
    """Junta varios partidos de UN equipo en una cuenta por jugador.

    Cada partido es un diccionario con:
        jugadores      la alineación de ESE equipo
        tiros_favor    sus tiros, con minuto y xg
        tiros_contra   los del rival

    Los partidos cuyas cuentas no cuadran —una expulsión— se quedan
    fuera y se dicen. Un partido menos es mucho mejor que un partido
    inventado.
    """
    por_jugador = {}
    minutos_equipo = 0
    xg_favor_equipo = 0.0
    xg_contra_equipo = 0.0
    descartados = []
    dudosos = []

    for i, p in enumerate(partidos):
        try:
            reparto = reparto_de_un_partido(
                p.get("jugadores") or [],
                p.get("tiros_favor") or [],
                p.get("tiros_contra") or [])
        except NoSePuedeReconstruir as e:
            descartados.append({
                "partido": p.get("etiqueta") or f"partido {i + 1}",
                "motivo": e.motivo, "detalle": e.detalle})
            continue

        # Los minutos de este partido admitían más de una lectura y se
        # ha usado la media. Se dice cuáles son, porque es información
        # sobre la calidad del dato, no un detalle de implementación.
        if any(d.get("lectura_dudosa") for d in reparto.values()):
            baile = max(d.get("cuanto_baila", 0) for d in reparto.values())
            dudosos.append({
                "partido": p.get("etiqueta") or f"partido {i + 1}",
                "cuanto_baila": round(baile, 3)})

        minutos_equipo += MINUTOS_PARTIDO
        xg_favor_equipo += sum(float(t.get("xg", 0) or 0)
                               for t in (p.get("tiros_favor") or []))
        xg_contra_equipo += sum(float(t.get("xg", 0) or 0)
                                for t in (p.get("tiros_contra") or []))

        for pid, d in reparto.items():
            a = por_jugador.setdefault(pid, {
                "player_id": pid, "nombre": d["nombre"], "puesto": None,
                "puestos": {},
                "partidos": 0, "minutos": 0,
                "xg_favor_dentro": 0.0, "xg_contra_dentro": 0.0,
                "minutos_fuera": 0,
                "xg_favor_fuera": 0.0, "xg_contra_fuera": 0.0,
            })
            # El puesto se guarda contando, no quedándose con el del
            # primer partido. Si no, Koundé salía como "Sub" toda la
            # temporada porque el primero que vio el programa lo pilló
            # entrando desde el banquillo. "Sub" no es un puesto.
            if d["puesto"]:
                a["puestos"][d["puesto"]] = a["puestos"].get(d["puesto"], 0) + 1
            a["partidos"] += 1 if d["minutos_dentro"] else 0
            a["minutos"] += d["minutos_dentro"]
            a["minutos_fuera"] += d["minutos_fuera"]
            a["xg_favor_dentro"] += d["xg_favor_dentro"]
            a["xg_contra_dentro"] += d["xg_contra_dentro"]
            a["xg_favor_fuera"] += d["xg_favor_fuera"]
            a["xg_contra_fuera"] += d["xg_contra_fuera"]

    # Los minutos que un jugador NO estuvo tienen que contar también
    # los partidos enteros que se perdió, no sólo los que jugó a
    # medias. Si no, "sin él" sólo mira los ratos sueltos en que le
    # cambiaron, que es una muestra distinta y mucho más pequeña.
    for a in por_jugador.values():
        jugados = a["minutos"] + a["minutos_fuera"]
        faltan = minutos_equipo - jugados
        if faltan > 0:
            a["minutos_fuera"] += faltan
            # El xG de los partidos que se perdió entero no está en el
            # reparto, así que se saca del total del equipo.
            a["xg_favor_fuera"] = xg_favor_equipo - a["xg_favor_dentro"]
            a["xg_contra_fuera"] = xg_contra_equipo - a["xg_contra_dentro"]

    tasa_eq_f = por_90(xg_favor_equipo, minutos_equipo)
    tasa_eq_c = por_90(xg_contra_equipo, minutos_equipo)

    salida = []
    for a in por_jugador.values():
        reales = {k: v for k, v in a["puestos"].items() if k != "Sub"}
        a["puesto"] = (max(reales, key=reales.get) if reales
                       else (max(a["puestos"], key=a["puestos"].get)
                             if a["puestos"] else None))
        a["partidos_de_suplente"] = a["puestos"].get("Sub", 0)
        a.pop("puestos")
        f_dentro = por_90(a["xg_favor_dentro"], a["minutos"])
        c_dentro = por_90(a["xg_contra_dentro"], a["minutos"])
        f_fuera = por_90(a["xg_favor_fuera"], a["minutos_fuera"])
        c_fuera = por_90(a["xg_contra_fuera"], a["minutos_fuera"])

        f_aj = encoger(f_dentro, a["minutos"], tasa_eq_f)
        c_aj = encoger(c_dentro, a["minutos"], tasa_eq_c)

        salida.append({
            **a,
            "xg_favor_dentro": round(a["xg_favor_dentro"], 3),
            "xg_contra_dentro": round(a["xg_contra_dentro"], 3),
            "xg_favor_fuera": round(a["xg_favor_fuera"], 3),
            "xg_contra_fuera": round(a["xg_contra_fuera"], 3),
            "favor_90_con": f_dentro,
            "contra_90_con": c_dentro,
            "favor_90_sin": f_fuera if a["minutos_fuera"] else None,
            "contra_90_sin": c_fuera if a["minutos_fuera"] else None,
            "favor_90_ajustado": f_aj,
            "contra_90_ajustado": c_aj,
            # Negativo quiere decir que su equipo encaja menos con él.
            "diferencia_contra": (round(c_dentro - c_fuera, 3)
                                  if a["minutos_fuera"] else None),
            "diferencia_favor": (round(f_dentro - f_fuera, 3)
                                 if a["minutos_fuera"] else None),
            "fiable": a["minutos"] >= MINIMO_PARA_ENSENAR,
        })

    salida.sort(key=lambda x: x["contra_90_ajustado"])

    return {
        "jugadores": salida,
        "equipo": {
            "minutos": minutos_equipo,
            "partidos": minutos_equipo // MINUTOS_PARTIDO,
            "xg_favor": round(xg_favor_equipo, 2),
            "xg_contra": round(xg_contra_equipo, 2),
            "favor_90": tasa_eq_f,
            "contra_90": tasa_eq_c,
        },
        "descartados": descartados,
        "dudosos": dudosos,
        "k_encogido": K_ENCOGIDO,
        "minimo_para_ensenar": MINIMO_PARA_ENSENAR,
    }
