# -*- coding: utf-8 -*-
"""
PRUEBAS DEL TURNERO Y DE LAS PETICIONES QUE NO SE REPITEN
=========================================================
    python3 -m pytest tests/test_turnero.py -v

Sin red. Lo que se comprueba aquí es lo que decide si Sportalyze
aguanta estar abierto a la gente o no.

EL PROBLEMA, EN UNA FRASE
-------------------------
Las diez peticiones por minuto de football-data son DEL PLAN, no de
cada visitante. Con una persona no se nota. Con un enlace compartido,
cinco personas pinchando equipos a la vez se las comen y todas ven un
error.

LAS DOS COSAS QUE LO ARREGLAN
-----------------------------
  · El turno: nunca salen más de nueve peticiones en sesenta segundos.
    Quien llega de más espera un par de segundos en vez de recibir un
    429.
  · Un viaje por petición: si cinco visitantes piden lo mismo a la vez,
    sale UNA y las cinco esperan a esa.

La segunda ahorra más que la primera, porque todo el mundo mira las
mismas ligas. Las dos juntas son la diferencia entre una página que
aguanta y una que se cae en cuanto la compartes.
"""
import asyncio
import os
import sys
import time

import pytest

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(AQUI))

from backend.scrapers import football_data as fd     # noqa: E402


# ════════════════════════════════════════════════════════════════
# EL TURNO
# ════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_por_debajo_del_limite_no_se_espera():
    t = fd.Turnero(cuantas=5, ventana=60.0)
    ini = time.monotonic()
    for _ in range(5):
        await t.turno()
    assert time.monotonic() - ini < 0.2


@pytest.mark.asyncio
async def test_pasado_el_limite_se_espera_lo_justo():
    """Con ventana de medio segundo, la cuarta tiene que esperar a que
    caduque la primera. Ni más ni menos."""
    t = fd.Turnero(cuantas=3, ventana=0.5)
    for _ in range(3):
        await t.turno()
    ini = time.monotonic()
    await t.turno()
    esperado = time.monotonic() - ini
    assert 0.3 < esperado < 1.2, esperado


@pytest.mark.asyncio
async def test_si_la_cola_es_absurda_se_dice_en_vez_de_colgar():
    """Veinte segundos mirando una ruedecita no es esperar, es pensar
    que la página está rota."""
    t = fd.Turnero(cuantas=1, ventana=600.0)
    await t.turno()
    with pytest.raises(fd.LimiteAlcanzado) as e:
        await t.turno()
    assert "cola" in str(e.value)
    # y el mensaje tiene que decir qué SÍ se puede mirar mientras tanto
    assert "informe" in str(e.value).lower()


@pytest.mark.asyncio
async def test_la_espera_estimada_no_pide_turno():
    """Preguntar cuánto falta no puede gastar una petición."""
    t = fd.Turnero(cuantas=2, ventana=60.0)
    await t.turno()
    await t.turno()
    assert t.espera_estimada() > 50
    assert t.espera_estimada() > 50        # preguntar dos veces no cambia nada
    assert len(t._salidas) == 2


@pytest.mark.asyncio
async def test_la_ventana_se_vacia_sola():
    t = fd.Turnero(cuantas=2, ventana=0.3)
    await t.turno()
    await t.turno()
    assert t.espera_estimada() > 0
    await asyncio.sleep(0.35)
    assert t.espera_estimada() == 0.0


def test_el_limite_deja_margen():
    """Nueve y no diez: el contador de football-data va por su reloj,
    no por el nuestro. Si alguien lo sube a diez, que sea a sabiendas."""
    assert fd.PETICIONES_POR_MINUTO == 9
    assert fd.VENTANA == 60.0


# ════════════════════════════════════════════════════════════════
# UN VIAJE POR PETICIÓN
# ════════════════════════════════════════════════════════════════

class _Respuesta:
    def __init__(self, datos):
        self._datos = datos
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._datos


class _ClienteFalso:
    """Sustituye a httpx.AsyncClient y cuenta cuántos viajes se hacen."""

    viajes = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None):
        _ClienteFalso.viajes.append(url)
        await asyncio.sleep(0.05)          # como si tardara la red
        return _Respuesta({"url": url, "n": len(_ClienteFalso.viajes)})


@pytest.fixture
def limpio(monkeypatch):
    """Caché, turnero y peticiones en vuelo, a cero.

    Con una clave de pega: sin clave el cliente se niega a salir antes
    de nada —que es lo correcto— y aquí lo que se está probando es el
    turno, no la clave.
    """
    fd._caches.clear()
    fd._en_vuelo.clear()
    fd._turnero = fd.Turnero()
    _ClienteFalso.viajes = []
    monkeypatch.setattr(fd, "FOOTBALL_API_KEY", "clave-de-pega")
    monkeypatch.setattr(fd.httpx, "AsyncClient", _ClienteFalso)
    return fd.FootballDataClient()


