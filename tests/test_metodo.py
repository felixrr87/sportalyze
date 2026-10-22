# -*- coding: utf-8 -*-
"""
PRUEBAS DE LA PANTALLA DE MÉTODO Y DE LA RUTA DE HALLAZGOS
==========================================================
Lo que se vigila aquí no es que el texto esté bien escrito: es que las
CIFRAS del método salgan del código y no de unos números tecleados
aparte.

Una página que explica el método con las constantes copiadas a mano se
queda vieja el primer día que alguien toca una, y entonces miente
sobre lo único que esta aplicación promete.
"""
import pytest
from fastapi.testclient import TestClient

import main
from backend.ml import hallazgos as hall
from backend.ml import onoff
from backend.ml import puntuar as punt


@pytest.fixture
def cliente():
    return TestClient(main.app, raise_server_exceptions=False)


def _constante(d, nombre):
    for n in d["numeros_que_se_pueden_discutir"]:
        if n["nombre"] == nombre:
            return n
    raise AssertionError(f"{nombre} no sale en el método")


# ══════════════════════════════════════════════════════════
# EL MÉTODO
# ══════════════════════════════════════════════════════════

def test_el_metodo_contesta(cliente):
    r = cliente.get("/api/metodo")
    assert r.status_code == 200
    d = r.json()
    for clave in ("fuentes", "fuentes_descartadas",
                  "numeros_que_se_pueden_discutir", "cuando_se_niega",
                  "como_se_prueba"):
        assert clave in d, f"falta {clave}"


def test_cada_constante_dice_donde_vive(cliente):
    """Sin el fichero, «K_MINUTOS = 540» es un número que hay que
    creerse. Con él, es uno que se puede ir a mirar."""
    d = cliente.get("/api/metodo").json()
    for n in d["numeros_que_se_pueden_discutir"]:
        assert n["donde"].endswith(".py"), n
        assert n["que_hace"].strip(), n
        assert n["valor"] is not None, n


def test_las_cifras_salen_del_codigo_y_no_estan_tecleadas(monkeypatch, cliente):
    """LA PRUEBA QUE JUSTIFICA LA PANTALLA.

    Se cambia la constante de verdad y la pantalla tiene que cambiar
    sola. Si estuviera escrita a mano, aquí seguiría diciendo 540.
    """
    assert _constante(cliente.get("/api/metodo").json(),
                      "K_MINUTOS")["valor"] == punt.K_MINUTOS

    monkeypatch.setattr(punt, "K_MINUTOS", 999)
    monkeypatch.setattr(onoff, "K_ENCOGIDO", 777)
    d = cliente.get("/api/metodo").json()
    assert _constante(d, "K_MINUTOS")["valor"] == 999
    assert _constante(d, "K_ENCOGIDO")["valor"] == 777


def test_las_pruebas_se_cuentan_leyendo_el_disco(cliente):
    d = cliente.get("/api/metodo").json()["como_se_prueba"]["pruebas"]
    assert d["total"] and d["total"] > 100
    assert "test_hallazgos.py" in d["por_fichero"]
    # la suma de los ficheros tiene que ser el total: si no, uno de los
    # dos números está puesto a ojo
    assert sum(d["por_fichero"].values()) == d["total"]


def test_fbref_sale_descartado_y_con_el_motivo(cliente):
    """La decisión de no usar datos de Opta es parte del método, no
    una omisión. Si no está escrita, parece que no se le ocurrió."""
    d = cliente.get("/api/metodo").json()
    texto = " ".join(f["nombre"] + " " + f["por_que"]
                     for f in d["fuentes_descartadas"])
    assert "FBref" in texto and "Opta" in texto


def test_cada_fuente_dice_lo_que_NO_da(cliente):
    """Lo que una fuente no publica es la mitad del método."""
    for f in cliente.get("/api/metodo").json()["fuentes"]:
        assert f["no_da"].strip(), f
        assert f["licencia"].strip(), f


def test_estan_las_negativas_con_lo_que_hace_en_su_lugar(cliente):
    d = cliente.get("/api/metodo").json()["cuando_se_niega"]
    assert len(d) >= 4
    for n in d:
        assert n["por_que"].strip() and n["que_hace_en_su_lugar"].strip(), n
    texto = " ".join(n["que"] for n in d)
    assert "defensa" in texto and "xG" in texto


