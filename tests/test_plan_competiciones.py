# -*- coding: utf-8 -*-
"""
EL 400 QUE NO ES LO QUE DICE SER
================================
football-data contesta a una competición que no entra en tu plan con:

    400  {"message": "Your API token is invalid."}

Y es engañoso. El 24 de octubre, en el mismo arranque y con siete
segundos entre medias, la MISMA clave dio:

    PL   200 OK          BL1  400 "token is invalid"
    FL1  200 OK          PD   400 "token is invalid"
                         SA   400 "token is invalid"

Una clave rota falla para todo. Ésa no.

Lo que se comprueba aquí: que Sportalyze distingue las dos cosas, y
que NO lo hace mirando el texto del mensaje — que viene en el idioma
de quien pregunta y cambiaría la respuesta con sólo cambiar de idioma.
"""
import httpx
import pytest

from backend.errors import ClaveInvalida, CompeticionNoIncluida
from backend.scrapers import football_data as fd


def _respuesta(codigo, cuerpo):
    peticion = httpx.Request("GET", "https://api.football-data.org/v4/x")
    return httpx.Response(codigo, json=cuerpo, request=peticion)


class _ClienteFalso:
    """Un httpx.AsyncClient de mentira que contesta lo que le digas."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.pedidas = []

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None):
        self.pedidas.append(url)
        return self.respuestas.pop(0)


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    """Cada prueba empieza con la bandera y la caché a cero.

    Sin esto, una prueba que deja la clave marcada como buena cambia
    el resultado de la siguiente. Se descubrió al escribirlas.
    """
    monkeypatch.setattr(fd, "_LA_CLAVE_HA_FUNCIONADO", False)
    monkeypatch.setattr(fd, "FOOTBALL_API_KEY", "una-clave-de-pega")
    monkeypatch.setattr(fd.football_client, "headers",
                        {"X-Auth-Token": "una-clave-de-pega"})
    # LA CACHÉ SE LLAMA _caches, NO _CAJAS.
    #
    # La primera versión de este fixture limpiaba un `_CAJAS` que no
    # existe, con un getattr que se tragaba el fallo sin decir nada.
    # Resultado: la respuesta buena de /competitions/PL/standings se
    # quedaba guardada de una prueba a la siguiente, la siguiente la
    # servía de caché sin gastar la respuesta falsa, y los papeles se
    # descolocaban. Dos pruebas decían «DID NOT RAISE» por eso.
    #
    # Una limpieza que no limpia nada es peor que no limpiar: parece
    # que lo hace.
    for caja in fd._caches.values():
        caja.clear()
    fd._en_vuelo.clear()
    yield


# ══════════════════════════════════════════════════════════
# EL EXTRACTOR DEL CÓDIGO DE COMPETICIÓN
# ══════════════════════════════════════════════════════════

@pytest.mark.parametrize("endpoint,esperado", [
    ("/competitions/PD/standings", "PD"),
    ("/competitions/BL1/matches", "BL1"),
    ("/competitions/PL", "PL"),
    ("/competitions", None),
    ("/teams/81", None),
    ("/teams/81/matches", None),
])
def test_saca_la_competicion_del_endpoint(endpoint, esperado):
    assert fd._competicion_de(endpoint) == esperado


# ══════════════════════════════════════════════════════════
# LA DISTINCIÓN, QUE ES TODO
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_el_400_antes_de_que_nada_funcione_es_clave_invalida(monkeypatch):
    """Si la clave no ha traído datos NI UNA VEZ, un 400 sí puede ser
    que esté rota. Aquí no se presume inocencia."""
    falso = _ClienteFalso([
        _respuesta(400, {"message": "Your API token is invalid.",
                         "errorCode": 400}),
    ])
    monkeypatch.setattr(fd.httpx, "AsyncClient", falso)

    with pytest.raises(ClaveInvalida) as e:
        await fd.football_client.get_standings("PD")
    assert "ni una vez" in str(e.value)


@pytest.mark.asyncio
async def test_el_mismo_400_despues_de_una_buena_es_la_competicion(monkeypatch):
    """LA PRUEBA QUE JUSTIFICA TODO EL ARREGLO.

    Primero una liga contesta bien; después otra contesta ese 400.
    Es la secuencia exacta del arranque del 24 de octubre: PL bien,
    PD mal. La segunda NO puede ser «clave inválida».
    """
    falso = _ClienteFalso([
        _respuesta(200, {"standings": [{"table": []}]}),
        _respuesta(400, {"message": "Your API token is invalid.",
                         "errorCode": 400}),
    ])
    monkeypatch.setattr(fd.httpx, "AsyncClient", falso)

    await fd.football_client.get_standings("PL")        # ésta va bien

    with pytest.raises(CompeticionNoIncluida) as e:
        await fd.football_client.get_standings("PD")
    assert e.value.competicion == "PD"
    assert "plan" in str(e.value)


@pytest.mark.asyncio
async def test_no_se_mira_el_texto_del_mensaje(monkeypatch):
    """Y ÉSTA ES LA QUE IMPIDE EL ARREGLO FÁCIL Y MALO.

    football-data contesta en el idioma del que pregunta: el mismo
    fallo llegó como «Your API token is invalid» y como «Su token de
    API no es válido». Una comprobación por texto se rompe el día que
    cambien de idioma, de mayúsculas o de redacción.

    Aquí el mensaje es una frase inventada que no se parece a ninguna
    de las dos, y el diagnóstico tiene que salir igual.
    """
    falso = _ClienteFalso([
        _respuesta(200, {"standings": [{"table": []}]}),
        _respuesta(400, {"message": "Chrzanić siatkówka 42", "errorCode": 400}),
    ])
    monkeypatch.setattr(fd.httpx, "AsyncClient", falso)

    await fd.football_client.get_standings("FL1")

    with pytest.raises(CompeticionNoIncluida):
        await fd.football_client.get_standings("SA")


@pytest.mark.asyncio
async def test_un_400_que_no_es_de_competicion_no_se_disculpa(monkeypatch):
    """`/competitions` a secas no es una competición concreta: ahí un
    400 no se puede achacar al plan."""
    falso = _ClienteFalso([
        _respuesta(200, {"standings": [{"table": []}]}),
        _respuesta(400, {"message": "lo que sea", "errorCode": 400}),
    ])
    monkeypatch.setattr(fd.httpx, "AsyncClient", falso)

    await fd.football_client.get_standings("PL")

    with pytest.raises(ClaveInvalida):
        await fd.football_client._get("/competitions")


@pytest.mark.asyncio
async def test_el_403_sigue_siendo_clave_invalida(monkeypatch):
    """Un 403 sí es de clave, lo diga quien lo diga."""
    falso = _ClienteFalso([
        _respuesta(200, {"standings": [{"table": []}]}),
        _respuesta(403, {"message": "forbidden"}),
    ])
    monkeypatch.setattr(fd.httpx, "AsyncClient", falso)

    await fd.football_client.get_standings("PL")

    with pytest.raises(ClaveInvalida):
        await fd.football_client.get_standings("PD")


# ══════════════════════════════════════════════════════════
# LO QUE VE EL VISITANTE
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_la_ruta_explica_el_plan_y_dice_que_SI_hay(monkeypatch):
    """Un error que no dice qué puedes hacer en su lugar deja al
    visitante mirando una pared."""
    from fastapi.testclient import TestClient
    import main

    async def falso_standings(codigo):
        raise CompeticionNoIncluida("PD")
    monkeypatch.setattr(main.football_client, "get_standings", falso_standings)

    cliente = TestClient(main.app, raise_server_exceptions=False)
    r = cliente.get("/api/standings/PD")

    assert r.status_code == 503
    d = r.json()["detail"]
    assert d["motivo"] == "competicion_no_incluida"
    assert d["competicion"] == "PD"
    # el nombre de verdad de la liga, no su código
    assert "La Liga" in d["detalle"]
    # y lo que importa: que diga que la clave NO está mal
    assert "no es que la clave esté mal" in d["detalle"].lower()
    # y adónde ir
    assert "Understat" in d["que_si_hay"]


@pytest.mark.asyncio
async def test_la_clave_rota_de_verdad_se_sigue_diciendo(monkeypatch):
    """El arreglo no puede tapar el caso que sí es culpa de la clave."""
    from fastapi.testclient import TestClient
    import main

    async def falso_standings(codigo):
        raise ClaveInvalida("no ha traído datos ni una vez")
    monkeypatch.setattr(main.football_client, "get_standings", falso_standings)

    cliente = TestClient(main.app, raise_server_exceptions=False)
    r = cliente.get("/api/standings/PD")

    assert r.status_code == 503
    assert r.json()["detail"]["motivo"] == "clave_invalida"
