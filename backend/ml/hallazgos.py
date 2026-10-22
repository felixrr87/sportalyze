# -*- coding: utf-8 -*-
"""
LA MÁQUINA DE HALLAZGOS
=======================
Busca, entre todos los jugadores de las cinco grandes, a los que están
metiendo MÁS (o MENOS) goles de los que valen sus ocasiones, y se queda
sólo con aquellos en los que la diferencia es difícil de explicar por
azar.

EL PROBLEMA QUE RESUELVE, Y QUE CASI NADIE SE PLANTEA
──────────────────────────────────────────────────────
Si miras a 1.200 jugadores y te quedas con los que tienen p < 0,05,
te salen unos 60 "hallazgos" AUNQUE NO PASE NADA. Es aritmética: el
5 % de 1.200. Publicar esos 60 como descubrimientos es el fallo más
común del análisis deportivo con datos, y no se nota nunca, porque
cada uno por separado parece una historia estupenda.

Aquí se corrige con Benjamini-Hochberg, que no controla la
probabilidad de equivocarse en cada prueba sino la proporción de
falsos entre los que se publican (FDR). Con FDR = 0,10, de cada diez
nombres que salen se espera que uno sea casualidad. Y eso se dice en
pantalla, con el número.

EL MODELO NULO: UNA BINOMIAL, NO UNA POISSON
─────────────────────────────────────────────
La hipótesis es «este jugador convierte sus ocasiones al valor que les
da el modelo de xG». Sus tiros son monedas independientes, cada una
con su probabilidad. Esa suma es una Poisson-binomial, que no se puede
calcular sin el xG tiro a tiro.

Se usa una binomial con n = sus tiros y p = npxG / tiros. La media
sale EXACTA (n·p = npxG) y la varianza es la MAYOR posible para esa
media, porque Σp(1−p) se maximiza cuando todas las p son iguales. O
sea: la distribución más ancha compatible con el dato, que es la que
menos hallazgos produce. Cuando se duda, se duda a favor de no
publicar.

SIN PENALTIS
────────────
Se usan npg y npxG: goles y xG sin penaltis. Un penalti vale 0,76 de
xG y lo mete quien lo tira, no quien lo genera; contarlos convierte al
lanzador titular del equipo en un "hallazgo" todas las temporadas.

LO QUE ESTO NO DEMUESTRA, Y VA ESCRITO EN LA RESPUESTA
───────────────────────────────────────────────────────
Que un jugador supere a su xG no quiere decir que sea mejor rematador:
puede ser que el modelo de xG no vea algo de sus tiros (la posición
del portero, la presión, la altura del balón). Lo que dice es que, si
el modelo tuviera razón, lo suyo sería raro. Que es otra cosa, y es la
que se puede defender.
"""
from math import comb


# ── los números que se pueden discutir ──────────────────────────────

# Por debajo de esto no hay nada que medir: con 8 tiros, cualquier cosa
# cabe dentro del azar y lo único que se consigue es gastar una prueba
# de las que luego hay que corregir.
MINIMO_DE_TIROS = 15

# Y por debajo de estos minutos tampoco, aunque haya tirado mucho.
MINIMO_DE_MINUTOS = 450

# Benjamini-Hochberg: de cada diez nombres publicados, se espera que
# uno sea casualidad. Subirlo saca más nombres y más falsos; bajarlo,
# menos de los dos.
FDR = 0.10

# El p sin corregir con el que se compara, sólo para enseñar cuántos
# habrían salido haciéndolo mal.
P_INGENUO = 0.05


class NoSePuedeMedir(Exception):
    """Se lanza cuando a un jugador no se le puede aplicar la prueba."""

    def __init__(self, motivo: str, detalle: str = ""):
        super().__init__(detalle or motivo)
        self.motivo = motivo
        self.detalle = detalle


# ── la cola de la binomial ──────────────────────────────────────────

