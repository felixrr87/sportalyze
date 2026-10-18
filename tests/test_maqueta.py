# -*- coding: utf-8 -*-
"""
PUENTE A LA COMPROBACIÓN DE LA MAQUETA
======================================
    python3 -m pytest tests/test_maqueta.py -v

Ejecuta tests/maqueta/comprobar.js, que carga el index.html de verdad en
un DOM y comprueba que la pantalla del Simulador pinta los números del
modelo. Ver tests/maqueta/LEEME.md.

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

    index = os.path.join(os.path.dirname(AQUI), "frontend", "index.html")
    r = subprocess.run(
        [_node(), os.path.join(MAQ, "comprobar.js"), index, ruta_ed],
        capture_output=True, text=True, timeout=180, cwd=MAQ)
    # La salida del comprobador se imprime siempre: si falla, ahí está
    # la línea que dice qué no cuadra.
    print(r.stdout)
    if r.stderr.strip():
        print("── stderr ──\n" + r.stderr)
    assert r.returncode == 0, "la maqueta no cuadra con el modelo"
    assert "Toda la maqueta cuadra" in r.stdout
