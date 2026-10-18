# -*- coding: utf-8 -*-
"""
EL SIMULADOR — fuerzas de equipo y 10.000 temporadas por delante
================================================================
Dado lo jugado hasta hoy, estima la fuerza de ataque y defensa de cada
equipo y simula los partidos que faltan diez mil veces. De ahí sale,
para cada equipo, el rango de posiciones en el que va a acabar.

De dónde viene esto
-------------------
Es el motor de la publicación "El Simulador" (jornada 8), traído aquí
tal cual. Allí los resultados se metían A MANO desde el acta oficial de
LaLiga. Aquí los trae football-data.org en una sola llamada, con lo que
la pantalla se actualiza sola y se acaba el copiar y pegar.

Lo que NO ha cambiado al traerlo: el modelo, LAMBDA, ESCALA_INCERT y la
semilla. Si alguien compara esta pantalla con el cartel de la jornada 8
y las cifras no cuadran, es porque hay más partidos jugados, no porque
el motor sea otro.

EL MODELO
---------
Goles de cada equipo en cada partido, Poisson independientes:

    log λ_local     = μ + ataque[local]  − defensa[visitante] + casa
    log λ_visitante = μ + ataque[visit]  − defensa[local]

Máxima verosimilitud con penalización L2 (ridge) sobre ataque y
defensa. La penalización no es un adorno: en la jornada 7 hay 42
parámetros (20 ataques, 20 defensas, ventaja de campo y media general)
contra 69 partidos jugados. Sin encoger, el modelo se cree a pies
juntillas que el que ha metido 31 goles mete 4,4 por partido el resto
del año.

DOS FUENTES DE INCERTIDUMBRE, NO UNA
------------------------------------
Al simular hay que tirar dos dados:

  1. El dado del partido. Aun sabiendo exactamente lo bueno que es cada
     equipo, el resultado de un partido concreto es aleatorio.
  2. El dado de la fuerza. No sabemos exactamente lo bueno que es cada
     equipo. Con 7 u 8 jornadas, las fuerzas estimadas traen un error
     de estimación grande.

La primera versión sólo tiraba el primero y le daba al líder con pleno
de victorias un 96,5 % de título. Mirando cuatro ligas, 14 equipos han
empezado ganando sus 7 primeros partidos y NUEVE acabaron campeones, no
trece y medio. Por eso cada simulación usa unas fuerzas distintas,
sacadas de la distribución de lo que los datos permiten creer
(aproximación de Laplace).

LO QUE EL MODELO NO SABE, Y ES MUCHO
------------------------------------
- No sabe quién es cada equipo: ni presupuesto, ni plantilla, ni lo que
  hizo el año pasado. Sólo lo jugado este año.
- No sabe de lesiones, ni de entrenadores, ni de Champions entre semana.
- No usa xG. Son resultados y nada más, y un modelo de goles es más
  ruidoso que uno de xG.

Es deliberado: la pregunta es qué se puede saber con la MISMA
información que tiene la clasificación.

POR QUÉ ESTO SE NIEGA A FUNCIONAR MÁS DE LO QUE FUNCIONA
---------------------------------------------------------
Un simulador que devuelve números pase lo que pase es un adorno. Este
revienta —y lo explica— cuando el calendario que le llega no cuadra o
cuando hay tan poco jugado que el resultado no diría nada. Antes de
simular comprueba que están los 380 partidos, que cada equipo recibe a
cada rival una vez y que nadie juega contra sí mismo. Si falla algo de
eso, no estima: avisa.
"""
import unicodedata
from datetime import date

import numpy as np

# ── Los números del modelo ───────────────────────────────────────────
# NO se tocan a mano. Salieron de validar.py, que los eligió por
# verosimilitud fuera de muestra en 58 temporadas de cuatro ligas.
# El primer LAMBDA que puse a ojo fue 1,8 y daba al líder un 99 % de
# título en la jornada 7; históricamente el líder de la jornada 7 gana
# 9 de cada 14 ligas.
LAMBDA = 7.0
ESCALA_INCERT = 0.45
N_SIM = 10000
SEMILLA = 7
MAX_GOLES = 12          # tope al simular: por encima es ruido numérico

