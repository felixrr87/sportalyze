# -*- coding: utf-8 -*-
"""
PUENTE A LA COMPROBACIÓN DE LA MAQUETA
======================================
    python3 -m pytest tests/test_maqueta.py -v

Ejecuta los comprobadores de tests/maqueta/, que cargan el index.html
de verdad en un DOM y comprueban que las pantallas pintan los números
del modelo: comprobar.js el Simulador y comprobar_informe.js el informe
post-partido. Ver tests/maqueta/LEEME.md.

SE SALTA, NO FALLA, si no hay node o falta jsdom: el proyecto tiene que
poder probarse entero sin node instalado. Lo que no puede es dar por
buena la maqueta sin mirarla, y por eso cuando node está, esto corre.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

AQUI = os.path.dirname(os.path.abspath(__file__))
MAQ = os.path.join(AQUI, "maqueta")
sys.path.insert(0, os.path.dirname(AQUI))


def _node():
    return shutil.which("node")


def _jsdom():
    return os.path.isdir(os.path.join(MAQ, "node_modules", "jsdom"))


@pytest.mark.skipif(not _node(), reason="no hay node instalado")
@pytest.mark.skipif(not _jsdom(),
                    reason="falta jsdom: cd tests/maqueta && npm install")
def test_la_maqueta_pinta_los_numeros_del_modelo():
    # la edición, calculada con el motor en este mismo momento
    from backend.ml import simulador as S
    with open(os.path.join(AQUI, "datos", "laliga_2026_27.json"),
              encoding="utf-8") as fh:
        crudos = json.load(fh)
    ed = S.edicion(crudos, "PD", "La Liga", hoy="2026-09-22")
    ruta_ed = os.path.join(MAQ, "edicion.json")
    with open(ruta_ed, "w", encoding="utf-8") as fh:
        json.dump(ed, fh, ensure_ascii=False)

    _correr("comprobar.js", ruta_ed, "Toda la maqueta cuadra")


@pytest.mark.skipif(not _node(), reason="no hay node instalado")
@pytest.mark.skipif(not _jsdom(),
                    reason="falta jsdom: cd tests/maqueta && npm install")
def test_el_informe_pintado_es_el_dato():
    """Lo que de verdad busca: que ningún tiro esté en el campo
    equivocado. StatsBomb da las coordenadas con el atacante yendo
    siempre hacia la misma portería, así que al visitante hay que
    darle la vuelta. Si no se hace, el mapa parece correcto y los dos
    equipos disparan al mismo sitio."""
    import gzip
    from backend.ml import informe as I

    def gz(n):
        with gzip.open(os.path.join(AQUI, "datos", n), "rt", encoding="utf-8") as fh:
            return json.load(fh)

    with open(os.path.join(AQUI, "datos", "final_mundial_2022_ficha.json"),
              encoding="utf-8") as fh:
        ficha = json.load(fh)
    informe = I.informe(gz("final_mundial_2022_eventos.json.gz"), ficha,
                        gz("final_mundial_2022_alineaciones.json.gz"))
    ruta = os.path.join(MAQ, "informe.json")
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump(informe, fh, ensure_ascii=False)

    _correr("comprobar_informe.js", ruta, "Todo el informe pintado cuadra")


@pytest.mark.skipif(not _node(), reason="no hay node instalado")
@pytest.mark.skipif(not _jsdom(),
                    reason="falta jsdom: cd tests/maqueta && npm install")
def test_todas_las_pantallas_estan_explicadas():
    """Cada pantalla, su explicación: el método arriba y la versión en
    cristiano debajo. Y que ninguna prometa lo que el código no hace.

    Lo encontró a la primera: en Partidos y en Watchlist la explicación
    desaparecía, porque esas dos pantallas reescriben su propio .cont y
    se la llevaban por delante al cargar los datos. Dos de doce, que es
    como no verlo nunca.
    """
    _correr("comprobar_explicaciones.js", None, "Todas las pantallas explicadas")


@pytest.mark.skipif(not _node(), reason="no hay node instalado")
@pytest.mark.skipif(not _jsdom(),
                    reason="falta jsdom: cd tests/maqueta && npm install")
def test_el_scouting_pintado_es_el_dato():
    """Scouting, ficha de jugador y Comparador contra el motor de verdad.

    La respuesta que se le sirve a la pantalla NO es un JSON escrito a
    mano: sale de run_scouting_pipeline, el mismo código que corre en
    producción. Así, si el motor cambia de forma, esta prueba se entera.

    Lo que busca, en una frase: que la pantalla no toque el dato. La
    versión anterior del mapa de talento le sumaba Math.random() a las
    coordenadas para separar los puntos que se solapaban, y dos
    jugadores que caen encima es justo el dato que había que ver.
    """
    from tests.fabricar_fixture import main as fabricar
    fabricar()
    _correr("comprobar_scouting.js",
            os.path.join(AQUI, "datos", "scouting_fixture.json"),
            "lo pintado es el dato",
            os.path.join(AQUI, "datos", "tiros_fixture.json"))


@pytest.mark.skipif(not _node(), reason="no hay node instalado")
@pytest.mark.skipif(not _jsdom(),
                    reason="falta jsdom: cd tests/maqueta && npm install")
def test_el_informe_del_partido_pintado_es_el_dato():
    """La pantalla que sale al pinchar un partido en Partidos.

    El informe se calcula AQUÍ con el motor de verdad y se le sirve a
    la pantalla, así que si el motor cambia de forma esto se entera.

    Lo que más busca: que cada equipo ataque hacia su lado. Understat
    da las coordenadas con el que tira yendo siempre hacia la misma
    portería; si al visitante no se le da la vuelta —o se le da sólo
    en x— el mapa sigue pareciendo un mapa y cuenta otra cosa.
    """
    _correr("comprobar_informe_partido.js",
            os.path.join(AQUI, "datos", "informe_partido_fixture.json"),
            "Todo el informe del partido cuadra con el dato")


def _correr(script, datos, frase, datos2=None):
    index = os.path.join(os.path.dirname(AQUI), "frontend", "index.html")
    argumentos = [_node(), os.path.join(MAQ, script), index]
    if datos:
        argumentos.append(datos)
    if datos2:
        argumentos.append(datos2)
    r = subprocess.run(
        argumentos,
        capture_output=True, text=True, timeout=180, cwd=MAQ)
    # La salida del comprobador se imprime siempre: si falla, ahí está
    # la línea que dice qué no cuadra.
    print(r.stdout)
    if r.stderr.strip():
        print("── stderr ──\n" + r.stderr)
    assert r.returncode == 0, f"{script}: lo pintado no cuadra con el dato"
    assert frase in r.stdout
