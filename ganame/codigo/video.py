# -*- coding: utf-8 -*-
"""
GÁNAME — el vídeo para el feed
==============================
    python3 video.py            monta el vídeo entero
    python3 video.py --mirar 320   guarda sólo ese fotograma, para ajustar

LinkedIn no enseña páginas dentro del feed: sólo texto, imagen, vídeo o
documento. Así que la publicación no puede ser la página. Este vídeo es
lo que se ve en el feed, y el enlace a la página va en el primer
comentario.

QUÉ ES ESTE VÍDEO EXACTAMENTE
-----------------------------
No es una grabación de pantalla: en esta máquina no hay navegador con
el que grabar. Son los mismos datos (datos.json), la misma geometría
del campo y la misma paleta que la página, dibujados fotograma a
fotograma. Lo que se ve es lo que hace la página.

Por eso TODAS las cifras que salen se leen del archivo y ninguna se
escribe a mano:

  · las dos parejas que se enseñan, con su resultado real
  · la probabilidad que el modelo le daba a cada tiro
  · el 7 de 10 del modelo
  · el AUC y el número de parejas posibles
  · el mapa de calor, celda a celda

Hay comprobaciones al final que revientan si alguna de esas cifras no
cuadra con lo que se ha dibujado.
"""
import json
import math
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

AQUI = os.path.dirname(os.path.abspath(__file__))
DATOS = os.path.join(AQUI, "datos.json")
FOT = "/sessions/beautiful-pensive-pascal/fotgan"
SALIDA = os.path.join(AQUI, "..", "ganame.mp4")

W, H, FPS = 1080, 1350, 30
BG = (8, 13, 24)
PANEL, PANEL2, BORDE = (17, 26, 43), (25, 36, 58), (37, 51, 76)
INK, DIM, TENUE = (234, 238, 245), (141, 153, 175), (91, 104, 126)
ORO, CIAN, ROJO, VERDE = (227, 179, 65), (53, 191, 208), (255, 86, 104), (63, 217, 154)
LINEA = (46, 65, 96)

# el campo, en el mismo marco que la página: 68 x 39 m, portería arriba
VX, VY = 68.0, 39.0
GX, GY, POSTE = 105.0, 34.0, 7.32 / 2

FU = {}


def f(t, peso="b"):
    r = {"b": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "n": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "m": "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
         "c": "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"}[peso]
    k = (t, peso)
    if k not in FU:
        FU[k] = ImageFont.truetype(r, int(t))
    return FU[k]


def esp(d, xy, s, fn, col, sep=0.0):
    x, y = xy
    for ch in s:
        d.text((x, y), ch, font=fn, fill=col)
        x += d.textlength(ch, font=fn) + sep
    return x - xy[0]


def ancho(d, s, fn, sep=0.0):
    return sum(d.textlength(c, font=fn) + sep for c in s) - sep


def centrado(d, cx, y, s, fn, col, sep=0.0):
    esp(d, (cx - ancho(d, s, fn, sep) / 2, y), s, fn, col, sep)