# Cuántas simulaciones se calculan de golpe. Baja el pico de memoria
# sin cambiar ni un número: ver el comentario largo dentro de simular().
TROZO = 1000

# Mínimos para que simular signifique algo. Con una jornada jugada el
# modelo es un generador de números bonitos.
MIN_JORNADAS = 3
MIN_PARTIDOS_POR_EQUIPO = 2


class CalendarioIncompleto(Exception):
    """El calendario que ha llegado no cuadra, así que no se simula.

    NO significa que el modelo falle: significa que la fuente no ha
    dado la temporada entera y simular sobre un calendario a medias
    daría posiciones finales inventadas.
    """


class DemasiadoPronto(Exception):
    """Hay tan poco jugado que el resultado no diría nada."""


class DatosDesfasados(Exception):
    """Hay partidos cuya fecha ya pasó y siguen sin resultado.

    Esto no es un fallo del modelo: es que la fuente va con retraso. Y
    simular con la clasificación de hace dos jornadas da posiciones
    finales que parecen de hoy y no lo son, que es peor que no dar nada.

    Un partido APLAZADO no cuenta aquí: ése sí está pendiente de verdad.
    """


# ── Nombres ──────────────────────────────────────────────────────────
# football-data da "Club Atlético de Madrid"; en una tabla de 20 filas
# eso no cabe. Estos recortes son los mismos de la publicación.
_A_MANO = {
    "Club Atlético de Madrid": "Atlético",
    "Atlético Madrid": "Atlético",
    "Real Racing Club de Santander": "Racing",
    "RC Deportivo La Coruña": "Deportivo",
    "Real Betis Balompié": "Betis",
    "Deportivo Alavés": "Alavés",
    "RCD Espanyol de Barcelona": "Espanyol",
    "Rayo Vallecano de Madrid": "Rayo",
    "Real Sociedad de Fútbol": "Real Sociedad",
    "RC Celta de Vigo": "Celta",
    "Athletic Club": "Athletic",
    "Real Valladolid CF": "Valladolid",
    "Real Madrid CF": "Real Madrid",
    "FC Barcelona": "Barcelona",
    "Girona FC": "Girona",
    "Sevilla FC": "Sevilla",
    "Valencia CF": "Valencia",
    "Villarreal CF": "Villarreal",
    "Getafe CF": "Getafe",
    "CA Osasuna": "Osasuna",
    "Levante UD": "Levante",
    "Elche CF": "Elche",
    "RCD Mallorca": "Mallorca",
}
_SUFIJOS = ("CF", "FC", "RC", "RCD", "CD", "UD", "CA", "SD", "SAD", "CP",
            "AFC", "AC", "SS", "BSC", "SV", "VfL", "VfB", "TSG")


def corto(nombre: str) -> str:
    """Nombre de equipo para pintar: corto y sin las siglas.

    Al Atlético le quitas 'Club Atlético' y 'de Madrid' y te quedas sin
    equipo: por eso primero se mira la tabla a mano.
    """
    n = (nombre or "").strip()
    if n in _A_MANO:
        return _A_MANO[n]
    trozos = [t for t in n.split() if t not in _SUFIJOS]
    salida = " ".join(trozos).strip(" .")
    return salida or n


def _sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn").lower()


# ── La fuente ────────────────────────────────────────────────────────
def desde_football_data(crudos: list) -> list:
    """Pasa la respuesta de /competitions/{code}/matches a partidos.

    Un partido cuenta como jugado SÓLO si football-data dice FINISHED y
    trae los dos goles. Un partido en juego, aplazado o suspendido entra
    en el calendario sin resultado: es un partido que falta por jugar,
    no un 0-0.
    """
    fuera = []
    for m in crudos or []:
        casa = (m.get("homeTeam") or {}).get("name")
        visi = (m.get("awayTeam") or {}).get("name")
        if not casa or not visi:
            continue                      # sorteo sin equipos asignados
        completo = ((m.get("score") or {}).get("fullTime") or {})
        gl, gv = completo.get("home"), completo.get("away")
        estado = m.get("status") or "SCHEDULED"
        jugado = (estado == "FINISHED"
                  and gl is not None and gv is not None)
        fuera.append({
            "jornada": m.get("matchday"),
            "fecha": (m.get("utcDate") or "")[:10],
            "estado": estado,
            "local": casa,
            "visitante": visi,
            "gl": int(gl) if jugado else None,
            "gv": int(gv) if jugado else None,
        })
    return fuera


