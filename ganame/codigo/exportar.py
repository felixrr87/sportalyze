# -*- coding: utf-8 -*-
"""
GÁNAME — el exportador
======================
    python3 exportar.py

Saca del modelo del relieve TODO lo que la página necesita para
funcionar sola en el navegador, sin servidor y sin trampa:

  · la superficie de probabilidad de gol en una rejilla del campo,
    calculada con el modelo de verdad (relieve.py), no con una
    aproximación hecha para que quede bonito
  · los tiros equivalentes detrás de cada punto, para poder decir
    «aquí no tengo con qué medir» en vez de inventar
  · diez PAREJAS de tiros reales: en cada una, uno acabó en gol y el
    otro no. El lector elige cuál entró

POR QUÉ PAREJAS Y NO TIROS SUELTOS
-----------------------------------
La primera versión enseñaba diez tiros sueltos y pedía una
probabilidad para cada uno. Era un juego roto: sólo el 14,9 % de los
tiros acaban en gol, así que se ganaba diciendo «no entra» diez veces
sin mirar la pantalla. La tirada con la semilla de siempre salió con
cero goles de diez y lo dejó claro.

No he cambiado la semilla hasta que saliera una muestra bonita. He
cambiado el juego, que era lo que estaba mal.

Con parejas de un gol y un fallo, el azar es exactamente el 50 % y la
puntuación se entiende sola. Y hay una ventaja: el acierto del modelo
en parejas así ES su AUC, una medida estándar que se puede comparar
con cualquier otro modelo de xG del mundo.

CÓMO SE ELIGEN LAS PAREJAS
---------------------------
  1. se parte de los 29.224 tiros en juego (sin penaltis)
  2. se sortea un gol y un fallo, al azar, con semilla fija
  3. se repite diez veces

Sin filtrar por dificultad. Habrá parejas fáciles y parejas imposibles,
que es justo la proporción que hay en el fútbol de verdad.
"""
import json
import os
import sys

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
RELIEVE = os.path.abspath(os.path.join(
    AQUI, "..", "PERSONAL_16_el-relieve", "codigo"))
sys.path.insert(0, RELIEVE)

import relieve  # noqa: E402

SEMILLA = 20261014
PASO = 0.9
SALIDA = os.path.join(AQUI, "datos.json")


