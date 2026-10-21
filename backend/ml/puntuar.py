# -*- coding: utf-8 -*-
"""
LA PUNTUACIÓN DE SCOUTING
=========================
Convierte a cada jugador en un número del 0 al 100 que quiere decir
algo concreto: en qué percentil está dentro del grupo con el que se le
está comparando.

CÓMO SE CALCULA, PASO A PASO
----------------------------
  1. Cada métrica se pasa a POR 90 MINUTOS. Un total premia a quien más
     juega; lo que se busca es quién rinde mejor cuando está.
  2. Cada métrica por 90 se convierte a PERCENTIL dentro del grupo que
     se está mirando — los delanteros de esa liga que pasan el filtro
     de minutos. Percentil 80 = mejor que el 80 % de ese grupo.
  3. Los percentiles se promedian con el peso de cada métrica.

El resultado es comparable y comprobable: si a alguien le sale 86, se
puede ir métrica a métrica y ver de dónde sale.

LO QUE NO HACE, Y ANTES SÍ
--------------------------
  · No suma métricas con unidades distintas. Sumar goles con tiros con
    xGChain da un número que depende de la escala de cada una, no de lo
    bueno que sea el jugador.
  · No aplica bonus por edad. Understat no da la edad, y el código
    anterior ponía 25 por defecto: eso metía a TODOS en el tramo
    «≤26» y les multiplicaba por 1,02. Un ajuste por edad calculado
    sobre una edad inventada no es un ajuste, es un adorno.
  · No puntúa defensas ni porteros. Ver metricas.py.
"""
import numpy as np

# ══════════════════════════════════════════════════════════════════
# EL ENCOGIDO POR MINUTOS
# ══════════════════════════════════════════════════════════════════
#
# Dani Olmo salía con un 97,8 habiendo jugado 323 minutos. Tres
# partidos y medio. Un analista abre el Scouting, ve eso el primero de
# la lista, y cierra la pestaña: no es un hallazgo, es que no ha
# jugado lo bastante como para saberlo.
#
# Una tasa por 90 minutos con pocos minutos es casi toda ruido. El que
# mete dos en media hora va a 6 goles por 90; el que mete dos en
# novecientos minutos va a 0,2. El primero no es treinta veces mejor.
#
# Así que cada percentil se acerca al 50 —la media del grupo— en
# proporción a lo poco que ha jugado:
#
#     ajustado = (minutos · suyo + K · 50) / (minutos + K)
#
# Con K = 540 minutos, seis partidos. Alguien con 540 pesa la mitad él
# y la mitad la media; con 1.620 pesa el 75 % él. En octubre, con
# nueve jornadas, eso ordena la lista por quien lo ha demostrado y no
# por quien ha tenido una buena tarde.
#
# K está aquí escrito para que se pueda discutir, y la respuesta
# devuelve el percentil crudo al lado del ajustado: no se esconde
# nada, se ordena mejor.
K_MINUTOS = 540


def encoger(percentil: float, minutos: int, k: int = K_MINUTOS) -> float:
    """Acerca un percentil a 50 según lo poco que ha jugado."""
    minutos = max(0, int(minutos or 0))
    return round((minutos * percentil + k * 50.0) / (minutos + k), 1)


from backend.ml.metricas import (METRICAS_POR_PUESTO, MINIMO_PARA_PERCENTILES,
                                 PUESTOS_SIN_DATOS)

MINUTOS_PARA_POR_90 = 1.0     # evita dividir por cero


class PuestoSinDatos(Exception):
    """Con esta fuente no se puede puntuar ese puesto.

    No es un fallo ni un «todavía no»: es que los datos para hacerlo no
    existen en Understat. Lleva dentro la explicación que se enseña.
    """

    def __init__(self, puesto, motivo):
        self.puesto = puesto
        self.motivo = motivo
        super().__init__(motivo)


def por_90(jugador: dict, clave: str) -> float:
    """El valor de esa métrica por cada 90 minutos jugados."""
    minutos = float(jugador.get("time", 0) or 0)
    if minutos < MINUTOS_PARA_POR_90:
        return 0.0
    return float(jugador.get(clave, 0) or 0) * 90.0 / minutos


def faltan_metricas(jugadores: list, puesto: str) -> list:
    """Qué métricas del puesto no vienen en los datos.

    Se mira en los datos DE VERDAD, no en una lista escrita a mano: si
    mañana Understat añade o quita un campo, esto se entera solo.
    """
    ficha = METRICAS_POR_PUESTO.get(puesto)
    if not ficha or not jugadores:
        return []
    presentes = set()
    for j in jugadores:
        presentes |= set(j.keys())
    return [clave for clave, _, _, _ in ficha["metricas"]
            if clave not in presentes]