def equipos(ps: list) -> list:
    return sorted({p["local"] for p in ps} | {p["visitante"] for p in ps})


def jugados(ps: list, hasta: int = None) -> list:
    fuera = [p for p in ps if p["gl"] is not None]
    if hasta is not None:
        fuera = [p for p in fuera if (p["jornada"] or 0) <= hasta]
    return fuera


def ultima_jornada_jugada(ps: list) -> int:
    j = [p["jornada"] or 0 for p in ps if p["gl"] is not None]
    return max(j) if j else 0


def ultima_fecha_jugada(ps: list):
    f = [p["fecha"] for p in ps if p["gl"] is not None and p["fecha"]]
    return max(f) if f else None


def validar_calendario(ps: list) -> dict:
    """Comprueba que la temporada que ha llegado es una temporada entera.

    Devuelve un resumen del calendario. Revienta si no cuadra, y dice
    exactamente qué no cuadra: es la diferencia entre un simulador y un
    generador de números.
    """
    if not ps:
        raise CalendarioIncompleto("la fuente no ha dado ningún partido")

    eq = equipos(ps)
    n = len(eq)
    if n < 16:
        raise CalendarioIncompleto(
            f"sólo hay {n} equipos en el calendario; una liga tiene 18 o 20")

    esperados = n * (n - 1)
    if len(ps) != esperados:
        raise CalendarioIncompleto(
            f"{len(ps)} partidos en el calendario y con {n} equipos "
            f"deberían ser {esperados}: falta parte de la temporada")

    casa, parejas = {}, set()
    for p in ps:
        if p["local"] == p["visitante"]:
            raise CalendarioIncompleto(
                f"{p['local']} aparece jugando contra sí mismo")
        llave = (p["local"], p["visitante"])
        if llave in parejas:
            raise CalendarioIncompleto(
                f"{corto(p['local'])} v {corto(p['visitante'])} está dos veces")
        parejas.add(llave)
        casa[p["local"]] = casa.get(p["local"], 0) + 1

    descuadrados = {e: c for e, c in casa.items() if c != n - 1}
    if descuadrados or len(casa) != n:
        raise CalendarioIncompleto(
            "los partidos en casa no cuadran: cada equipo debería recibir "
            f"a {n - 1} rivales y no es así ({len(descuadrados)} equipos mal)")

    sin_jornada = sum(1 for p in ps if not p["jornada"])
    if sin_jornada:
        raise CalendarioIncompleto(
            f"{sin_jornada} partidos sin número de jornada")

    return {"equipos": n, "partidos": len(ps),
            "jugados": len(jugados(ps)),
            "jornada": ultima_jornada_jugada(ps),
            "ultima_fecha": ultima_fecha_jugada(ps)}


def exigir_bastante_jugado(ps: list) -> None:
    """Se niega a simular cuando hay tan poco jugado que no diría nada."""
    eq = equipos(ps)
    jug = jugados(ps)
    por_equipo = {e: 0 for e in eq}
    for p in jug:
        por_equipo[p["local"]] += 1
        por_equipo[p["visitante"]] += 1

    jornada = ultima_jornada_jugada(ps)
    menos = min(por_equipo.values()) if por_equipo else 0
    if jornada < MIN_JORNADAS or menos < MIN_PARTIDOS_POR_EQUIPO:
        raise DemasiadoPronto(
            f"con {jornada} jornada(s) jugada(s) y algún equipo con sólo "
            f"{menos} partido(s), simular no diría nada. Hacen falta al "
            f"menos {MIN_JORNADAS} jornadas y {MIN_PARTIDOS_POR_EQUIPO} "
            f"partidos por equipo.")
    if len(jug) >= len(ps):
        raise DemasiadoPronto(
            "la temporada está acabada: no queda nada que simular")


