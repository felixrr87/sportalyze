# -*- coding: utf-8 -*-
"""
EL CAMPO NO ES PLANO
=====================
    python3 relieve.py

Calcula, con 29.224 tiros reales, la probabilidad de marcar desde
cada punto del campo, y la deja lista para dibujarla como un relieve.

QUÉ ES Y QUÉ NO ES
------------------
No es un modelo de xG. Un xG de verdad usa muchas más cosas: parte
del cuerpo, tipo de jugada, presión del defensa, posición del
portero. Esto usa UNA: desde dónde se tiró.

Y precisamente por eso sirve para lo que sirve: enseñar la forma del
terreno. Si metes más variables, el relieve deja de poder dibujarse
y pasa a ser una tabla.

CÓMO SE SUAVIZA, Y POR QUÉ IMPORTA
----------------------------------
Una rejilla cruda da celdas con tres tiros y un gol: 33 %. Eso no es
una montaña, es ruido con forma de montaña.

Aquí cada punto del relieve se calcula con una ventana gaussiana
sobre todos los tiros, y además se encoge hacia una base:

    p = (suma de pesos de los goles + k·base) / (suma de pesos + k)

Con k = 60, una zona con pocos tiros se queda pegada a la base en
vez de inventarse un pico. Las montañas que quedan son las que
aguantan.

EL ERROR QUE TUVE QUE DESHACER, Y POR QUÉ LO DEJO ESCRITO
---------------------------------------------------------
La primera versión encogía hacia la MEDIA GENERAL (14,9 %). Suena
razonable y es falso, y además de una forma que se veía a simple
vista en cuanto lo dibujé en relieve:

    · a 45 metros, de frente .......... decía 13,9 %  (hay 17 tiros)
    · en la línea de gol, junto al córner  decía 20,7 %

Eso no era el dato: era la media general asomando por donde no hay
datos. Una zona sin tiros no se parece al tiro medio; no se parece a
nada, y rellenarla con el promedio es inventar.

La base ahora es un modelo logístico ajustado a los 29.224 tiros con
dos variables, el logaritmo de la distancia y el logaritmo del
ángulo. Donde hay datos manda la ventana; donde no los hay, el
relieve enseña lo que predice ese modelo, que en el córner dice 1 % y
no 20 %.

EL SEGUNDO ERROR: LA VENTANA ESTABA EN EL SITIO EQUIVOCADO
----------------------------------------------------------
La ventana gaussiana era de 3,2 metros SOBRE EL CÉSPED, y eso rompe
justo donde está lo interesante. En un punto escorado a 14 metros, un
círculo de 3,5 m alrededor incluye posiciones de 6 grados y de 25:
el promedio salía 8,6 % cuando los tiros de ese sitio exacto marcan
el 1,3 %. La ventana se estaba tragando el acantilado.

Ahora la ventana no se mide en metros de césped sino en las dos
cosas que de verdad mandan: 1,8 metros de distancia y 3 grados de
ángulo. Dos puntos a la misma distancia pero con ángulos distintos ya
no se mezclan, que era todo el problema.

Efecto secundario que conviene decir: el relieve sale simétrico, y lo
es a propósito. Sólo depende de la distancia y del ángulo, así que
no recoge la asimetría de zurdos y diestros. Esa no la estoy
modelando y no quiero fingir que sí.
"""
import os

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))

# Campo real en metros; el dato viene en 120 x 80
LARGO, ANCHO = 105.0, 68.0
PORTERIA = 7.32
GX, GY = LARGO, ANCHO / 2

# Las ventanas van en LOGARITMO de la distancia y del ángulo, o sea
# en porcentaje y no en unidades fijas: 14 % de la distancia y 16 %
# del ángulo. Con una ventana fija en grados, cerca de la portería el
# ángulo cambia tan deprisa que cada celda miraba un puñado distinto
# de tiros y el relieve salía con púas.
H_DIST = 0.14
H_ANG = 0.16
K = 120.0          # fuerza del encogimiento hacia la base