# ══════════════════════════════════════════════════════════
# LA RUTA DE HALLAZGOS
# ══════════════════════════════════════════════════════════

def _plantilla(n=300, semilla=5):
    """Jugadores que convierten exactamente a su xG: no hay hallazgos
    de verdad, así que todo lo que salga es un falso positivo."""
    import random
    rnd = random.Random(semilla)
    gente = []
    for i in range(n):
        tiros = rnd.randint(16, 60)
        xg_tiro = rnd.uniform(0.07, 0.2)
        goles = sum(1 for _ in range(tiros) if rnd.random() < xg_tiro)
        gente.append({
            "player_id": str(i), "name": f"J{i}", "team": "E",
            "position": "F", "time": 900, "shots": tiros,
            "npg": goles, "npxG": round(tiros * xg_tiro, 2),
            "goals": goles, "xG": round(tiros * xg_tiro, 2),
        })
    return gente


@pytest.fixture
def sin_understat(monkeypatch):
    async def falso(liga, season=None):
        return _plantilla()
    monkeypatch.setattr(main, "get_league_players", falso)


def test_los_hallazgos_contestan_con_las_dos_cifras_que_importan(
        cliente, sin_understat):
    d = cliente.get("/api/hallazgos?liga=PD").json()
    assert d["cuantos_probados"] == 300
    # las dos cifras sin las cuales una lista de hallazgos no se puede
    # juzgar: cuántos se han mirado y cuántos saldrían haciéndolo mal
    assert d["esperados_por_puro_azar"] == pytest.approx(15.0)
    assert "pasarian_sin_corregir" in d
    assert d["pasarian_sin_corregir"] >= len(d["hallazgos"])
    assert d["sin_penaltis"] is True
    assert d["fdr"] == hall.FDR


def test_la_ruta_no_devuelve_cientos_de_descartados(cliente, sin_understat):
    """Se dice cuántos hay y se enseñan unos pocos: mandar 900 líneas
    de descarte es tirar la respuesta a la basura."""
    d = cliente.get("/api/hallazgos?liga=PD&min_minutos=5000").json()
    assert d["cuantos_descartados"] == 300
    assert len(d["muestra_de_descartados"]) <= 12
    assert d["muestra_de_descartados"][0]["motivo"] == "pocos_minutos"


def test_una_liga_que_no_existe_se_dice(cliente, sin_understat):
    r = cliente.get("/api/hallazgos?liga=XX")
    assert r.status_code == 400
    assert r.json()["detail"]["motivo"] == "liga_desconocida"


def test_subir_el_fdr_nunca_saca_menos_nombres(cliente, sin_understat):
    pocos = len(cliente.get("/api/hallazgos?liga=PD&fdr=0.05").json()["hallazgos"])
    muchos = len(cliente.get("/api/hallazgos?liga=PD&fdr=0.3").json()["hallazgos"])
    assert muchos >= pocos


def test_si_understat_se_cae_se_dice_y_no_sale_una_lista_vacia(
        cliente, monkeypatch):
    from backend.scrapers.understat import FuenteNoDisponible

    async def roto(liga, season=None):
        raise FuenteNoDisponible("Understat no contesta")
    monkeypatch.setattr(main, "get_league_players", roto)

    r = cliente.get("/api/hallazgos?liga=PD")
    assert r.status_code == 503
    assert r.json()["detail"]["motivo"] == "fuente_caida"


def test_la_atribucion_obligatoria_esta_y_con_las_palabras_que_piden(cliente):
    """El punto 7.1 de las condiciones de football-data.org pide esta
    frase, con estas palabras, en un sitio visible. Estuvo sin poner
    desde el principio.

    Se comprueba la frase literal a propósito: «datos de
    football-data» no cumple lo que piden, por muy parecido que
    suene.
    """
    d = cliente.get("/api/metodo").json()
    assert "Football data provided by the Football-Data.org API" in d["atribucion"]
    assert any("Understat" in a for a in d["atribucion"])