# Estados que significan "este partido no se ha jugado y no se sabe
# cuándo", así que su fecha vieja no es señal de que la fuente falle.
_EN_EL_AIRE = {"POSTPONED", "SUSPENDED", "CANCELLED", "CANCELED", "AWARDED"}

# Días de retraso que se toleran antes de negarse a simular. Un partido
# acaba y football-data lo actualiza en minutos; dos días de margen es
# generoso y aun así detecta una fuente parada.
DIAS_TOLERADOS = 2


def salud_datos(ps: list, hoy: str = None) -> dict:
    """Mira si la fuente está al día. Revienta si va muy atrasada.

    Devuelve el recuento de aplazados y de partidos vencidos sin
    resultado, más los días que lleva de retraso el más viejo.
    """
    hoy = hoy or date.today().isoformat()
    aplazados = [p for p in ps
                 if p["gl"] is None and p.get("estado") in _EN_EL_AIRE]
    vencidos = [p for p in ps
                if p["gl"] is None
                and p.get("estado") not in _EN_EL_AIRE
                and p["fecha"] and p["fecha"] < hoy]

    retraso = 0
    if vencidos:
        viejo = min(p["fecha"] for p in vencidos)
        retraso = (date.fromisoformat(hoy) - date.fromisoformat(viejo)).days

    salud = {
        "aplazados": len(aplazados),
        "vencidos_sin_resultado": len(vencidos),
        "dias_de_retraso": retraso,
        "aviso": None,
    }
    if retraso > DIAS_TOLERADOS:
        raise DatosDesfasados(
            f"{len(vencidos)} partidos se jugaron hace hasta {retraso} días "
            f"y la fuente sigue sin dar su resultado. Con la clasificación "
            f"atrasada, los rangos saldrían mal: mejor no dar ninguno.")
    if vencidos:
        salud["aviso"] = (
            f"{len(vencidos)} partido(s) de ayer o de hoy todavía sin "
            f"resultado en la fuente. La simulación va sin ellos.")
    return salud


def clasificacion(ps: list, hasta: int = None) -> list:
    """Tabla al uso: puntos, y desempate por diferencia de goles.

    OJO: el desempate de verdad en La Liga es el enfrentamiento directo,
    no la diferencia de goles. A estas alturas casi nadie se ha
    enfrentado dos veces, así que aquí se usa diferencia general y se
    dice. Para rangos de posición final no cambia nada material.
    """
    t = {e: {"equipo": e, "pj": 0, "g": 0, "e": 0, "p": 0,
             "gf": 0, "gc": 0, "pts": 0} for e in equipos(ps)}
    for p in jugados(ps, hasta):
        a, b, ga, gb = p["local"], p["visitante"], p["gl"], p["gv"]
        for x, y, gx, gy in ((a, b, ga, gb), (b, a, gb, ga)):
            t[x]["pj"] += 1
            t[x]["gf"] += gx
            t[x]["gc"] += gy
            if gx > gy:
                t[x]["g"] += 1
                t[x]["pts"] += 3
            elif gx == gy:
                t[x]["e"] += 1
                t[x]["pts"] += 1
            else:
                t[x]["p"] += 1
    filas = list(t.values())
    for f in filas:
        f["dg"] = f["gf"] - f["gc"]
    filas.sort(key=lambda f: (-f["pts"], -f["dg"], -f["gf"],
                              _sin_tildes(f["equipo"])))
    for i, f in enumerate(filas, 1):
        f["pos"] = i
    return filas


