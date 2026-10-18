# -*- coding: utf-8 -*-
"""
PRUEBAS DEL INFORME POST-PARTIDO
================================
    python3 -m pytest tests/test_informe.py -v

Sin red. Sobre la final del Mundial 2022 (Argentina 3-3 Francia), con
los eventos de verdad de StatsBomb Open Data.

POR QUÉ ESE PARTIDO Y NO OTRO
-----------------------------
Porque es el que más trampas tiene juntas:

  · Hubo prórroga, así que el partido dura 120 minutos y no 90.
  · Hubo TANDA DE PENALTIS, que viene como eventos normales en el
    periodo 5 y que, si se cuenta, deja el marcador en 7-5 y le regala
    1,57 de xG a Francia sin haber tirado a puerta.
  · El primer cambio de Francia fue en el minuto 40, o sea que la red
    de pases de un equipo se corta a la mitad de la primera parte.
  · Tiene nombres que ninguna regla automática acierta: «Ángel Fabián
    Di María Hernández», «Randal Kolo Muani», «Alexis Mac Allister».

Si el informe sale bien aquí, sale bien en un partido normal.

EL MARCADOR ES LA COMPROBACIÓN MADRE
------------------------------------
Los goles que salen de los eventos tienen que cuadrar con el marcador
oficial del partido. Es una comprobación que no se puede falsear: o el
3-3 sale de los datos, o algo está mal contado.
"""
import copy
import gzip
import json
import os
import sys

import pytest

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(AQUI))

from backend.ml import informe as I     # noqa: E402

DATOS = os.path.join(AQUI, "datos")


