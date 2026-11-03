# -*- coding: utf-8 -*-
"""
PRUEBAS DE LA EDAD
==================
    python3 -m pytest tests/test_edades.py -v

Understat no publica fechas de nacimiento. football-data sí. Lo que se
vigila aquí es que cruzarlas no invente ninguna edad por el camino, y
que cuando falten se diga en vez de dejar un filtro mudo.

El fallo que esto evita no es «sale una edad mal». Es peor: un filtro
de «menores de 23» que devuelve una lista perfectamente creíble en la
que falta gente, o sobra, y nada en pantalla lo delata.
"""
import json
import os
import sys
from datetime import date

import pytest

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(AQUI))

from backend.ml import edades as ed     # noqa: E402


HOY = date(2026, 11, 3)


def _fichero(jugadores, descargado="2026-11-01"):
    return {"liga": "PD", "season": 2026, "descargado": descargado,
            "jugadores": jugadores}


# ══════════════════════════════════════════════════════════
# LA EDAD SE CALCULA, NO SE GUARDA
# ══════════════════════════════════════════════════════════

def test_anos_cumplidos_no_resta_de_anos():
    """Quien cumple mañana todavía no los tiene."""
    assert ed.edad_a_dia_de_hoy("2000-11-04", HOY) == 25
    assert ed.edad_a_dia_de_hoy("2000-11-03", HOY) == 26   # cumple hoy
    assert ed.edad_a_dia_de_hoy("2000-11-02", HOY) == 26


def test_el_29_de_febrero_no_revienta():
    """Nacido en bisiesto, preguntado en año normal."""
    assert ed.edad_a_dia_de_hoy("2004-02-29", date(2026, 3, 1)) == 22
    assert ed.edad_a_dia_de_hoy("2004-02-29", date(2026, 2, 28)) == 21


@pytest.mark.parametrize("malo", [None, "", "no-es-una-fecha", "0000", 12345])
def test_una_fecha_rota_da_None_y_no_un_cero(malo):
    """UN CERO SERÍA EL PEOR RESULTADO POSIBLE.

    Un cero pasa cualquier filtro de «edad máxima» y convierte a un
    veterano en la perla de dieciséis años de la lista. None se puede
    detectar; un cero se cuela.
    """
    assert ed.edad_a_dia_de_hoy(malo, HOY) is None


def test_la_edad_no_se_guarda_guardada():
    """El mismo fichero, preguntado en dos momentos, da dos edades.

    Si se guardara «24» en vez de la fecha, medio mundo tendría un año
    de menos en cuanto pasara su cumpleaños y nadie se enteraría.
    """
    f = _fichero({"101": {"nacimiento": "2002-06-10"}})
    antes = [{"player_id": "101"}]
    despues = [{"player_id": "101"}]
    ed.poner_edades(antes, f, date(2026, 6, 9))
    ed.poner_edades(despues, f, date(2026, 6, 11))
    assert antes[0]["age"] == 23
    assert despues[0]["age"] == 24


# ══════════════════════════════════════════════════════════
# PEGAR LAS EDADES
# ══════════════════════════════════════════════════════════

def test_al_que_no_esta_no_se_le_pone_nada():
    """Ni cero, ni «desconocido», ni la media. Nada."""
    f = _fichero({"101": {"nacimiento": "2002-06-10"}})
    jugadores = [{"player_id": "101"}, {"player_id": "999"}]
    puestos, _ = ed.poner_edades(jugadores, f, HOY)
    assert puestos == 1
    assert jugadores[0]["age"] == 24
    assert "age" not in jugadores[1]


def test_sin_fichero_no_se_pega_nada_y_no_revienta():
    jugadores = [{"player_id": "101"}]
    puestos, avisos = ed.poner_edades(jugadores, None, HOY)
    assert puestos == 0
    assert "age" not in jugadores[0]
    assert avisos == []


def test_una_fecha_rota_en_el_fichero_no_pone_edad():
    f = _fichero({"101": {"nacimiento": "ayer"}})
    jugadores = [{"player_id": "101"}]
    puestos, _ = ed.poner_edades(jugadores, f, HOY)
    assert puestos == 0
    assert "age" not in jugadores[0]


def test_un_fichero_viejo_se_dice():
    f = _fichero({"101": {"nacimiento": "2002-06-10"}},
                 descargado="2026-08-01")      # 94 días antes
    _, avisos = ed.poner_edades([{"player_id": "101"}], f, HOY)
    assert avisos and "94 días" in avisos[0]


def test_un_fichero_reciente_no_molesta():
    f = _fichero({"101": {"nacimiento": "2002-06-10"}},
                 descargado="2026-11-01")
    _, avisos = ed.poner_edades([{"player_id": "101"}], f, HOY)
    assert avisos == []


# ══════════════════════════════════════════════════════════
# LO QUE SE LE CUENTA A QUIEN MIRA
# ══════════════════════════════════════════════════════════

def test_si_no_hay_ninguna_edad_se_dice_que_no_se_ha_filtrado():
    a = ed.aviso_de_cobertura(0, 400, 23)
    assert a and "NO se ha aplicado" in a


def test_si_hay_edades_a_medias_se_dice_cuantas():
    """«Quedan 40» significa cosas distintas según sobre cuántos."""
    a = ed.aviso_de_cobertura(120, 400, 23)
    assert a and "120 de 400" in a and "280" in a