# ── El ajuste ────────────────────────────────────────────────────────
def ajustar(ps, hasta, eq=None, lam=LAMBDA):
    """(ataque, defensa, casa, mu) por máxima verosimilitud penalizada."""
    # scipy se carga AQUÍ y no al importar el módulo: son unos 40 MB
    # que sólo hacen falta cuando alguien abre el Simulador. Quien
    # entre a mirar un informe no los paga.
    from scipy.optimize import minimize

    eq = eq or equipos(ps)
    n = len(eq)
    idx = {e: i for i, e in enumerate(eq)}
    jug = jugados(ps, hasta)
    loc = np.array([idx[p["local"]] for p in jug])
    vis = np.array([idx[p["visitante"]] for p in jug])
    gl = np.array([p["gl"] for p in jug], float)
    gv = np.array([p["gv"] for p in jug], float)
    media = np.log(max((gl.sum() + gv.sum()) / (2 * len(gl)), 0.2))

    def neg_log_ver(t):
        at, de = t[:n], t[n:2 * n]
        casa, mu = t[2 * n], t[2 * n + 1]
        ll = mu + at[loc] - de[vis] + casa
        lv = mu + at[vis] - de[loc]
        # log-verosimilitud Poisson sin el log(y!), que es constante
        v = (np.exp(ll) - gl * ll).sum() + (np.exp(lv) - gv * lv).sum()
        return v + lam * (at @ at + de @ de)

    t0 = np.zeros(2 * n + 2)
    t0[2 * n] = 0.15
    t0[2 * n + 1] = media
    r = minimize(neg_log_ver, t0, method="L-BFGS-B",
                 options={"maxiter": 4000, "ftol": 1e-12})
    if not r.success and r.status != 1:
        raise RuntimeError(f"el ajuste no convergió: {r.message}")
    t = r.x
    return t[:n], t[n:2 * n], t[2 * n], t[2 * n + 1]


def _z(n, a, b, casa):
    """Derivada de log λ respecto a los parámetros.

    log λ = μ + ataque[a] − defensa[b] (+ casa si es local): la derivada
    es +1 en ataque[a], −1 en defensa[b], +1 en μ, y +1 en la ventaja de
    campo sólo para el local.
    """
    v = np.zeros(2 * n + 2)
    v[a] = 1.0
    v[n + b] = -1.0
    v[2 * n] = 1.0 if casa else 0.0
    v[2 * n + 1] = 1.0
    return v


def covarianza(ps, hasta, eq, at, de, casa, mu, lam=LAMBDA):
    """Cuánta incertidumbre hay en las fuerzas estimadas.

    Inversa de la curvatura (hessiana) de la verosimilitud penalizada en
    el óptimo. Para una Poisson con enlace logarítmico sale en cerrado:
    cada partido aporta λ·z·zᵀ y la penalización 2·lam en la diagonal.

    Cuantos más partidos, más curvatura y menos incertidumbre. Con 8
    jornadas la curvatura es poca y esta matriz es grande, que es justo
    lo que hay que reconocer.
    """
    n = len(eq)
    idx = {e: i for i, e in enumerate(eq)}
    H = np.zeros((2 * n + 2, 2 * n + 2))
    for p in jugados(ps, hasta):
        a, b = idx[p["local"]], idx[p["visitante"]]
        for x, y, en_casa in ((a, b, True), (b, a, False)):
            z = _z(n, x, y, en_casa)
            lmb = np.exp(mu + at[x] - de[y] + (casa if en_casa else 0.0))
            H += lmb * np.outer(z, z)
    H[np.arange(2 * n), np.arange(2 * n)] += 2 * lam
    # μ y la ventaja de campo no llevan penalización; un pelín de
    # regularización numérica para que la matriz sea invertible siempre
    H[2 * n, 2 * n] += 1e-6
    H[2 * n + 1, 2 * n + 1] += 1e-6
    return np.linalg.inv(H)