def main():
    x, y, g = relieve.cargar()
    n_tiros, n_goles = len(x), int(g.sum())
    print("tiros en juego: %d   goles: %d" % (n_tiros, n_goles))

    # ── el modelo ────────────────────────────────────────────────
    b = relieve.base_logistica(x, y, g)
    # _estimar monta una matriz de puntos x tiros. Con 29.224 de cada
    # lado son 6,4 GB, así que se evalúa a trozos. El resultado es
    # idéntico: lo comprueba el assert de más abajo contra un trozo
    # calculado aparte.
    # _estimar monta una matriz de puntos x tiros. Con 29.224 de cada
    # lado son 6,4 GB y más de dos minutos, así que se evalúa a trozos
    # y se va guardando: si el proceso se corta, se reanuda donde iba.
    # El resultado es idéntico al de un solo tirón, y hay un assert
    # abajo que lo comprueba contra un trozo calculado aparte.
    CACHE = os.path.join(AQUI, "p_tiro.npy")
    TROZO = 2000
    if os.path.exists(CACHE):
        p_tiro = np.load(CACHE)
        assert p_tiro.shape == x.shape, "la caché no corresponde a estos tiros"
    else:
        p_tiro = np.full(x.shape, -1.0)
    import time as _t
    t0 = _t.time()
    for i in range(0, len(x), TROZO):
        s_ = slice(i, i + TROZO)
        if p_tiro[s_].min() >= 0:
            continue
        p_tiro[s_], _ = relieve._estimar(x[s_], y[s_], x, y, g, b)
        np.save(CACHE, p_tiro)
        hechos = int((p_tiro >= 0).sum())
        print("  %5d / %d tiros" % (hechos, len(x)), flush=True)
        if _t.time() - t0 > 130:
            print("PARO por tiempo. Vuelve a lanzarlo: sigue donde iba.")
            sys.exit(2)
    assert p_tiro.min() >= 0, "quedan tiros sin calcular"
    suelto, _ = relieve._estimar(x[:37], y[:37], x, y, g, b)
    assert np.allclose(p_tiro[:37], suelto), "trocear ha cambiado el resultado"

    brier_modelo = float(np.mean((p_tiro - g) ** 2))
    # Referencia tonta: decir siempre la media general.
    brier_media = float(np.mean((g.mean() - g) ** 2))
    print("Brier del modelo sobre los %d tiros: %.4f" % (n_tiros, brier_modelo))
    print("Brier de decir siempre la media:     %.4f" % brier_media)
    assert brier_modelo < brier_media, (
        "el modelo no mejora a decir siempre la media: no hay post")

    # calibración por deciles, que es lo que se publica
    orden = np.argsort(p_tiro)
    cal = []
    for t in np.array_split(orden, 10):
        cal.append({"dice": round(float(p_tiro[t].mean()) * 100, 1),
                    "pasa": round(float(g[t].mean()) * 100, 1),
                    "n": int(len(t))})
    peor = max(abs(c["dice"] - c["pasa"]) for c in cal)
    print("peor decil de calibración: %.1f puntos" % peor)
    assert peor < 6.0, "el modelo no está calibrado (%.1f puntos)" % peor

    # ── la superficie ────────────────────────────────────────────
    X, Y, P, N, M = relieve.superficie(x, y, g, paso=PASO)
    print("rejilla:", X.shape, " paso %.2f m" % PASO)
    assert np.nanmax(P) < 0.95 and np.nanmin(P[M]) >= 0.0

    rej = {
        "x0": float(X[0, 0]), "y0": float(Y[0, 0]), "paso": PASO,
        "nx": int(X.shape[1]), "ny": int(X.shape[0]),
        # se redondea a 4 decimales: 0,01 % de resolución, sobra
        "p": [[None if not M[i, j] else round(float(P[i, j]), 4)
               for j in range(X.shape[1])] for i in range(X.shape[0])],
        "n": [[int(round(N[i, j])) for j in range(X.shape[1])]
              for i in range(X.shape[0])],
    }

    # ── el AUC: con qué frecuencia el modelo ordena bien una pareja ──
    # Se calcula sobre TODAS las parejas gol/fallo posibles
    # (4.358 x 24.866 = 108 millones) con el estadístico de rangos, que
    # da el mismo número sin montarlas una a una.
    from scipy.stats import rankdata
    r = rankdata(p_tiro)
    n1 = int(g.sum())
    n0 = len(g) - n1
    auc = float((r[g == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))
    print("AUC del modelo: %.4f  (%.1f %% de las parejas bien ordenadas)"
          % (auc, auc * 100))
    assert 0.5 < auc < 0.9, "un AUC de %.3f no es creíble" % auc

    # ── las diez parejas ─────────────────────────────────────────
    rng = np.random.default_rng(SEMILLA)
    i_gol = np.flatnonzero(g == 1)
    i_no = np.flatnonzero(g == 0)
    parejas = []
    for _ in range(10):
        a = int(rng.choice(i_gol))
        b = int(rng.choice(i_no))
        lado = int(rng.integers(2))      # para que el gol no caiga siempre igual
        par = [a, b] if lado == 0 else [b, a]
        parejas.append([{
            "x": round(float(x[i]), 2), "y": round(float(y[i]), 2),
            "p": round(float(p_tiro[i]), 4), "gol": bool(g[i]),
            "d": round(float(relieve.distancia(x[i], y[i])), 1),
            "ang": round(float(relieve.angulo(x[i], y[i])), 1)} for i in par])

    vistos = [t["x"] * 1000 + t["y"] for par in parejas for t in par]
    assert len(set(vistos)) == 20, "hay un tiro repetido entre las parejas"
    aciertos_modelo = 0
    for par in parejas:
        assert sum(t["gol"] for t in par) == 1, "la pareja no tiene un gol y un fallo"
        for t in par:
            assert 0.0 <= t["ang"] <= 180.0, "ángulo imposible: %.1f" % t["ang"]
        if (par[0]["p"] > par[1]["p"]) == par[0]["gol"]:
            aciertos_modelo += 1
    izq = sum(par[0]["gol"] for par in parejas)
    print("el modelo acierta %d de las 10 parejas" % aciertos_modelo)
    print("el gol cae a la izquierda en %d de 10" % izq)
    assert 2 <= izq <= 8, "el gol cae casi siempre del mismo lado (%d)" % izq

    datos = {
        "tiros_totales": n_tiros, "goles_totales": n_goles,
        "media_gol": round(float(g.mean()), 4),
        "brier_modelo": round(brier_modelo, 4),
        "brier_media": round(brier_media, 4),
        "auc": round(auc, 4),
        "aciertos_modelo": aciertos_modelo,
        "calibracion": cal,
        "semilla": SEMILLA,
        "rejilla": rej,
        "parejas": parejas,
    }
    if os.path.exists(SALIDA):
        os.remove(SALIDA)
    with open(SALIDA, "w", encoding="utf-8") as fh:
        json.dump(datos, fh, ensure_ascii=False, separators=(",", ":"))
    print("guardado: %s  (%.0f KB)"
          % (SALIDA, os.path.getsize(SALIDA) / 1024))


if __name__ == "__main__":
    main()
