# -*- coding: utf-8 -*-
"""
GÁNAME — el montador
====================
    python3 montar.py

Mete datos.json dentro de plantilla.html y saca la página final, que
funciona sola: sin servidor, sin llamadas a ningún sitio y sin que
haya que fiarse de nada que no venga en el propio archivo.

LA COMPROBACIÓN QUE IMPORTA
---------------------------
La página vuelve a calcular en JavaScript la distancia y el ángulo de
portería de cualquier punto que toques. Si esa fórmula no fuera la
misma que usa el modelo en Python, el mapa diría una cosa y la lectura
otra, y nadie se enteraría.

Así que aquí se reimplementa la fórmula del JavaScript en Python y se
compara con lo que devuelve relieve.py para los veinte tiros del juego
y para una rejilla de puntos repartidos por el campo. Si no cuadran,
no sale página.
"""
import json
import math
import os
import sys

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(
    AQUI, "..", "..", "PERSONAL_16_el-relieve", "codigo")))
import relieve  # noqa: E402

PLANTILLA = os.path.join(AQUI, "plantilla.html")
DATOS = os.path.join(AQUI, "datos.json")
# Dos salidas, y conviene saber por qué:
#   PAGINA   es el archivo que se publica. Va sin <!doctype>, sin <head>
#            y sin <meta charset> porque quien lo publica le pone esa
#            envoltura encima.
#   SUELTA   es el mismo contenido con la envoltura puesta, para poder
#            abrirlo con doble clic desde la carpeta. Sin el charset,
#            los acentos salen rotos.
PAGINA = os.path.join(AQUI, "ganame_pagina.html")
SUELTA = os.path.join(AQUI, "..", "ganame.html")

GX, GY, POSTE = 105.0, 34.0, 7.32 / 2


def angulo_js(x, y):
    """La fórmula tal y como está escrita en el <script> de la página."""
    dx, dy = abs(GX - x), abs(y - GY)
    v = math.atan2(7.32 * dx, dx * dx + dy * dy - POSTE * POSTE)
    if v < 0:
        v += math.pi
    return math.degrees(v)


def distancia_js(x, y):
    return math.hypot(GX - x, GY - y)


def comprobar(d):
    # 1 · la fórmula del navegador contra la del modelo
    puntos = [(t["x"], t["y"]) for par in d["parejas"] for t in par]
    for xx in np.arange(66.0, 105.1, 1.3):
        for yy in np.arange(2.0, 66.1, 2.9):
            puntos.append((float(xx), float(yy)))
    peor_a = peor_d = 0.0
    for x, y in puntos:
        peor_a = max(peor_a, abs(angulo_js(x, y) - float(relieve.angulo(x, y))))
        peor_d = max(peor_d, abs(distancia_js(x, y) - float(relieve.distancia(x, y))))
    print("puntos comprobados: %d" % len(puntos))
    print("  peor desvío de ángulo:    %.6f grados" % peor_a)
    print("  peor desvío de distancia: %.6f metros" % peor_d)
    assert peor_a < 1e-6, "el ángulo del navegador NO es el del modelo"
    assert peor_d < 1e-9, "la distancia del navegador NO es la del modelo"

    # 2 · que lo que dice el texto de la página es verdad
    assert d["aciertos_modelo"] == sum(
        1 for par in d["parejas"]
        if (par[0]["p"] > par[1]["p"]) == par[0]["gol"]), \
        "el marcador del modelo no cuadra con las parejas"
    assert all(sum(t["gol"] for t in par) == 1 for par in d["parejas"]), \
        "alguna pareja no tiene exactamente un gol"
    peor_cal = max(abs(c["dice"] - c["pasa"]) for c in d["calibracion"])
    assert peor_cal < 6.0, "la calibración no aguanta lo que dice el texto"
    tope = max(v for f in d["rejilla"]["p"] for v in f if v is not None)
    assert tope <= 0.60, "la rampa de color se queda corta: tope %.3f" % tope
    print("  el modelo acierta %d de 10 · peor decil %.1f pts · tope del mapa %.1f %%"
          % (d["aciertos_modelo"], peor_cal, tope * 100))


def main():
    with open(DATOS, encoding="utf-8") as fh:
        d = json.load(fh)
    comprobar(d)

    with open(PLANTILLA, encoding="utf-8") as fh:
        html = fh.read()
    assert html.count("__DATOS__") == 1, "la plantilla no tiene el hueco"
    html = html.replace("__DATOS__", json.dumps(
        d, ensure_ascii=False, separators=(",", ":")))

    # que no se haya colado nada que el navegador no pueda cargar
    for malo in ("http://", "fetch(", "XMLHttpRequest"):
        assert malo not in html, "la página depende de algo externo: %s" % malo
    assert "__DATOS__" not in html

    envoltura = (
        "<!doctype html>\n<html lang=\"es\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\""
        "width=device-width,initial-scale=1,viewport-fit=cover\">\n"
        "</head>\n<body style=\"margin:0\">\n%s\n</body>\n</html>\n")

    for ruta, texto in ((PAGINA, html), (SUELTA, envoltura % html)):
        if os.path.exists(ruta):
            os.remove(ruta)
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write(texto)
        print("guardado: %s  (%.0f KB)"
              % (os.path.abspath(ruta), os.path.getsize(ruta) / 1024))

    # que la versión suelta lleve de verdad el charset: sin él los
    # acentos salen como "GÃ¡name" y lo he visto pasar.
    with open(SUELTA, encoding="utf-8") as fh:
        suelta = fh.read()
    assert "charset=\"utf-8\"" in suelta[:200], "falta el charset"
    assert "[hidden]{display:none!important}" in suelta, (
        "sin esa regla, el marcador se ve antes de jugar")


if __name__ == "__main__":
    main()