def simular(ps, hasta=None, n_sim=N_SIM, lam=LAMBDA, semilla=SEMILLA,
            escala=None):
    """Simula lo que queda y devuelve (equipos, posiciones, parametros).

    posiciones tiene forma (n_sim, n_equipos): en qué puesto acabó cada
    equipo en cada simulación.

    Los partidos ya jugados NO se simulan: sus puntos son los de verdad.
    Sólo se tira el dado sobre los que faltan.
    """
    hasta = ultima_jornada_jugada(ps) if hasta is None else hasta
    eq = equipos(ps)
    n = len(eq)
    idx = {e: i for i, e in enumerate(eq)}
    at, de, casa, mu = ajustar(ps, hasta, eq, lam)

    # Punto de partida real
    pts0 = np.zeros(n); gf0 = np.zeros(n); gc0 = np.zeros(n)
    for p in jugados(ps, hasta):
        a, b = idx[p["local"]], idx[p["visitante"]]
        gf0[a] += p["gl"]; gc0[a] += p["gv"]
        gf0[b] += p["gv"]; gc0[b] += p["gl"]
        pts0[a] += 3 if p["gl"] > p["gv"] else (1 if p["gl"] == p["gv"] else 0)
        pts0[b] += 3 if p["gv"] > p["gl"] else (1 if p["gl"] == p["gv"] else 0)

    jugados_llave = {(p["local"], p["visitante"]) for p in jugados(ps, hasta)}
    faltan = [p for p in ps
              if (p["local"], p["visitante"]) not in jugados_llave]
    if not faltan:
        raise DemasiadoPronto("no queda nada por jugar")
    fl = np.array([idx[p["local"]] for p in faltan])
    fv = np.array([idx[p["visitante"]] for p in faltan])

    rng = np.random.default_rng(semilla)

    # Un juego de fuerzas distinto por simulación: el segundo dado.
    esc = ESCALA_INCERT if escala is None else escala
    cov = covarianza(ps, hasta, eq, at, de, casa, mu, lam) * esc
    theta = np.concatenate([at, de, [casa, mu]])
    if esc > 0:
        muestras = rng.multivariate_normal(theta, cov, size=n_sim,
                                           method="cholesky")
    else:
        muestras = np.tile(theta, (n_sim, 1))     # sin el segundo dado
    s_at = muestras[:, :n]
    s_de = muestras[:, n:2 * n]
    s_casa = muestras[:, 2 * n][:, None]
    s_mu = muestras[:, 2 * n + 1][:, None]

    # ── POR TROZOS, Y EN EL ORDEN CORRECTO ──────────────────────
    #
    # Por qué trocear: hacerlo de una vez son seis matrices de
    # 10.000 × 311 en float64 e int64. Medido, el pico de memoria del
    # servidor subía de 169 a 368 MB sólo por esto. En un ordenador da
    # igual; en un servidor pequeño —medio giga, que es lo que dan los
    # planes básicos— eso es quedarse sin memoria con dos visitantes.
    #
    # POR QUÉ PRIMERO TODOS LOS LOCALES Y LUEGO TODOS LOS VISITANTES,
    # que es lo que parece de más y es lo único que importa:
    #
    # La primera versión troceada sacaba, por cada trozo, los goles
    # locales y los visitantes seguidos. Eso ALTERNA las dos tiradas en
    # el generador:
    #
    #     de una vez:  local(todos), visitante(todos)
    #     troceado:    local(1), visitante(1), local(2), visitante(2)…
    #
    # Son dos secuencias distintas del mismo generador, así que salían
    # otros números: comprobado, el 83 % de las posiciones cambiaba.
    # Haciendo primero la tirada local entera —por trozos— y después la
    # visitante entera, el generador consume exactamente lo mismo que
    # de una vez, y el resultado es idéntico hasta el último dígito.
    # Hay una prueba que lo compara.
    #
    # Los goles caben en int8 porque MAX_GOLES es 12: las dos matrices
    # enteras ocupan 3 MB cada una en vez de 25.
    n_faltan = len(faltan)
    gl = np.empty((n_sim, n_faltan), dtype=np.int8)
    gv = np.empty((n_sim, n_faltan), dtype=np.int8)

    for destino, equipo_local in ((gl, True), (gv, False)):
        for ini in range(0, n_sim, TROZO):
            fin = min(ini + TROZO, n_sim)
            if equipo_local:
                lam = np.exp(s_mu[ini:fin] + s_at[ini:fin][:, fl]
                             - s_de[ini:fin][:, fv] + s_casa[ini:fin])
            else:
                lam = np.exp(s_mu[ini:fin] + s_at[ini:fin][:, fv]
                             - s_de[ini:fin][:, fl])
            destino[ini:fin] = np.minimum(rng.poisson(lam), MAX_GOLES)
            del lam

    pts = np.tile(pts0, (n_sim, 1))
    gf = np.tile(gf0, (n_sim, 1))
    gc = np.tile(gc0, (n_sim, 1))
    pl = np.where(gl > gv, 3, np.where(gl == gv, 1, 0)).astype(np.int8)
    pv = np.where(gv > gl, 3, np.where(gl == gv, 1, 0)).astype(np.int8)
    for k in range(n_faltan):
        a, b = fl[k], fv[k]
        pts[:, a] += pl[:, k]; pts[:, b] += pv[:, k]
        gf[:, a] += gl[:, k]; gc[:, a] += gv[:, k]
        gf[:, b] += gv[:, k]; gc[:, b] += gl[:, k]
    del gl, gv, pl, pv

    # Ordenar: puntos, diferencia de goles, goles a favor. El empate
    # perfecto se rompe al azar, no por orden alfabético, que favorecería
    # siempre al mismo equipo.
    dg = gf - gc
    azar = rng.random((n_sim, n))
    clave = (-pts * 1e12) + (-dg * 1e8) + (-gf * 1e4) + azar
    orden = np.argsort(clave, axis=1, kind="stable")
    posiciones = np.empty((n_sim, n), int)
    filas = np.arange(n_sim)[:, None]
    posiciones[filas, orden] = np.arange(1, n + 1)[None, :]

    params = {"ataque": dict(zip(eq, at.round(4).tolist())),
              "defensa": dict(zip(eq, de.round(4).tolist())),
              "ventaja_campo": round(float(casa), 4),
              "mu": round(float(mu), 4)}
    return eq, posiciones, params