def test_si_estan_todas_no_se_avisa_de_nada():
    assert ed.aviso_de_cobertura(400, 400, 23) is None


# ══════════════════════════════════════════════════════════
# EL FICHERO
# ══════════════════════════════════════════════════════════

def test_un_fichero_que_no_existe_devuelve_None(tmp_path, monkeypatch):
    monkeypatch.setattr(ed, "CARPETA", str(tmp_path))
    assert ed.cargar("PD", 2026) is None


def test_un_fichero_roto_devuelve_None_y_no_revienta(tmp_path, monkeypatch):
    """Mejor sin edades que con media aplicación caída."""
    monkeypatch.setattr(ed, "CARPETA", str(tmp_path))
    with open(ed.ruta("PD", 2026), "w") as fh:
        fh.write("{esto no es json")
    assert ed.cargar("PD", 2026) is None


def test_un_json_valido_pero_sin_jugadores_tambien_es_None(tmp_path, monkeypatch):
    monkeypatch.setattr(ed, "CARPETA", str(tmp_path))
    with open(ed.ruta("PD", 2026), "w") as fh:
        json.dump({"liga": "PD"}, fh)
    assert ed.cargar("PD", 2026) is None


def test_se_lee_lo_que_se_escribe(tmp_path, monkeypatch):
    monkeypatch.setattr(ed, "CARPETA", str(tmp_path))
    with open(ed.ruta("PD", 2026), "w") as fh:
        json.dump(_fichero({"101": {"nacimiento": "2002-06-10",
                                    "nacionalidad": "Spain"}}), fh)
    f = ed.cargar("PD", 2026)
    jugadores = [{"player_id": "101"}]
    ed.poner_edades(jugadores, f, HOY)
    assert jugadores[0]["age"] == 24
    assert jugadores[0]["nationality"] == "Spain"


# ══════════════════════════════════════════════════════════
# LA RUTA DE JUGADORES, QUE ES DONDE SE NOTA
# ══════════════════════════════════════════════════════════
#
# Las de arriba prueban el módulo. Éstas prueban la promesa: que
# `max_age` en /api/players filtre de verdad, y que filtre BIEN.
#
# Existen porque un sabotaje no puso nada en rojo. Al cambiar el
# filtro por `(p.get("age") or 99) <= max_age` —que es justo lo que
# haría cualquiera sin pensarlo— los jugadores sin fecha de
# nacimiento desaparecían de la lista en silencio, y las veinte
# pruebas del módulo seguían verdes. Un sabotaje que no pone nada
# rojo señala una prueba que falta, no un código que esté bien.

from fastapi.testclient import TestClient      # noqa: E402
import main                                    # noqa: E402


def _jugador(pid, nombre, pos="F S", minutos=900):
    return {"player_id": pid, "id": pid, "name": nombre, "position": pos,
            "time": minutos, "goals": 3, "xG": 2.5, "assists": 1,
            "xA": 1.2, "shots": 20, "key_passes": 15, "team": "Equipo",
            "npg": 3, "npxG": 2.5, "xGChain": 3.0, "xGBuildup": 1.0}


@pytest.fixture
def ruta(tmp_path, monkeypatch):
    """La ruta de jugadores con Understat de mentira y un fichero de
    edades en el que SÓLO el viejo tiene fecha."""
    monkeypatch.setattr(ed, "CARPETA", str(tmp_path))
    with open(ed.ruta("PD", 2026), "w") as fh:
        json.dump({"liga": "PD", "season": 2026,
                   "descargado": date.today().isoformat(),
                   "jugadores": {"1": {"nacimiento": "1990-01-01"}}}, fh)

    async def falso(codigo, season=None):
        return [_jugador("1", "El Viejo"), _jugador("2", "El Joven"),
                _jugador("3", "El Sin Fecha")]

    monkeypatch.setattr(main, "get_league_players", falso)
    return TestClient(main.app, raise_server_exceptions=False)


def test_el_filtro_de_edad_filtra_de_verdad(ruta):
    """Antes esto devolvía lo mismo con 18 que con 50."""
    d = ruta.get("/api/players/PD?season=2026&max_age=25&limit=10").json()
    nombres = [p["name"] for p in d["players"]]
    assert "El Viejo" not in nombres, "el de 1990 tiene que caer con max_age=25"


def test_quien_no_tiene_fecha_NO_se_descarta(ruta):
    """EL SABOTAJE QUE NO PONÍA NADA EN ROJO.

    No haber podido emparejar a alguien con football-data no es motivo
    para darlo por viejo y quitarlo de la lista. Se queda, y arriba se
    dice a cuántos se les ha aplicado el filtro.
    """
    d = ruta.get("/api/players/PD?season=2026&max_age=25&limit=10").json()
    nombres = [p["name"] for p in d["players"]]
    assert "El Sin Fecha" in nombres
    assert "El Joven" in nombres


def test_se_dice_a_cuantos_se_les_ha_podido_aplicar(ruta):
    """Sin esta frase, «quedan 2» no se puede interpretar."""
    d = ruta.get("/api/players/PD?season=2026&max_age=25&limit=10").json()
    assert any("1 de 3" in a for a in d.get("avisos", [])), d.get("avisos")