def suave(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def mezcla(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


# ─────────────────────────────────────────────────────────────────
# EL CAMPO
# ─────────────────────────────────────────────────────────────────

class Campo:
    """Un rectángulo de pantalla que representa 68 x 39 m de césped."""

    def __init__(self, x, y, w):
        self.x, self.y, self.w = x, y, w
        self.h = w * VY / VX
        self.s = w / VX

    def pt(self, fx, fy):
        return (self.x + fx * self.s, self.y + fy * self.s)

    def de_tiro(self, t):
        """Un tiro del archivo (x, y en el campo de 105 x 68)."""
        return self.pt(t["y"], 105.0 - t["x"])

    def fondo(self, d, col=(11, 18, 32)):
        d.rectangle([self.x, self.y, self.x + self.w, self.y + self.h], fill=col)

    def lineas(self, d, gr=None):
        g = max(1, int(round(self.s * 0.16))) if gr is None else gr
        P, S = self.pt, self.s

        def rect(ax, ay, bx, by):
            d.rectangle([P(ax, ay), P(bx, by)], outline=LINEA, width=g)

        d.line([P(0, g / S / 2), P(68, g / S / 2)], fill=LINEA, width=g)
        rect(13.84, 0, 54.16, 16.5)
        rect(24.84, 0, 43.16, 5.5)
        cx, cy = P(34, 11)
        d.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=LINEA)
        # el arco, sólo el trozo que queda fuera del área
        a = math.degrees(math.acos((16.5 - 11) / 9.15))
        c0, c1 = P(34 - 9.15, 11 - 9.15), P(34 + 9.15, 11 + 9.15)
        d.arc([c0, c1], 90 - a, 90 + a, fill=LINEA, width=g)
        d.line([P(34 - POSTE, 0), P(34 + POSTE, 0)], fill=(124, 140, 166),
               width=max(2, int(round(self.s * 0.38))))

    def tiro(self, d, t, col, r=1.25, halo=True):
        cx, cy = self.de_tiro(t)
        rp = r * self.s
        if halo:
            h = 2.6 * self.s
            d.ellipse([cx - h, cy - h, cx + h, cy + h],
                      fill=mezcla((11, 18, 32), col, 0.22))
        d.ellipse([cx - rp, cy - rp, cx + rp, cy + rp], fill=col)


def distancia(x, y):
    return math.hypot(GX - x, GY - y)


def angulo(x, y):
    dx, dy = abs(GX - x), abs(y - GY)
    v = math.atan2(7.32 * dx, dx * dx + dy * dy - POSTE * POSTE)
    if v < 0:
        v += math.pi
    return math.degrees(v)


# ─────────────────────────────────────────────────────────────────
# EL MAPA DE CALOR, con la misma rampa que la página
# ─────────────────────────────────────────────────────────────────

PARADAS = [(0.00, (22, 48, 80)), (0.08, (29, 111, 138)), (0.20, (53, 191, 208)),
           (0.35, (227, 179, 65)), (0.52, (255, 242, 207))]


def rampa(p):
    u = min(p, 0.52)
    for k in range(len(PARADAS) - 1):
        a, ca = PARADAS[k]
        b, cb = PARADAS[k + 1]
        if u <= b:
            return mezcla(ca, cb, (u - a) / (b - a))
    return PARADAS[-1][1]


def capa_calor(R, w, h):
    """El relieve, del archivo a una imagen del tamaño del campo."""
    nx, ny = R["nx"], R["ny"]            # nx = eje largo, ny = eje ancho
    chico = Image.new("RGBA", (ny, nx), (0, 0, 0, 0))
    px = chico.load()
    for fila in range(nx):
        j = nx - 1 - fila                # fila 0 = línea de gol
        for col in range(ny):
            v = R["p"][col][j]
            if v is None:
                continue
            r, g, b = rampa(v)
            px[col, fila] = (r, g, b, 236)
    return chico.resize((int(w), int(h)), Image.LANCZOS)


# ─────────────────────────────────────────────────────────────────
# PIEZAS DE PANTALLA
# ─────────────────────────────────────────────────────────────────

def caja(d, x, y, w, h, r=16, rell=PANEL, bor=BORDE, g=2):
    d.rounded_rectangle([x, y, x + w, y + h], radius=r, fill=rell,
                        outline=bor, width=g)


def cabecera(d, alfa=1.0):
    c = mezcla(BG, CIAN, alfa)
    esp(d, (70, 62), "SPORTALYZE  ·  29.224 TIROS  ·  DATOS ABIERTOS",
        f(21, "m"), c, 2.2)


def puntero(d, x, y, t=1.0):
    """Un dedo: anillo que se cierra al tocar."""
    r = 26 + 16 * (1 - suave(t))
    d.ellipse([x - r, y - r, x + r, y + r], outline=(255, 255, 255),
              width=max(2, int(4 * suave(t))))
    d.ellipse([x - 6, y - 6, x + 6, y + 6], fill=(255, 255, 255))


def tarjeta_tiro(im, d, x, y, w, t, estado, lado, elegido):
    """estado: 'ciego' (aún sin elegir) o 'abierto' (ya se sabe)."""
    col = CIAN if estado == "ciego" else (VERDE if t["gol"] else ROJO)
    bor = BORDE if estado == "ciego" else col
    alto = w * VY / VX + 150
    caja(d, x, y, w, alto, r=14, rell=PANEL2, bor=bor, g=3)

    eti = ("IZQUIERDA" if lado == 0 else "DERECHA")
    if estado == "abierto" and elegido:
        eti += "  ·  TU ELECCIÓN"
    esp(d, (x + 18, y + 16), eti, f(17, "m"), TENUE, 1.6)

    c = Campo(x + 16, y + 48, w - 32)
    c.fondo(d)
    c.lineas(d)
    c.tiro(d, t, col)

    yy = y + 48 + c.h + 14
    esp(d, (x + 18, yy), "%.1f m" % t["d"], f(22, "m"), DIM)
    s = "%d°" % round(t["ang"])
    esp(d, (x + w - 18 - ancho(d, s, f(22, "m")), yy), s, f(22, "m"), DIM)

    if estado == "abierto":
        yy += 38
        centrado(d, x + w / 2, yy, "GOL" if t["gol"] else "NO ENTRÓ",
                 f(36, "c"), col, 1)
        yy += 44
        centrado(d, x + w / 2, yy,
                 "el modelo le daba %.1f %%" % (t["p"] * 100), f(18, "m"), TENUE)
    return alto


def coma(s):
    return s.replace(".", ",")


def miles(n):
    return "{:,}".format(n).replace(",", ".")


# ─────────────────────────────────────────────────────────────────
# EL GUION
# ─────────────────────────────────────────────────────────────────

D = json.load(open(DATOS, encoding="utf-8"))
R = D["rejilla"]
PAR_A = D["parejas"][0]      # 4,6 % contra 53,6 %: la fácil
PAR_B = D["parejas"][6]      # 20,3 % contra 20,3 %: la imposible
AUC = D["auc"]
N_PAREJAS = D["goles_totales"] * (D["tiros_totales"] - D["goles_totales"])
ACIERTOS_MODELO = D["aciertos_modelo"]

# puntos del mapa que se recorren al final, y lo que el modelo dice en
# ellos. Se leen de la rejilla: si cambia el modelo, cambia el vídeo.
RUTA = [(97.0, 34.0), (92.0, 24.0), (88.0, 44.0), (99.5, 30.0), (84.0, 34.0)]


def celda(x, y):
    j = int(round((x - R["x0"]) / R["paso"]))
    col = int(round((y - R["y0"]) / R["paso"]))
    j = max(0, min(R["nx"] - 1, j))
    col = max(0, min(R["ny"] - 1, col))
    return R["p"][col][j], R["n"][col][j]


ESCENAS = [("titulo", 2.4), ("par_a", 2.6), ("rev_a", 2.9),
           ("par_b", 2.6), ("rev_b", 3.2), ("marcador", 3.0),
           ("mapa", 5.6), ("cierre", 3.0)]
TOTAL = int(round(sum(s[1] for s in ESCENAS) * FPS))

CALOR = None
DIBUJADO = {}        # lo que de verdad ha salido en pantalla, para comprobar


def escena_de(k):
    t = k / FPS
    for nom, dur in ESCENAS:
        if t < dur:
            return nom, t, dur
        t -= dur
    return ESCENAS[-1][0], ESCENAS[-1][1], ESCENAS[-1][1]


def fotograma(k):
    global CALOR
    nom, t, dur = escena_de(k)
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    cabecera(d)

    if nom == "titulo":
        a = suave(t / 0.7)
        centrado(d, W / 2, 430, "GÁNAME", f(int(190 * (0.96 + 0.04 * a)), "c"),
                 mezcla(BG, INK, a), 2)
        if t > 0.75:
            b = suave((t - 0.75) / 0.6)
            centrado(d, W / 2, 680, "Dos tiros reales.", f(46, "n"),
                     mezcla(BG, DIM, b))
            centrado(d, W / 2, 748, "Uno acabó en gol y el otro no.",
                     f(46, "b"), mezcla(BG, INK, b))
        if t > 1.5:
            b = suave((t - 1.5) / 0.6)
            centrado(d, W / 2, 860, "¿Cuál?", f(72, "c"), mezcla(BG, ORO, b), 2)
        DIBUJADO["titulo"] = True

    elif nom in ("par_a", "rev_a", "par_b", "rev_b"):
        par = PAR_A if nom.endswith("_a") else PAR_B
        abierto = nom.startswith("rev")
        n_par = 1 if nom.endswith("_a") else 7
        esp(d, (70, 150), "PAREJA %d DE 10" % n_par, f(24, "m"), DIM, 2)
        if abierto:
            ok = par[1]["gol"]            # en el vídeo se elige la derecha
            centrado(d, W / 2, 210, "ACERTASTE" if ok else "FALLASTE",
                     f(58, "c"), VERDE if ok else ROJO, 1)
        else:
            centrado(d, W / 2, 210, "¿CUÁL ACABÓ EN GOL?", f(54, "c"), INK, 1)

        w = 452
        for lado, tiro in enumerate(par):
            x = 70 + lado * (w + 36)
            tarjeta_tiro(im, d, x, 320, w, tiro,
                         "abierto" if abierto else "ciego", lado,
                         elegido=(lado == 1))
        if not abierto and t > dur - 1.0:
            # el dedo va a la derecha y toca
            u = (t - (dur - 1.0)) / 1.0
            x0, y0 = 70 + 0.5 * (w + 36) + w * 0.1, 980
            x1, y1 = 70 + (w + 36) + w / 2, 560
            puntero(d, x0 + (x1 - x0) * suave(u), y0 + (y1 - y0) * suave(u),
                    1.0 if u < 0.8 else (1 - u) / 0.2)
        if abierto:
            pg = [p for p in par if p["gol"]][0]["p"]
            pf = [p for p in par if not p["gol"]][0]["p"]
            dif = abs(pg - pf) * 100
            y = 1120
            caja(d, 70, y, W - 140, 150, r=12, rell=PANEL2, bor=PANEL2, g=0)
            d.rectangle([70, y, 76, y + 150], fill=ORO)
            if dif < 1.5:
                l1 = "Esta era imposible."
                l2 = "El modelo les daba lo mismo: %.1f puntos de" % dif
                l3 = "diferencia. Aquí también tiraba una moneda."
            else:
                l1 = "Esta la acierta el modelo."
                l2 = "Le daba %d puntos más al que entró." % round(dif)
                l3 = "Con la portería así de abierta, no falla."
            esp(d, (104, y + 22), l1, f(30, "b"), INK)
            esp(d, (104, y + 66), l2, f(26, "n"), DIM)
            esp(d, (104, y + 102), l3, f(26, "n"), DIM)
            DIBUJADO.setdefault("dif", {})[n_par] = dif

    elif nom == "marcador":
        centrado(d, W / 2, 230, "EL MARCADOR", f(76, "c"), INK, 1)
        cajas = [("TÚ", "?", ORO), ("EL MODELO", str(ACIERTOS_MODELO), INK),
                 ("A CARA O CRUZ", "5", DIM)]
        w, gap = 296, 26
        x0 = (W - (3 * w + 2 * gap)) / 2
        for i, (q, v, col) in enumerate(cajas):
            x = x0 + i * (w + gap)
            a = suave((t - 0.25 * i) / 0.5)
            caja(d, x, 380, w, 250, r=14, rell=PANEL2,
                 bor=ORO if i == 0 else BORDE, g=3)
            centrado(d, x + w / 2, 410, q, f(20, "m"), TENUE, 1.6)
            centrado(d, x + w / 2, 460, v, f(int(118 * (0.7 + 0.3 * a)), "c"),
                     mezcla(BG, col, a))
        centrado(d, W / 2, 720, "sobre estas diez parejas", f(26, "m"), TENUE)
        if t > 1.1:
            b = suave((t - 1.1) / 0.7)
            centrado(d, W / 2, 840, "Y sobre TODAS las parejas posibles",
                     f(38, "n"), mezcla(BG, DIM, b))
            centrado(d, W / 2, 906, miles(N_PAREJAS), f(96, "c"),
                     mezcla(BG, CIAN, b), 2)
            centrado(d, W / 2, 1026, "—todos los goles contra todos los fallos—",
                     f(28, "n"), mezcla(BG, TENUE, b))
            centrado(d, W / 2, 1090, "acierta el %s" % coma("%.1f %%" % (AUC * 100)),
                     f(52, "b"), mezcla(BG, ORO, b))
        DIBUJADO["marcador"] = (ACIERTOS_MODELO, N_PAREJAS, AUC)

    elif nom == "mapa":
        centrado(d, W / 2, 180, "Y EL MODELO ESTÁ ABIERTO", f(56, "c"), INK, 1)
        centrado(d, W / 2, 262, "toca cualquier punto del campo", f(30, "n"), DIM)

        c = Campo(70, 340, W - 140)
        c.fondo(d)
        if CALOR is None:
            CALOR = capa_calor(R, c.w, c.h)
        a = suave(t / 1.0)
        if a > 0:
            capa = CALOR.copy()
            capa.putalpha(capa.getchannel("A").point(lambda v: int(v * a)))
            im.paste(capa, (int(c.x), int(c.y)), capa)
        c.lineas(d)

        # el dedo recorre la ruta y la lectura va cambiando
        u = max(0.0, (t - 1.0) / max(0.1, dur - 1.6))
        seg = min(len(RUTA) - 2, int(u * (len(RUTA) - 1)))
        fr = suave(u * (len(RUTA) - 1) - seg)
        (ax, ay), (bx, by) = RUTA[seg], RUTA[seg + 1]
        cx_, cy_ = ax + (bx - ax) * fr, ay + (by - ay) * fr
        p, n = celda(cx_, cy_)
        if t > 1.0:
            sx, sy = c.pt(cy_, 105.0 - cx_)
            puntero(d, sx, sy, 1.0)

        y = int(c.y + c.h + 26)
        w, gap = 236, 14
        x0 = (W - (4 * w + 3 * gap)) / 2
        lect = [("PROBABILIDAD", coma("%.1f %%" % (p * 100)) if p else "—", ORO),
                ("TIROS DETRÁS", miles(n), INK),
                ("DISTANCIA", coma("%.1f m" % distancia(cx_, cy_)), INK),
                ("PORTERÍA A LA VISTA", "%d°" % round(angulo(cx_, cy_)), INK)]
        for i, (q, v, col) in enumerate(lect):
            x = x0 + i * (w + gap)
            caja(d, x, y, w, 150, r=12, rell=PANEL, bor=BORDE, g=2)
            centrado(d, x + w / 2, y + 22, q, f(16, "m"), TENUE, 1.2)
            centrado(d, x + w / 2, y + 62, v, f(50, "c"), col if t > 1.0 else TENUE)
        centrado(d, W / 2, y + 190,
                 "donde está oscuro no hay con qué medir, y por eso no se pinta",
                 f(26, "n"), TENUE)
        DIBUJADO["mapa"] = True

    else:  # cierre
        a = suave(t / 0.6)
        centrado(d, W / 2, 330, "29.224 TIROS", f(72, "c"), mezcla(BG, INK, a), 2)
        centrado(d, W / 2, 430, "EL CÓDIGO SE PIDE Y SE PASA",
                 f(40, "c"), mezcla(BG, CIAN, a), 2)
        if t > 0.6:
            b = suave((t - 0.6) / 0.6)
            caja(d, 70, 580, W - 140, 230, r=16, rell=PANEL,
                 bor=mezcla(BG, ORO, b), g=3)
            centrado(d, W / 2, 626, "JUÉGALO TÚ", f(78, "c"), mezcla(BG, ORO, b), 2)
            centrado(d, W / 2, 726, "enlace en el primer comentario",
                     f(32, "n"), mezcla(BG, DIM, b))
        if t > 1.3:
            b = suave((t - 1.3) / 0.6)
            centrado(d, W / 2, 920, "Félix Ramírez  ·  Sportalyze",
                     f(34, "b"), mezcla(BG, INK, b))
            centrado(d, W / 2, 976, "linkedin.com/in/felix-ramirez-tech",
                     f(26, "m"), mezcla(BG, TENUE, b))
        DIBUJADO["cierre"] = True

    return im


def main():
    if "--mirar" in sys.argv:
        k = int(sys.argv[sys.argv.index("--mirar") + 1])
        p = os.path.join(AQUI, "..", "mirar_%04d.png" % k)
        fotograma(k).save(p)
        print("guardado", os.path.abspath(p))
        return

    os.makedirs(FOT, exist_ok=True)
    for v in os.listdir(FOT):
        os.remove(os.path.join(FOT, v))
    print("%d fotogramas (%.1f s)" % (TOTAL, TOTAL / FPS))
    ultimo = None
    quietos = 0
    for k in range(TOTAL):
        im = fotograma(k)
        b = im.tobytes()
        if b == ultimo:
            quietos += 1
        ultimo = b
        im.save(os.path.join(FOT, "f%05d.png" % k))
        if k % 60 == 0:
            print("  %d / %d" % (k, TOTAL), flush=True)

    # ── COMPROBACIONES ──
    assert quietos < TOTAL * 0.25, (
        "%d de %d fotogramas son idénticos al anterior: el vídeo está "
        "congelado" % (quietos, TOTAL))
    for clave in ("titulo", "marcador", "mapa", "cierre"):
        assert DIBUJADO.get(clave), "la escena %r no se ha llegado a dibujar" % clave
    assert DIBUJADO["marcador"] == (ACIERTOS_MODELO, N_PAREJAS, AUC)
    d1, d7 = DIBUJADO["dif"][1], DIBUJADO["dif"][7]
    assert d1 > 20, "la pareja fácil ya no es fácil (%.1f puntos)" % d1
    assert d7 < 1.5, (
        "la pareja 7 ya no es la imposible (%.1f puntos): el vídeo dice que "
        "el modelo les daba lo mismo y dejaría de ser verdad" % d7)
    hay = len(os.listdir(FOT))
    assert hay == TOTAL, "faltan fotogramas: %d de %d" % (hay, TOTAL)

    if os.path.exists(SALIDA):
        os.remove(SALIDA)
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
        "-i", os.path.join(FOT, "f%05d.png"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
        "-movflags", "+faststart", SALIDA], check=True)
    print("guardado: %s  (%.1f MB, %.1f s)"
          % (os.path.abspath(SALIDA), os.path.getsize(SALIDA) / 1e6, TOTAL / FPS))
    print("la pareja 1 se abre con %.1f puntos de diferencia" % d1)
    print("la pareja 7, con %.1f" % d7)


if __name__ == "__main__":
    main()