def _probabilidades_partido(at, de, casa, mu, ia, ib):
    """1X2 de un partido con las fuerzas ajustadas, sumando la rejilla
    de resultados posibles hasta MAX_GOLES."""
    ll = np.exp(mu + at[ia] - de[ib] + casa)
    lv = np.exp(mu + at[ib] - de[ia])
    k = np.arange(0, MAX_GOLES + 1)
    # Poisson en logaritmos: log p(k) = −λ + k·log λ − log k!
    # El log k! se acumula en vez de calcularse por factorial, que para
    # k grande se desborda.
    log_fact = np.concatenate([[0.0], np.cumsum(np.log(k[1:]))])

    def pois(lmb):
        return np.exp(-lmb + k * np.log(lmb) - log_fact)

    pl, pv = pois(ll), pois(lv)
    m = np.outer(pl, pv)
    m = m / m.sum()
    # Las tres casillas parten la matriz entera, así que suman 1. Al
    # redondear a cuatro decimales eso se rompe y la pantalla podía
    # mostrar 35 + 27 + 39 = 101. El resto del redondeo se le suma a la
    # casilla más grande, que es donde menos se nota.
    tres = [float(np.tril(m, -1).sum()),      # gana el local
            float(np.trace(m)),               # empate
            float(np.triu(m, 1).sum())]       # gana el visitante
    tres = [round(x, 4) for x in tres]
    mayor = max(range(3), key=lambda i: tres[i])
    tres[mayor] = round(tres[mayor] + (1.0 - sum(tres)), 4)
    return tres[0], tres[1], tres[2], float(ll), float(lv)