def _gz(nombre):
    with gzip.open(os.path.join(DATOS, nombre), "rt", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def eventos():
    return _gz("final_mundial_2022_eventos.json.gz")


@pytest.fixture(scope="module")
def alineaciones():
    return _gz("final_mundial_2022_alineaciones.json.gz")


@pytest.fixture(scope="module")
def ficha():
    with open(os.path.join(DATOS, "final_mundial_2022_ficha.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def inf(eventos, ficha, alineaciones):
    return I.informe(eventos, ficha, alineaciones)


# ════════════════════════════════════════════════════════════════
# LA TANDA DE PENALTIS NO ES EL PARTIDO
# ════════════════════════════════════════════════════════════════

def test_el_marcador_es_el_oficial(inf):
    assert (inf["goles_local"], inf["goles_visitante"]) == (3, 3)
    assert inf["local"] == "Argentina" and inf["visitante"] == "France"


def test_la_tanda_no_cuenta_para_el_marcador(eventos):
    """Si el periodo 5 contara, la final acabó 7-5. No acabó 7-5."""
    tanda = [e for e in eventos if e.get("period") == 5]
    assert tanda, "este partido tiene que tener tanda, si no la prueba no prueba nada"
    goles_tanda = sum(1 for e in tanda if e["type"]["name"] == "Shot"
                      and (e["shot"].get("outcome") or {}).get("name") == "Goal")
    assert goles_tanda == 6, goles_tanda
    assert sum(I.marcador(eventos).values()) == 6     # 3 + 3, no 12


def test_la_tanda_no_cuenta_para_el_xg(inf):
    """Cada penalti de la tanda vale 0,783 de xG. Son seis: 4,7 de xG
    regalado si se cuelan."""
    for e in (inf["local"], inf["visitante"]):
        assert inf["estadisticas"][e]["xg"] < 3.5, (e, inf["estadisticas"][e]["xg"])
    assert inf["estadisticas"]["Argentina"]["xg"] == pytest.approx(2.758, abs=0.01)
    assert inf["estadisticas"]["France"]["xg"] == pytest.approx(2.273, abs=0.01)


def test_ningun_tiro_del_informe_es_de_la_tanda(inf):
    assert all(t["periodo"] != 5 for t in inf["tiros"])
    assert len(inf["tiros"]) == 30


def test_se_avisa_de_que_hubo_tanda(inf):
    assert inf["aviso"] and "penaltis" in inf["aviso"].lower()


# ════════════════════════════════════════════════════════════════
# SE NIEGA SI EL MARCADOR NO CUADRA
# ════════════════════════════════════════════════════════════════

def test_si_el_marcador_no_cuadra_revienta(eventos, ficha, alineaciones):
    """La comprobación madre. Si alguien cambia cómo se cuentan los
    goles, esto salta antes de que salga un informe con el resultado
    mal."""
    mala = copy.deepcopy(ficha)
    mala["home_score"] = 5
    with pytest.raises(I.PartidoIncompleto) as e:
        I.informe(eventos, mala, alineaciones)
    assert "no cuadra" in str(e.value)


def test_sin_eventos_no_hay_informe():
    with pytest.raises(I.PartidoIncompleto):
        I.informe([])


def test_sin_alineacion_inicial_no_hay_informe(eventos):
    sin = [e for e in eventos if e["type"]["name"] != "Starting XI"]
    with pytest.raises(I.PartidoIncompleto) as e:
        I.informe(sin)
    assert "alineaciones iniciales" in str(e.value)


# ════════════════════════════════════════════════════════════════
# LOS NOMBRES, QUE NINGUNA REGLA ACIERTA SOLA
# ════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("completo,apodo,esperado", [
    ("Lionel Andrés Messi Cuccittini", "Lionel Messi", "Messi"),
    ("Ángel Fabián Di María Hernández", "Ángel Di María", "Di María"),
    ("Nicolás Hernán Otamendi", "Nicolás Otamendi", "Otamendi"),
    ("Kylian Mbappé Lottin", "Kylian Mbappé", "Mbappé"),
    ("Marcus Thuram", None, "Thuram"),             # sin apodo, ya es corto
    ("Randal Kolo Muani", None, "Kolo Muani"),     # sin apodo, apellido doble
    ("Ronaldinho", None, "Ronaldinho"),            # una sola palabra
])
def test_el_apodo_manda_sobre_la_regla(completo, apodo, esperado):
    assert I._nombre_corto(completo, apodo) == esperado


def test_los_nombres_de_la_red_son_los_de_verdad(inf):
    """Sin el apodo de StatsBomb, «Di María» salía como «María» y
    «Otamendi» como «Hernán». Tres de once mal."""
    nombres = {n["corto"] for n in inf["red"]["Argentina"]["nodos"]}
    assert "Di María" in nombres
    assert "Otamendi" in nombres
    assert "Messi" in nombres
    assert "María" not in nombres and "Hernán" not in nombres


def test_cada_titular_lleva_su_dorsal(inf):
    for e in (inf["local"], inf["visitante"]):
        for n in inf["red"][e]["nodos"]:
            assert isinstance(n["dorsal"], int), (e, n["corto"])


# ════════════════════════════════════════════════════════════════
# LA RED DE PASES
# ════════════════════════════════════════════════════════════════

def test_la_red_tiene_once_jugadores(inf):
    for e in (inf["local"], inf["visitante"]):
        assert len(inf["red"][e]["nodos"]) == 11, e


def test_la_red_se_corta_en_el_primer_cambio(inf):
    """Francia cambió en el minuto 40. Si la red llegara al 90, estaría
    poniendo la posición media de gente que ya no estaba."""
    assert inf["red"]["France"]["hasta_minuto"] == 40
    assert inf["red"]["Argentina"]["hasta_minuto"] == 63
    for e in (inf["local"], inf["visitante"]):
        assert inf["red"][e]["motivo_corte"] == "primer cambio"


def test_nadie_se_sale_del_campo(inf):
    for e in (inf["local"], inf["visitante"]):
        for n in inf["red"][e]["nodos"]:
            assert 0 <= n["x"] <= 120 and 0 <= n["y"] <= 80, (e, n["corto"])


def test_los_enlaces_unen_jugadores_que_estan(inf):
    for e in (inf["local"], inf["visitante"]):
        r = inf["red"][e]
        ids = {n["id"] for n in r["nodos"]}
        for l in r["enlaces"]:
            assert l["de"] in ids and l["a"] in ids
            assert l["de"] != l["a"], "un enlace de un jugador consigo mismo"
            assert l["pases"] >= r["min_pases_enlace"]


def test_no_hay_enlaces_repetidos(inf):
    """Un enlace es una PAREJA, no una dirección: si A→B y B→A salieran
    por separado, la línea más gruesa del dibujo sería mentira."""
    for e in (inf["local"], inf["visitante"]):
        parejas = [tuple(sorted((l["de"], l["a"])))
                   for l in inf["red"][e]["enlaces"]]
        assert len(set(parejas)) == len(parejas), e


def test_el_portero_esta_en_su_sitio(inf):
    """Comprobación de olfato: si el portero sale en el centro del
    campo, las posiciones medias están mal calculadas."""
    for e in (inf["local"], inf["visitante"]):
        gk = next(n for n in inf["red"][e]["nodos"]
                  if "Goalkeeper" in n["puesto"])
        assert gk["x"] < 45, (e, gk["corto"], gk["x"])


# ════════════════════════════════════════════════════════════════
# LOS TIROS
# ════════════════════════════════════════════════════════════════

def test_los_goles_de_los_tiros_son_los_del_marcador(inf):
    assert sum(1 for t in inf["tiros"] if t["gol"]) == \
        inf["goles_local"] + inf["goles_visitante"]


def test_mbappe_metio_tres(inf):
    """El primer triplete en una final de Mundial desde 1966."""
    suyos = [t for t in inf["tiros"] if t["corto"] == "Mbappé" and t["gol"]]
    assert len(suyos) == 3
    assert sum(1 for t in suyos if t["penalti"]) == 2


def test_todos_los_tiros_estan_dentro_del_campo(inf):
    for t in inf["tiros"]:
        assert 0 <= t["x"] <= 120 and 0 <= t["y"] <= 80, t


def test_el_xg_de_un_tiro_esta_entre_cero_y_uno(inf):
    for t in inf["tiros"]:
        assert 0.0 <= t["xg"] <= 1.0, t


def test_el_xg_de_la_carrera_acaba_donde_el_de_la_comparativa(inf):
    """Dos sitios de la pantalla enseñan el mismo xG. Si no coinciden,
    uno de los dos miente."""
    for e in (inf["local"], inf["visitante"]):
        final = inf["carrera_xg"][e][-1]["xg"]
        assert final == pytest.approx(inf["estadisticas"][e]["xg"], abs=0.01), e


def test_la_carrera_de_xg_nunca_baja(inf):
    """Es un acumulado: si baja, está mal sumado."""
    for e in (inf["local"], inf["visitante"]):
        serie = [p["xg"] for p in inf["carrera_xg"][e]]
        assert serie == sorted(serie), e
        assert serie[0] == 0.0


# ════════════════════════════════════════════════════════════════
# LAS ESTADÍSTICAS
# ════════════════════════════════════════════════════════════════

def test_la_posesion_suma_cien(inf):
    total = sum(inf["estadisticas"][e]["posesion"]
                for e in (inf["local"], inf["visitante"]))
    assert total == pytest.approx(100.0, abs=0.2)


def test_los_tiros_a_puerta_no_pasan_de_los_tiros(inf):
    for e in (inf["local"], inf["visitante"]):
        d = inf["estadisticas"][e]
        assert d["tiros_a_puerta"] <= d["tiros"]
        assert d["pases_bien"] <= d["pases"]
        assert 0 <= d["precision"] <= 100
        assert d["duelos_ganados"] <= d["duelos"]


def test_los_tiros_de_la_tabla_son_los_del_mapa(inf):
    for e in (inf["local"], inf["visitante"]):
        delmapa = sum(1 for t in inf["tiros"] if t["equipo"] == e)
        assert inf["estadisticas"][e]["tiros"] == delmapa, e


def test_argentina_tuvo_mas_la_pelota(inf):
    """Otra de olfato, contra lo que se sabe del partido."""
    assert inf["estadisticas"]["Argentina"]["posesion"] > \
           inf["estadisticas"]["France"]["posesion"]


# ════════════════════════════════════════════════════════════════
# LOS JUGADORES
# ════════════════════════════════════════════════════════════════

def test_los_goles_por_jugador_suman_los_del_partido(inf):
    assert sum(j["goles"] for j in inf["jugadores"]) == \
        inf["goles_local"] + inf["goles_visitante"]


def test_el_xg_por_jugador_suma_el_del_equipo(inf):
    for e in (inf["local"], inf["visitante"]):
        suma = sum(j["xg"] for j in inf["jugadores"] if j["equipo"] == e)
        assert suma == pytest.approx(inf["estadisticas"][e]["xg"], abs=0.02), e


def test_los_pases_por_jugador_suman_los_del_equipo(inf):
    for e in (inf["local"], inf["visitante"]):
        suma = sum(j["pases"] for j in inf["jugadores"] if j["equipo"] == e)
        assert suma == inf["estadisticas"][e]["pases"], e


def test_nadie_da_mas_pases_buenos_que_pases(inf):
    for j in inf["jugadores"]:
        assert j["pases_bien"] <= j["pases"], j["corto"]
        assert j["pases_progresivos"] <= j["pases_bien"], j["corto"]
        assert j["regates_bien"] <= j["regates"], j["corto"]
        assert j["goles"] <= j["tiros"], j["corto"]


def test_messi_dio_mas_pases_progresivos_que_nadie_de_argentina(inf):
    arg = [j for j in inf["jugadores"] if j["equipo"] == "Argentina"]
    mejor = max(arg, key=lambda j: j["pases_progresivos"])
    assert mejor["corto"] == "Messi", mejor["corto"]


# ════════════════════════════════════════════════════════════════
# LA PROCEDENCIA
# ════════════════════════════════════════════════════════════════

def test_el_informe_dice_de_donde_viene(inf):
    """La atribución a StatsBomb no es cortesía: es la condición de uso
    de los datos abiertos."""
    assert inf["fuente"] == "StatsBomb Open Data"
    assert "StatsBomb" in inf["atribucion"]
    for campo in ("competicion", "temporada", "fase", "fecha", "eventos"):
        assert inf.get(campo), campo


def test_el_informe_viaja_como_json(inf):
    assert json.loads(json.dumps(inf))["goles_local"] == 3


def test_el_campo_mide_lo_que_dice_statsbomb(inf):
    assert inf["campo"] == {"largo": 120.0, "ancho": 80.0}


# ════════════════════════════════════════════════════════════════
# SIN LAS ALINEACIONES TAMBIÉN TIENE QUE FUNCIONAR
# ════════════════════════════════════════════════════════════════

def test_funciona_sin_el_fichero_de_alineaciones(eventos, ficha):
    """Si StatsBomb da los eventos y no las alineaciones, el informe
    sale igual: sólo se pierden los apodos y los dorsales."""
    sin = I.informe(eventos, ficha, None)
    assert sin["goles_local"] == 3
    assert len(sin["red"]["Argentina"]["nodos"]) == 11
    assert all(n["dorsal"] is None for n in sin["red"]["Argentina"]["nodos"])


def test_funciona_sin_la_ficha_del_partido(eventos, alineaciones):
    """Sin ficha no se puede comprobar el marcador contra el oficial, y
    se dice: no se inventa una competición ni una fecha."""
    sin = I.informe(eventos, None, alineaciones)
    assert sin["goles_local"] == 3
    assert sin["competicion"] == "" and sin["fecha"] == ""


# ════════════════════════════════════════════════════════════════
# LAS RUTAS
# ════════════════════════════════════════════════════════════════
#
# Con un StatsBomb de pega: estas pruebas no bajan los 3,7 MB de
# eventos de internet. Lo que comprueban es el contrato — qué código y
# qué `motivo` sale en cada caso — que es lo que la pantalla necesita
# para poder explicar un hueco en vez de quedarse en blanco.

@pytest.fixture
def cliente(monkeypatch, eventos, alineaciones, ficha):
    from fastapi.testclient import TestClient
    import main
    from backend.scrapers import statsbomb as sb

    sb._competiciones.clear()
    sb._partidos.clear()
    sb._informes.clear()

    estado = {"revienta": None, "eventos": eventos,
              "alineaciones": alineaciones, "ficha": ficha}

    async def fake_eventos(mid):
        if estado["revienta"]:
            raise estado["revienta"]
        return estado["eventos"]

    async def fake_alineaciones(mid):
        if estado["revienta"]:
            raise estado["revienta"]
        return estado["alineaciones"]

    async def fake_ficha(mid):
        return estado["ficha"]

    async def fake_competiciones():
        if estado["revienta"]:
            raise estado["revienta"]
        return [{"competition_id": 43, "season_id": 106,
                 "competition_name": "FIFA World Cup", "season_name": "2022"}]

    async def fake_partidos(c, s):
        if estado["revienta"]:
            raise estado["revienta"]
        return [estado["ficha"]]

    monkeypatch.setattr(sb, "eventos", fake_eventos)
    monkeypatch.setattr(sb, "alineaciones", fake_alineaciones)
    monkeypatch.setattr(sb, "ficha", fake_ficha)
    monkeypatch.setattr(sb, "competiciones", fake_competiciones)
    monkeypatch.setattr(sb, "partidos", fake_partidos)
    return TestClient(main.app), estado, sb


def test_la_ruta_devuelve_el_informe(cliente):
    cli, _, _ = cliente
    r = cli.get("/api/informe/3869685")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["goles_local"] == 3 and d["goles_visitante"] == 3
    assert d["match_id"] == 3869685
    assert d["fuente"] == "StatsBomb Open Data"
    assert len(d["tiros"]) == 30


def test_competiciones_y_partidos_salen_ligeros(cliente):
    cli, _, _ = cliente
    c = cli.get("/api/informe/competiciones")
    assert c.status_code == 200
    assert c.json()["total"] == 1

    p = cli.get("/api/informe/partidos/43/106")
    assert p.status_code == 200
    uno = p.json()["partidos"][0]
    # el menú sólo necesita esto; mandar la ficha entera sería mandar
    # muchos kilobytes para pintar una línea de texto
    assert set(uno) == {"match_id", "fecha", "local", "visitante",
                        "goles_local", "goles_visitante", "fase"}


def test_la_ruta_de_competiciones_no_la_pisa_el_match_id(cliente):
    """/api/informe/competiciones y /api/informe/{match_id} se parecen.
    Si el orden de las rutas cambiara, 'competiciones' intentaría
    leerse como un número de partido."""
    cli, _, _ = cliente
    assert cli.get("/api/informe/competiciones").status_code == 200


def test_un_partido_que_no_esta_abierto_da_404(cliente):
    cli, estado, sb = cliente
    estado["revienta"] = sb.PartidoNoEstaAbierto("events/1.json")
    r = cli.get("/api/informe/1")
    assert r.status_code == 404
    assert r.json()["detail"]["motivo"] == "no_esta_abierto"


def test_si_statsbomb_no_contesta_da_503(cliente):
    from backend.errors import FuenteNoDisponible
    cli, estado, _ = cliente
    estado["revienta"] = FuenteNoDisponible("StatsBomb", "sin salida a internet")
    r = cli.get("/api/informe/3869685")
    assert r.status_code == 503
    assert r.json()["detail"]["motivo"] == "fuente_caida"


def test_si_el_marcador_no_cuadra_la_ruta_no_publica(cliente):
    """La comprobación madre, vista desde fuera: antes un hueco con su
    explicación que un informe con el resultado mal."""
    cli, estado, _ = cliente
    estado["ficha"] = dict(estado["ficha"], home_score=9)
    r = cli.get("/api/informe/3869685")
    assert r.status_code == 503
    assert r.json()["detail"]["motivo"] == "partido_incompleto"
    assert "no cuadra" in r.json()["detail"]["detalle"]


def test_la_ruta_guarda_el_informe_calculado(cliente):
    """Son megas de eventos y un par de segundos de cálculo. La segunda
    visita no vuelve a pedirlo."""
    cli, estado, _ = cliente
    assert cli.get("/api/informe/3869685").status_code == 200
    estado["revienta"] = RuntimeError("no deberían volver a pedir los eventos")
    assert cli.get("/api/informe/3869685").status_code == 200