@pytest.mark.asyncio
async def test_cinco_visitantes_a_la_vez_son_un_solo_viaje(limpio):
    """ESTA es la prueba que decide si se puede compartir el enlace.

    Cinco personas abren la clasificación de La Liga en el mismo
    segundo. La caché está vacía para las cinco. Sin esto, salen cinco
    peticiones y se van media docena de turnos en una sola pantalla.
    """
    r = await asyncio.gather(*[
        limpio._get("/competitions/PD/standings") for _ in range(5)])
    assert len(_ClienteFalso.viajes) == 1, _ClienteFalso.viajes
    # y las cinco reciben lo mismo, no cuatro None
    assert all(x == r[0] for x in r)
    assert r[0]["url"].endswith("/competitions/PD/standings")


@pytest.mark.asyncio
async def test_cosas_distintas_si_son_viajes_distintos(limpio):
    await asyncio.gather(
        limpio._get("/competitions/PD/standings"),
        limpio._get("/competitions/PL/standings"),
        limpio._get("/competitions/SA/standings"))
    assert len(_ClienteFalso.viajes) == 3


@pytest.mark.asyncio
async def test_la_segunda_vez_sale_de_la_cache(limpio):
    await limpio._get("/competitions/PD/standings")
    await limpio._get("/competitions/PD/standings")
    assert len(_ClienteFalso.viajes) == 1


@pytest.mark.asyncio
async def test_la_cache_se_mira_otra_vez_despues_del_turno(monkeypatch, limpio):
    """Mientras una petición espera su turno, la respuesta puede llegar
    por otro lado. Si al salir del turno no se vuelve a mirar, se gasta
    un viaje en algo que ya está."""
    fd._turnero = fd.Turnero(cuantas=1, ventana=0.4)
    caja = fd._caja("/competitions/PD/standings")

    async def meter_en_cache():
        await asyncio.sleep(0.1)
        caja["/competitions/PD/standings"] = {"puesto": "por otro lado"}

    # la primera gasta el único turno
    await limpio._get("/competitions/SA/standings")
    assert len(_ClienteFalso.viajes) == 1

    r, _ = await asyncio.gather(
        limpio._get("/competitions/PD/standings"), meter_en_cache())
    assert r == {"puesto": "por otro lado"}
    assert len(_ClienteFalso.viajes) == 1, "ha salido un viaje de más"


@pytest.mark.asyncio
async def test_si_una_peticion_falla_no_se_queda_atascada(limpio, monkeypatch):
    """Una petición rota no puede dejar el endpoint bloqueado para
    siempre: el siguiente que pregunte tiene que poder intentarlo."""
    class Rota(_ClienteFalso):
        async def get(self, url, headers=None):
            _ClienteFalso.viajes.append(url)
            raise RuntimeError("se ha caído la red")

    monkeypatch.setattr(fd.httpx, "AsyncClient", Rota)
    with pytest.raises(Exception):
        await limpio._get("/competitions/PD/standings")
    assert "/competitions/PD/standings" not in fd._en_vuelo

    monkeypatch.setattr(fd.httpx, "AsyncClient", _ClienteFalso)
    r = await limpio._get("/competitions/PD/standings")
    assert r["url"].endswith("/competitions/PD/standings")


@pytest.mark.asyncio
async def test_una_pantalla_de_equipo_gasta_dos_turnos_y_no_mas(limpio):
    """Abrir un equipo son dos llamadas: su ficha y sus partidos. Si
    diez visitantes abren el MISMO equipo a la vez, siguen siendo dos.
    """
    async def abrir():
        await asyncio.gather(limpio._get("/teams/86"),
                             limpio._get("/teams/86/matches"))
    await asyncio.gather(*[abrir() for _ in range(10)])
    assert len(_ClienteFalso.viajes) == 2, _ClienteFalso.viajes