def proximos_partidos(ps, at, de, casa, mu, eq, cuantos=10):
    """El 1X2 de los próximos partidos, por fecha.

    POR FECHA Y NO POR JORNADA, y es a propósito. La primera versión
    cogía "la primera jornada que falte" y, con un partido de la jornada
    6 aplazado al 21 de octubre, la pantalla anunciaba "próxima jornada:
    la 6" con un solo partido. Lo que se quiere ver es lo que viene
    ahora, venga de la jornada que venga: cada partido lleva la suya.
    """
    idx = {e: i for i, e in enumerate(eq)}
    pendientes = [p for p in ps if p["gl"] is None and p["jornada"]]
    if not pendientes:
        return []
    fuera = []
    for p in sorted(pendientes, key=lambda x: (x["fecha"] or "9999",
                                               x["local"]))[:cuantos]:
        pl, px, pv, ll, lv = _probabilidades_partido(
            at, de, casa, mu, idx[p["local"]], idx[p["visitante"]])
        fuera.append({
            "fecha": p["fecha"], "jornada": p["jornada"],
            "aplazado": p.get("estado") in _EN_EL_AIRE,
            "local": corto(p["local"]), "visitante": corto(p["visitante"]),
            "p_local": pl, "p_empate": px, "p_visitante": pv,
            "goles_esperados_local": round(ll, 2),
            "goles_esperados_visitante": round(lv, 2),
        })
    return fuera


def resumen(eq, posiciones, ps, hasta=None):
    """Una fila por equipo: dónde está hoy y dónde va a acabar."""
    cl = {f["equipo"]: f for f in clasificacion(ps, hasta)}
    fuera = []
    for i, e in enumerate(eq):
        p = posiciones[:, i]
        f = cl[e]
        fuera.append({
            "equipo": e,
            "corto": corto(e),
            "pos_hoy": f["pos"], "pts_hoy": f["pts"], "pj": f["pj"],
            "gf": f["gf"], "gc": f["gc"], "dg": f["dg"],
            "media": round(float(p.mean()), 2),
            "p10": int(np.percentile(p, 10)),
            "p90": int(np.percentile(p, 90)),
            "mediana": int(np.median(p)),
            "p_titulo": round(float((p == 1).mean()), 4),
            "p_champions": round(float((p <= 4).mean()), 4),
            "p_descenso": round(float((p >= len(eq) - 2).mean()), 4),
            "dist": (np.bincount(p, minlength=len(eq) + 1)[1:]
                     / len(p)).round(4).tolist(),
        })
    return sorted(fuera, key=lambda f: f["pos_hoy"])


def edicion(crudos: list, competicion: str = "PD", nombre: str = "",
            hoy: str = None) -> dict:
    """Todo lo que la pantalla necesita, a partir de la respuesta cruda.

    Revienta con CalendarioIncompleto, DatosDesfasados o DemasiadoPronto
    si los datos no permiten simular honestamente. Eso es lo correcto:
    antes nada que un número inventado.

    `hoy` existe sólo para las pruebas, que trabajan con un fichero de
    resultados de una fecha fija. En producción se deja en None y se usa
    la fecha de verdad.
    """
    ps = desde_football_data(crudos)
    cal = validar_calendario(ps)
    salud = salud_datos(ps, hoy)
    exigir_bastante_jugado(ps)

    J = cal["jornada"]
    eq, pos, params = simular(ps, J)
    filas = resumen(eq, pos, ps, J)

    at = np.array([params["ataque"][e] for e in eq])
    de = np.array([params["defensa"][e] for e in eq])
    proximos = proximos_partidos(
        ps, at, de, params["ventaja_campo"], params["mu"], eq)

    anchos = [f["p90"] - f["p10"] + 1 for f in filas]
    return {
        "competicion": competicion,
        "nombre": nombre or competicion,
        "fuente": "football-data.org",
        "jornada": J,
        "ultima_fecha": cal["ultima_fecha"],
        "partidos_jugados": cal["jugados"],
        "partidos_calendario": cal["partidos"],
        "equipos": cal["equipos"],
        "calculado": date.today().isoformat(),
        "modelo": {"lambda": LAMBDA, "escala_incertidumbre": ESCALA_INCERT,
                   "simulaciones": N_SIM, "semilla": SEMILLA,
                   "max_goles": MAX_GOLES},
        "anchura_media_rango80": round(float(np.mean(anchos)), 1),
        "tabla": filas,
        "proximos": proximos,
        "salud": salud,
        "parametros": params,
    }
