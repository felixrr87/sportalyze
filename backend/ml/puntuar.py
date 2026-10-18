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
        total = sum(columnas[c]["percentiles"][i] * columnas[c]["peso"]
                    for c in columnas)
        j["score"] = round(total / suma_pesos, 1)
        j["percentiles"] = {
            columnas[c]["etiqueta"]: round(columnas[c]["percentiles"][i], 1)
            for c in columnas}
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
        "metodo": ("percentil dentro de este grupo, por 90 minutos, "
                   "promediado con los pesos de arriba"),
    }