# DÓNDE SE DIBUJA EL RELIEVE, Y POR QUÉ NO EN TODO EL CAMPO
# ---------------------------------------------------------
# Fuera de estos límites hay datos, pero son cuatro tiros y dicen
# cosas imposibles. Dos ejemplos de los que me salieron:
#
#   · a menos de 1,5 m de la línea: 15 tiros, 93 % de gol. Puede que
#     sea verdad, pero con quince tiros no lo sé, y dibujado como
#     relieve era una aguja de cincuenta metros que tapaba el resto.
#   · a 30 m con el ángulo casi cerrado: 19 tiros, 53 % de gol. Eso
#     no es que sea dudoso, es que no puede ser.
#
# Así que el relieve sólo existe donde se puede medir: entre 4 y 32
# metros, y con al menos 40 tiros equivalentes detrás de cada punto.
# Lo demás se queda como césped. Prefiero un relieve con bordes a un
# relieve que se inventa las esquinas.
#
# Y el agujero de dentro se tapa CONGELANDO el relieve del borde:
# cada punto a menos de 4 metros copia la altura que hay en su misma
# dirección a 4 metros exactos. Es una meseta con la forma del borde,
# no un disco plano.
#
# Probé las otras dos y las dos estaban mal. Dejar el agujero abierto
# partía la cima en tres torres que parecían un fallo de dibujo.
# Taparlo con un disco plano a la altura MEDIA del borde hacía que
# por el centro el relieve subiera a 51 % y luego bajara a 39: un
# cráter inventado. Lo pilló la comprobación del perfil, no el ojo.
#
# Congelar el borde significa, y así lo dice el rótulo: «aquí dejo
# de medir», no «aquí vale esto».
D_MIN, D_MAX = 4.0, 32.0
N_MIN = 40.0


def cargar():
    d = np.load(os.path.join(AQUI, "tiros.npz"), allow_pickle=True)
    m = ~d["penalti"]
    x = d["x0"][m] * LARGO / 120.0
    y = d["y0"][m] * ANCHO / 80.0
    g = d["gol"][m].astype(float)
    return x, y, g


def distancia(x, y):
    return np.hypot(GX - x, GY - y)


def angulo(x, y):
    """Grados de portería que se ven desde ese punto."""
    a = np.arctan2(GY - PORTERIA / 2 - y, GX - x)
    b = np.arctan2(GY + PORTERIA / 2 - y, GX - x)
    return np.degrees(np.abs(b - a))


def _diseno(x, y):
    """Las dos variables del modelo base: log(distancia) y log(ángulo)."""
    d = np.clip(distancia(x, y), 0.5, None)
    a = np.clip(angulo(x, y), 0.2, None)
    return np.column_stack([np.ones(len(np.atleast_1d(d))),
                            np.log(d), np.log(a)])


def base_logistica(x, y, g, vueltas=40):
    """Ajusta logit(p) = b0 + b1·log(d) + b2·log(ángulo) por IRLS.

    Newton a pelo, sin librerías: en cada vuelta se resuelve un
    mínimo cuadrado ponderado. Con 29.224 filas y 3 columnas converge
    en menos de diez vueltas.
    """
    A = _diseno(x, y)
    b = np.zeros(A.shape[1])
    for _ in range(vueltas):
        p = 1 / (1 + np.exp(-A @ b))
        w = np.clip(p * (1 - p), 1e-6, None)
        H = A.T @ (A * w[:, None]) + 1e-6 * np.eye(A.shape[1])
        paso = np.linalg.solve(H, A.T @ (g - p))
        b = b + paso
        if np.abs(paso).max() < 1e-9:
            break
    return b


def predecir(b, x, y):
    x = np.atleast_1d(np.asarray(x, float))
    y = np.atleast_1d(np.asarray(y, float))
    return 1 / (1 + np.exp(-(_diseno(x, y) @ b)))


def _estimar(px, py, x, y, g, b, hd=H_DIST, ha=H_ANG, k=K):
    """Probabilidad y tiros equivalentes en puntos sueltos cualesquiera.

    Es el corazón del relieve, y está suelto a propósito: la rejilla
    lo llama fila a fila, y el relleno de la cima lo llama en puntos
    que no caen en ninguna celda. Antes el relleno copiaba del vecino
    más cercano de la rejilla y heredaba sus agujeros: la meseta
    salía con once muescas negras, que en el vídeo parecían un fallo
    de dibujo y eran un fallo de verdad.
    """
    px = np.atleast_1d(np.asarray(px, float))
    py = np.atleast_1d(np.asarray(py, float))
    ld = np.log(np.clip(distancia(x, y), 0.5, None))
    la = np.log(np.clip(angulo(x, y), 0.2, None))
    LD = np.log(np.clip(distancia(px, py), 0.5, None))
    LA = np.log(np.clip(angulo(px, py), 0.2, None))
    q = (((ld[None, :] - LD[:, None]) / hd) ** 2
         + ((la[None, :] - LA[:, None]) / ha) ** 2)
    w = np.exp(-q / 2)
    sw = w.sum(1)
    return (w @ g + k * predecir(b, px, py)) / (sw + k), sw


