# -*- coding: utf-8 -*-
"""
STATSBOMB OPEN DATA
===================
Trae competiciones, partidos, eventos y alineaciones del repositorio
abierto de StatsBomb.

    github.com/statsbomb/open-data

POR QUÉ ESTA FUENTE Y NO LA DEL CUADERNO
-----------------------------------------
El cuaderno PostMatch original saca los eventos del HTML de WhoScored,
que por dentro lleva datos de Opta. Eso sirve para mirar un partido en
tu ordenador; no sirve para publicar. Los datos de Opta son de licencia
comercial y las condiciones de WhoScored prohíben extraerlos y
redistribuirlos.

StatsBomb Open Data es gratis, está publicado justo para esto y lo
único que pide es atribución: por eso «StatsBomb Open Data» sale en la
pantalla del informe, no escondido en un pie de página.

SIN CLAVE
---------
No hace falta ninguna clave ni registrarse. Son ficheros JSON servidos
por GitHub. Lo que sí hay es tamaño: el fichero de eventos de un
partido son entre 2 y 10 MB, así que no se pide dos veces.
"""
import asyncio
import logging

import httpx
from cachetools import TTLCache

from backend.errors import FuenteNoDisponible

logger = logging.getLogger(__name__)

BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"

# Un partido acabado no cambia nunca, así que lo que se guarda podría
# guardarse para siempre. El límite no es el tiempo, es la memoria:
# por eso se guardan POCAS cosas y se tiran las viejas.
#
# Y se guarda el INFORME ya calculado, no los eventos: 27 KB contra
# 3,7 MB. Los eventos se usan una vez y se sueltan.
_competiciones = TTLCache(maxsize=1, ttl=86400)
_partidos = TTLCache(maxsize=40, ttl=86400)
_informes = TTLCache(maxsize=12, ttl=86400)

# Un fichero de eventos grande tarda. 60 s es de sobra y evita que una
# petición se quede colgada para siempre.
ESPERA = 60.0


class PartidoNoEstaAbierto(Exception):
    """Ese partido no está en los datos abiertos de StatsBomb.

    No es un fallo: de los datos abiertos hay unos 3.500 partidos, no
    todos los del mundo.
    """

    def __init__(self, ruta=""):
        super().__init__(
            "ese partido no está en los datos abiertos de StatsBomb"
            + (f" ({ruta})" if ruta else ""))


async def _traer(ruta: str):
    """Un JSON del repositorio abierto, o una excepción que lo explica."""
    url = f"{BASE}/{ruta}"
    try:
        async with httpx.AsyncClient(timeout=ESPERA, follow_redirects=True) as c:
            r = await c.get(url)
    except Exception as e:
        raise FuenteNoDisponible(
            "StatsBomb", f"{type(e).__name__}: {e}") from e

    if r.status_code == 404:
        # Un 404 NO es que la fuente esté caída: es que ese partido no
        # está en los datos abiertos. Son cosas distintas y la pantalla
        # tiene que poder decirlo.
        raise PartidoNoEstaAbierto(ruta)
    if r.status_code != 200:
        raise FuenteNoDisponible("StatsBomb", f"HTTP {r.status_code} en {ruta}")
    try:
        return r.json()
    except Exception as e:
        raise FuenteNoDisponible(
            "StatsBomb", f"ha contestado algo que no es JSON: {e}") from e


async def competiciones() -> list:
    """Todas las competiciones y temporadas disponibles."""
    if "todas" in _competiciones:
        return _competiciones["todas"]
    datos = await _traer("competitions.json")
    _competiciones["todas"] = datos
    return datos


async def partidos(competition_id: int, season_id: int) -> list:
    """Los partidos de una competición y temporada."""
    llave = (competition_id, season_id)
    if llave in _partidos:
        return _partidos[llave]
    datos = await _traer(f"matches/{competition_id}/{season_id}.json")
    _partidos[llave] = datos
    return datos


async def eventos(match_id: int) -> list:
    """Los eventos de un partido. Entre 2 y 10 MB."""
    return await _traer(f"events/{match_id}.json")


async def alineaciones(match_id: int) -> list:
    """Las alineaciones: apodos, dorsales, tarjetas y minutos."""
    return await _traer(f"lineups/{match_id}.json")


async def ficha(match_id: int):
    """La ficha del partido (marcador oficial, competición, fecha).

    StatsBomb no tiene un fichero por partido: hay que buscarlo en las
    listas por competición. Se recorren las que ya están guardadas y,
    si no aparece, se devuelve None — el informe funciona igual, sólo
    que sin poder comprobar el marcador contra el oficial.

    Recorrer las ochenta listas por si acaso serían ochenta peticiones
    para un dato de adorno. No compensa.
    """
    for lista in list(_partidos.values()):
        for m in lista:
            if m.get("match_id") == match_id:
                return m
    return None


async def informe_de(match_id: int):
    """El informe ya calculado, guardado para no rehacerlo.

    Los eventos (megas) se piden, se usan y se sueltan; lo que se queda
    en memoria es el informe (kilobytes).
    """
    from backend.ml import informe as motor

    if match_id in _informes:
        return _informes[match_id]

    # Los dos ficheros a la vez: el de eventos es el que manda y el de
    # alineaciones llega mientras tanto.
    ev, al = await asyncio.gather(eventos(match_id), alineaciones(match_id))
    p = await ficha(match_id)

    resultado = await asyncio.to_thread(motor.informe, ev, p, al)
    resultado["match_id"] = match_id
    _informes[match_id] = resultado
    return resultado