# ════════════════════════════════════════════════════════════════
# CALENTAR LA CACHÉ
# ════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_calentar_cede_el_paso_a_los_visitantes(monkeypatch):
    """Calentar es un lujo. Si hay alguien esperando turno, se para.

    Sin esto, arrancar el servidor se comería los primeros turnos del
    minuto y el primer visitante de verdad esperaría POR CULPA del
    calentamiento, que es justo lo contrario de para lo que está.
    """
    import main

    monkeypatch.setattr("backend.config.FOOTBALL_API_KEY", "una-clave")
    monkeypatch.setattr(main, "ESPERA_INICIAL", 0.0)
    monkeypatch.setattr(main, "CADA_CUANTO", 0.0)

    pedidas = []

    async def falsa(codigo):
        pedidas.append(codigo)
        return {"table": []}

    monkeypatch.setattr(main.football_client, "get_standings", falsa)

    # turnero lleno: hay cola desde el primer momento
    fd._turnero = fd.Turnero(cuantas=1, ventana=60.0)
    await fd._turnero.turno()

    await main.calentar()
    assert pedidas == [], f"ha calentado habiendo cola: {pedidas}"


@pytest.mark.asyncio
async def test_calentar_las_ligas_cuando_no_hay_nadie(monkeypatch):
    import main
    monkeypatch.setattr("backend.config.FOOTBALL_API_KEY", "una-clave")
    monkeypatch.setattr(main, "ESPERA_INICIAL", 0.0)
    monkeypatch.setattr(main, "CADA_CUANTO", 0.0)
    pedidas = []

    async def falsa(codigo):
        pedidas.append(codigo)
        return {"table": []}

    monkeypatch.setattr(main.football_client, "get_standings", falsa)
    fd._turnero = fd.Turnero()
    await main.calentar()
    assert pedidas == list(main.LIGAS_QUE_SE_CALIENTAN)


@pytest.mark.asyncio
async def test_calentar_no_tira_el_servidor_si_falla(monkeypatch):
    """Una liga que falle no puede impedir que el servidor arranque ni
    que se calienten las demás."""
    import main
    monkeypatch.setattr("backend.config.FOOTBALL_API_KEY", "una-clave")
    monkeypatch.setattr(main, "ESPERA_INICIAL", 0.0)
    monkeypatch.setattr(main, "CADA_CUANTO", 0.0)
    pedidas = []

    async def falsa(codigo):
        pedidas.append(codigo)
        if codigo == "PL":
            raise RuntimeError("esta liga ha fallado")
        return {"table": []}

    monkeypatch.setattr(main.football_client, "get_standings", falsa)
    fd._turnero = fd.Turnero()
    await main.calentar()                    # no revienta
    assert len(pedidas) == len(main.LIGAS_QUE_SE_CALIENTAN)


@pytest.mark.asyncio
async def test_sin_clave_no_se_calienta_nada(monkeypatch):
    import main
    monkeypatch.setattr("backend.config.FOOTBALL_API_KEY", "")
    monkeypatch.setattr(main, "ESPERA_INICIAL", 0.0)
    pedidas = []

    async def falsa(codigo):
        pedidas.append(codigo)
        return {}

    monkeypatch.setattr(main.football_client, "get_standings", falsa)
    await main.calentar()
    assert pedidas == []


@pytest.mark.asyncio
async def test_health_dice_cuanta_cola_hay(monkeypatch):
    """Para poder mirar desde fuera si la página está saturada sin
    tener que entrar a probarla."""
    from fastapi.testclient import TestClient
    import main
    fd._turnero = fd.Turnero(cuantas=1, ventana=60.0)
    cli = TestClient(main.app)
    assert cli.get("/health").json()["espera_football_data"] == 0.0
    await fd._turnero.turno()
    assert cli.get("/health").json()["espera_football_data"] > 50


@pytest.mark.asyncio
async def test_sin_clave_se_dice_que_falta_la_clave(monkeypatch, limpio):
    """El fallo más probable al subir esto a un servidor: desplegar y
    olvidar la variable de entorno. Antes salía «403 Forbidden», que es
    verdad y no sirve: parece que la fuente ha dicho que no cuando lo
    que pasa es que no se le ha preguntado con credenciales."""
    monkeypatch.setattr(fd, "FOOTBALL_API_KEY", "")
    with pytest.raises(fd.FaltaLaClave) as e:
        await limpio._get("/competitions/PD/standings")
    assert "FOOTBALL_API_KEY" in str(e.value)
    assert "gratis" in str(e.value)
    assert not _ClienteFalso.viajes, "ha salido a la red sin clave"


@pytest.mark.asyncio
async def test_sin_clave_no_se_gasta_turno(monkeypatch, limpio):
    """Y tampoco gasta turnos: sin clave no hay nada que intentar."""
    monkeypatch.setattr(fd, "FOOTBALL_API_KEY", "")
    for _ in range(20):
        with pytest.raises(fd.FaltaLaClave):
            await limpio._get("/competitions/PD/standings")
    assert fd._turnero.espera_estimada() == 0.0