def _percentiles(valores: list) -> list:
    """De una lista de números a su percentil dentro de la lista.

    Con empates se usa el rango medio, que es lo correcto: si tres
    jugadores tienen cero asistencias, los tres tienen el mismo
    percentil y no uno 0, otro 5 y otro 10 según el orden de la lista.
    """
    n = len(valores)
    if n == 0:
        return []
    if n == 1:
        return [50.0]
    v = np.asarray(valores, dtype=float)
    orden = v.argsort()
    rangos = np.empty(n, dtype=float)
    rangos[orden] = np.arange(n, dtype=float)
    # rango medio para los empates
    for valor in np.unique(v):
        iguales = v == valor
        rangos[iguales] = rangos[iguales].mean()
    return (rangos / (n - 1) * 100.0).tolist()


def puntuar(jugadores: list, puesto: str) -> dict:
    """Puntúa un grupo de jugadores del mismo puesto.

    Cambia los diccionarios: añade `score` y `percentiles`. Devuelve un
    resumen con las métricas usadas y los avisos.

    Revienta con PuestoSinDatos si es un puesto que esta fuente no
    permite puntuar, y con ValueError si faltan métricas que deberían
    estar: callar un hueco es lo que hacía el código viejo.
    """
    puesto = (puesto or "").upper()[:2]

    if puesto in PUESTOS_SIN_DATOS:
        raise PuestoSinDatos(puesto, PUESTOS_SIN_DATOS[puesto])
    if puesto not in METRICAS_POR_PUESTO:
        raise PuestoSinDatos(
            puesto, f"«{puesto}» no es un puesto que esto sepa puntuar.")

    ficha = METRICAS_POR_PUESTO[puesto]
    if not jugadores:
        return {"puesto": puesto, "metricas": [], "avisos": [],
                "comparados": 0}

    faltan = faltan_metricas(jugadores, puesto)
    if faltan:
        raise ValueError(
            f"a los datos de {puesto} les faltan estas métricas: "
            f"{', '.join(faltan)}. No puntúo con ceros en su lugar, que "
            f"es lo que hacía la versión anterior.")

    avisos = []
    n = len(jugadores)
    if n < MINIMO_PARA_PERCENTILES:
        avisos.append(
            f"Sólo hay {n} jugadores en esta comparación. Un percentil "
            f"sobre {n} dice poco: estar en el 90 es ser el primero de "
            f"{n}, no ser mejor que el 90 % de nadie. Baja los minutos "
            f"mínimos o mira todas las ligas.")

    # percentil de cada métrica dentro del grupo
    columnas = {}
    for clave, etiqueta, peso, normalizar in ficha["metricas"]:
        valores = [por_90(j, clave) if normalizar
                   else float(j.get(clave, 0) or 0) for j in jugadores]
        columnas[clave] = {"valores": valores,
                           "percentiles": _percentiles(valores),
                           "etiqueta": etiqueta, "peso": peso}

    suma_pesos = sum(m[2] for m in ficha["metricas"])
    for i, j in enumerate(jugadores):
        minutos = int(j.get("time", 0) or 0)
        # Cada percentil se encoge ANTES de promediarlos. Encoger sólo
        # la nota final daría otra cosa: el promedio de los percentiles
        # encogidos y el encogido del promedio no coinciden cuando los
        # pesos no son iguales.
        crudos = {c: columnas[c]["percentiles"][i] for c in columnas}
        ajustados = {c: encoger(crudos[c], minutos) for c in columnas}

        total = sum(ajustados[c] * columnas[c]["peso"] for c in columnas)
        j["score"] = round(total / suma_pesos, 1)
        j["score_crudo"] = round(
            sum(crudos[c] * columnas[c]["peso"] for c in columnas)
            / suma_pesos, 1)
        j["minutos_para_el_ajuste"] = minutos
        j["k_minutos"] = K_MINUTOS
        j["percentiles"] = {
            columnas[c]["etiqueta"]: round(ajustados[c], 1) for c in columnas}
        j["percentiles_crudos"] = {
            columnas[c]["etiqueta"]: round(crudos[c], 1) for c in columnas}
        j["por_90"] = {
            columnas[c]["etiqueta"]: round(columnas[c]["valores"][i], 3)
            for c in columnas}
        # Sin edad no hay ajuste por edad, y se dice.
        j["ajustado_por_edad"] = False

    return {
        "puesto": puesto,
        "titulo": ficha["titulo"],
        "explica": ficha["explica"],
        "comparados": n,
        "metricas": [{"clave": c, "etiqueta": e, "peso": p}
                     for c, e, p, _ in ficha["metricas"]],
        "avisos": avisos,
        "k_minutos": K_MINUTOS,
        "metodo": ("percentil dentro de este grupo, por 90 minutos, "
                   "encogido hacia 50 según los minutos jugados y "
                   "promediado con los pesos de arriba"),
    }