def cola_derecha(k: int, n: int, p: float) -> float:
    """P(X >= k) con X ~ Binomial(n, p). Exacta, sumando."""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    return sum(comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


def cola_izquierda(k: int, n: int, p: float) -> float:
    """P(X <= k) con X ~ Binomial(n, p). Exacta, sumando."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    return sum(comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(0, k + 1))


def p_de_un_jugador(goles: int, tiros: int, xg: float) -> float:
    """El p a dos colas de que sus goles salgan de su xG por azar.

    A dos colas y no a una, porque interesan los dos lados —quien mete
    de más y quien falla lo que debería meter— y porque elegir el lado
    DESPUÉS de ver el dato dobla los falsos positivos sin avisar.
    """
    if tiros <= 0:
        raise NoSePuedeMedir(
            "sin_tiros", "No ha tirado: no hay nada que comparar.")
    if xg <= 0:
        raise NoSePuedeMedir(
            "xg_cero",
            f"Tiene {tiros} tiros y la fuente les da 0 de xG entre todos. "
            f"Con eso cualquier gol sale imposible, y lo imposible no es "
            f"un hallazgo: es un dato que no me creo.")

    p = xg / tiros
    if p >= 1:
        raise NoSePuedeMedir(
            "xg_mayor_que_tiros",
            f"{xg} de xG en {tiros} tiros son más de 1 por tiro. "
            f"La fuente se contradice y no voy a inventarme cuál es "
            f"la buena.")

    una_cola = min(cola_derecha(goles, tiros, p),
                   cola_izquierda(goles, tiros, p))
    return min(1.0, 2.0 * una_cola)


# ── la corrección por mirar a mucha gente a la vez ──────────────────

def benjamini_hochberg(pes: list, fdr: float = FDR) -> dict:
    """Cuáles de estos p sobreviven controlando la proporción de falsos.

    Devuelve las POSICIONES de la lista que pasan, y el umbral que se
    ha acabado usando. El procedimiento: se ordenan los p de menor a
    mayor, se busca el mayor puesto i cuyo p_(i) <= (i/m)·fdr, y se
    aceptan ése y TODOS los anteriores — también los que por sí solos
    no cumplirían, que es la parte que la gente se salta.
    """
    m = len(pes)
    if not m:
        return {"pasan": [], "umbral": 0.0, "cuantos_probados": 0}

    orden = sorted(range(m), key=lambda i: pes[i])
    corte = 0
    umbral = 0.0
    for puesto, i in enumerate(orden, start=1):
        if pes[i] <= (puesto / m) * fdr:
            corte = puesto
            umbral = (puesto / m) * fdr

    return {
        "pasan": sorted(orden[:corte]),
        "umbral": round(umbral, 6),
        "cuantos_probados": m,
    }


# ── la máquina entera ───────────────────────────────────────────────

def buscar(jugadores: list, fdr: float = FDR,
           minimo_tiros: int = MINIMO_DE_TIROS,
           minimo_minutos: int = MINIMO_DE_MINUTOS) -> dict:
    """De una lista de jugadores de Understat, los que no cuadran.

    Cada jugador trae, como mínimo: name, team, league, time, shots,
    npg, npxG. Los que no se pueden medir salen en `descartados` con
    el motivo escrito, no desaparecen sin más.
    """
    candidatos, descartados = [], []

    for j in jugadores:
        nombre = j.get("name") or "?"
        minutos = int(j.get("time") or 0)
        tiros = int(j.get("shots") or 0)
        goles = int(j.get("npg") or 0)
        xg = float(j.get("npxG") or 0)

        if minutos < minimo_minutos:
            descartados.append({
                "name": nombre, "motivo": "pocos_minutos",
                "detalle": f"{minutos} minutos, hacen falta {minimo_minutos}"})
            continue
        if tiros < minimo_tiros:
            descartados.append({
                "name": nombre, "motivo": "pocos_tiros",
                "detalle": f"{tiros} tiros, hacen falta {minimo_tiros}"})
            continue
        if goles > tiros:
            descartados.append({
                "name": nombre, "motivo": "mas_goles_que_tiros",
                "detalle": f"{goles} goles sin penalti con {tiros} tiros. "
                           f"La fuente se contradice."})
            continue

        try:
            p = p_de_un_jugador(goles, tiros, xg)
        except NoSePuedeMedir as e:
            descartados.append({"name": nombre, "motivo": e.motivo,
                                "detalle": e.detalle})
            continue

        candidatos.append({
            "player_id": j.get("player_id"), "name": nombre,
            "team": j.get("team"), "league": j.get("league"),
            "position": j.get("position"),
            "minutos": minutos, "tiros": tiros,
            "goles_sin_penalti": goles,
            "npxg": round(xg, 2),
            "diferencia": round(goles - xg, 2),
            "xg_por_tiro": round(xg / tiros, 4),
            "p": round(p, 6),
            "direccion": "mete de más" if goles > xg else (
                "mete de menos" if goles < xg else "clava su xG"),
        })

    pes = [c["p"] for c in candidatos]
    bh = benjamini_hochberg(pes, fdr)
    pasan = set(bh["pasan"])

    hallados = []
    for i, c in enumerate(candidatos):
        if i in pasan:
            c = dict(c)
            c["umbral_que_pasa"] = bh["umbral"]
            hallados.append(c)
    hallados.sort(key=lambda c: (c["p"], -abs(c["diferencia"])))

    ingenuos = sum(1 for p in pes if p < P_INGENUO)

    return {
        "hallazgos": hallados,
        "cuantos_probados": len(candidatos),
        "cuantos_descartados": len(descartados),
        "descartados": descartados,
        "fdr": fdr,
        "umbral_bh": bh["umbral"],
        # Las dos cifras que son el argumento entero de esta pantalla.
        "pasarian_sin_corregir": ingenuos,
        "esperados_por_puro_azar": round(P_INGENUO * len(candidatos), 1),
        "falsos_esperados_entre_los_publicados": round(fdr * len(hallados), 1),
        "minimo_de_tiros": minimo_tiros,
        "minimo_de_minutos": minimo_minutos,
        "sin_penaltis": True,
    }