def superficie(x, y, g, x0=66.0, paso=0.9, hd=H_DIST, ha=H_ANG, k=K):
    """Probabilidad de gol en cada punto de una rejilla.

    Devuelve (X, Y, P, N, M):
      P  probabilidad, NaN donde no hay con qué medirla
      N  tiros equivalentes detrás de cada punto
      M  máscara de dónde sí se puede dibujar
    """
    # La rejilla NO pasa de la línea de gol ni de las bandas. Dejarla
    # desbordar ponía la cima en x = 106 m, es decir, un metro por
    # detrás de la portería, desde donde no se ha tirado nunca.
    xs = np.arange(x0, LARGO + 1e-9, paso)
    ys = np.arange(0, ANCHO + 1e-9, paso)
    X, Y = np.meshgrid(xs, ys)
    P = np.zeros(X.shape)
    N = np.zeros(X.shape)
    b = base_logistica(x, y, g)
    D = distancia(X, Y)
    for i in range(X.shape[0]):
        P[i], N[i] = _estimar(X[i], Y[i], x, y, g, b, hd, ha, k)
    M = (D >= D_MIN) & (D <= D_MAX) & (N >= N_MIN)
    P = np.where(M, P, np.nan)
    dentro = D < D_MIN
    if dentro.any():
        # Cada punto interior copia el relieve de su misma dirección a
        # D_MIN exactos, calculado ahí mismo y no leído de la rejilla.
        # Justo en la boca de gol la dirección no existe (D = 0), así
        # que se toma la de frente.
        i_, j_ = np.where(dentro)
        dd = np.maximum(D[i_, j_], 1e-9)
        esc = D_MIN / dd
        rx = np.where(dd < 0.1, GX - D_MIN, GX + (X[i_, j_] - GX) * esc)
        ry = np.where(dd < 0.1, GY, GY + (Y[i_, j_] - GY) * esc)
        P[i_, j_], _ = _estimar(rx, ry, x, y, g, b, hd, ha, k)
        M = M | dentro
    return X, Y, P, N, M


def el_acantilado(x, y, g):
    """La comparación que sostiene el post: misma distancia, otro ángulo."""
    d, a = distancia(x, y), angulo(x, y)
    base = (d >= 12) & (d < 16)
    abierto = base & (a >= 25)
    cerrado = base & (a < 12)
    def tasa(s):
        n = int(s.sum()); p = 100 * g[s].mean()
        e = 196 * np.sqrt((p / 100) * (1 - p / 100) / n)
        return n, p, e
    return tasa(abierto), tasa(cerrado)


# Los dos puntos que se señalan en el vídeo. Están a la MISMA
# distancia de la portería a propósito: es toda la gracia del asunto.
# De frente, el ángulo pasa de 29 grados; escorado, no llega a 12.
# El escorado va al lado de acá (y < 34) a propósito: el relieve es
# simétrico, así que da igual el lado, y desde la cámara del vídeo
# éste es el que no queda tapado por la montaña.
DE_FRENTE = (91.0, 34.0)
ESCORADO = (100.0, 20.9)


def los_dos_puntos():
    """(punto, distancia, ángulo) de los dos ejemplos del vídeo."""
    fuera = []
    for px, py in (DE_FRENTE, ESCORADO):
        fuera.append(((px, py),
                      float(distancia(np.array([px]), np.array([py]))[0]),
                      float(angulo(np.array([px]), np.array([py]))[0])))
    return fuera


if __name__ == "__main__":
    x, y, g = cargar()
    d, a = distancia(x, y), angulo(x, y)
    print(f"{len(x)} tiros en juego · {int(g.sum())} goles · "
          f"{100*g.mean():.1f} % de conversión\n")

    print("POR DISTANCIA, mezclando todos los ángulos")
    for lo, hi in ((0, 6), (6, 9), (9, 12), (12, 16), (16, 20),
                   (20, 25), (25, 30)):
        s = (d >= lo) & (d < hi)
        print(f"   {lo:2d}–{hi:2d} m   n={int(s.sum()):5d}   {100*g[s].mean():5.1f} %")

    print("\nPOR ÁNGULO, fijando la distancia entre 12 y 18 m")
    b = (d >= 12) & (d < 18)
    for lo, hi in ((8, 14), (14, 20), (20, 28), (28, 40)):
        s = b & (a >= lo) & (a < hi)
        print(f"   {lo:2d}–{hi:2d}°   n={int(s.sum()):5d}   {100*g[s].mean():5.1f} %")

    (na, pa, ea), (nc, pc, ec) = el_acantilado(x, y, g)
    print(f"\nEL ACANTILADO · entre 12 y 16 metros de la portería")
    print(f"   ángulo abierto (>25°)   n={na:5d}   {pa:.1f} % ± {ea:.1f}")
    print(f"   ángulo cerrado (<12°)   n={nc:5d}   {pc:.1f} % ± {ec:.1f}")
    print(f"   ratio: {pa/pc:.1f} veces")

    b = base_logistica(x, y, g)
    pr = predecir(b, x, y)
    print("\nLA BASE LOGÍSTICA · ¿acierta? (deciles de lo que predice)")
    cortes = np.quantile(pr, np.linspace(0, 1, 11))
    for q in range(10):
        s = (pr >= cortes[q]) & (pr <= cortes[q + 1] if q == 9
                                 else pr < cortes[q + 1])
        print(f"   decil {q+1:2d}   predice {100*pr[s].mean():5.1f} %   "
              f"observado {100*g[s].mean():5.1f} %   n={int(s.sum())}")

    print("\n   y en los sitios donde antes mentía:")
    for px, py, que in ((60, 34, "45 m, de frente"),
                        (103, 2, "línea de gol, junto al córner"),
                        (91, 34, "14 m, de frente")):
        print(f"      {que:32s} {100*predecir(b, px, py)[0]:5.1f} %")

    print("\nLOS DOS PUNTOS DEL VÍDEO")
    for (px, py), dd, aa in los_dos_puntos():
        print(f"   ({px:.0f}, {py:.1f})   {dd:.1f} m de la portería   "
              f"{aa:.1f}° de ángulo")

    X, Y, P, N, M = superficie(x, y, g)
    print(f"\nRelieve: {P.shape[0]}x{P.shape[1]} puntos · "
          f"{100*M.mean():.0f} % de ellos con datos suficientes")
    print(f"   altura de {100*np.nanmin(P):.1f} % a {100*np.nanmax(P):.1f} %")
    i, j = np.unravel_index(np.nanargmax(P), P.shape)
    _d = distancia(X, Y)
    print(f"   meseta de la cima (dentro de {D_MIN:.0f} m): "
          f"{100*np.nanmin(P[_d < D_MIN]):.1f} % a "
          f"{100*np.nanmax(P[_d < D_MIN]):.1f} %")
    print(f"   cima en x={X[i,j]:.0f} m, y={Y[i,j]:.0f} m "
          f"({distancia(X[i,j],Y[i,j]):.1f} m de la portería)")

    # ── Comprobaciones ──
    assert len(x) > 28000
    assert 0.14 < g.mean() < 0.16
    # el pico tiene que estar cerca de la portería y centrado
    assert distancia(X[i, j], Y[i, j]) < 8, "la cima no está donde debe"
    # el perfil central tiene que subir sin baches hacia la portería
    fila = int(np.argmin(np.abs(Y[:, 0] - GY)))
    perfil = P[fila][np.isfinite(P[fila])]
    assert np.all(np.diff(perfil) > -0.015), "el perfil central da saltos atrás"
    assert abs(Y[i, j] - GY) < 8, "la cima no está centrada"
    # y el hallazgo que da título al post
    assert pa > 4 * pc, f"el acantilado se cae: {pa:.1f} vs {pc:.1f}"
    assert nc > 100, "muestra insuficiente en el ángulo cerrado"
    # el relieve no puede tener picos imposibles por falta de datos
    assert np.nanmax(P) < 0.60, f"pico de {100*np.nanmax(P):.0f} %: imposible"
    assert M.mean() > 0.35, "la máscara se ha comido casi todo el relieve"
    # y la rejilla no se sale del campo
    assert X.max() <= LARGO + 1e-6 and Y.max() <= ANCHO + 1e-6
    # la base tiene que estar calibrada: predicho y observado, cerca
    for q in range(10):
        s = (pr >= cortes[q]) & (pr <= cortes[q + 1] if q == 9
                                 else pr < cortes[q + 1])
        assert abs(pr[s].mean() - g[s].mean()) < 0.06, \
            f"base descalibrada en el decil {q+1}"
    # y no puede volver a decir que desde el córner se marca
    assert predecir(b, 103, 2)[0] < 0.05, "la base sigue inflando el córner"
    assert predecir(b, 60, 34)[0] < 0.05, "la base sigue inflando los 45 m"
    # el relieve tampoco, ya con la ventana encima
    for px, py in ((103, 2), (60, 34)):
        ii = int(np.argmin(np.abs(Y[:, 0] - py)))
        jj = int(np.argmin(np.abs(X[0, :] - px)))
        assert not np.isfinite(P[ii, jj]) or P[ii, jj] < 0.10, \
            f"el relieve dice {100*P[ii,jj]:.0f} % en ({px}, {py})"
    # los dos puntos del vídeo: misma distancia, ángulos de otro mundo
    (_, d1, a1), (_, d2, a2) = los_dos_puntos()
    assert abs(d1 - d2) < 0.3, f"no están a la misma distancia: {d1} vs {d2}"
    assert a1 > 25 and a2 < 12, f"los ángulos no son los del hallazgo: {a1}, {a2}"
    print("\nTodas las comprobaciones pasan.")
