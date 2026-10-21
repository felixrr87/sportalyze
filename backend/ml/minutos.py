# -*- coding: utf-8 -*-
"""
QUIÉN ESTABA EN EL CAMPO EN CADA MINUTO
=======================================
Understat no publica el minuto de los cambios. Publica, por jugador y
por partido, dos cosas: cuántos minutos jugó y si salió de inicio o
entró desde el banquillo.

Con eso basta, y no es una suposición: es aritmética.

    · un titular empieza en el minuto 0, así que jugó de 0 a `time`
    · un suplente acaba en el 90, así que jugó de 90 − `time` a 90

Y se puede comprobar. En el Betis–Barcelona del 17 de octubre de 2026:

    Gerard Martín (titular)   53 min  → jugó del 0 al 53
    Eric García  (suplente)   37 min  → jugó del 53 al 90      53 + 37 = 90
    Lamine Yamal (titular)    77 min  → del 0 al 77
    Raphinha     (suplente)   13 min  → del 77 al 90           77 + 13 = 90

Los once del Barça suman 990 minutos exactos, que son 11 × 90. Cada
titular que sale tiene su suplente que entra con el complemento justo.

PARA QUÉ SIRVE ESTO
-------------------
Para medir a los defensas, que es lo que no se podía hacer.

Understat sólo publica tiros, así que de un central no hay entradas,
ni intercepciones, ni despejes: su ficha salía sin nota y con un
cartel explicando que esta fuente no da para eso.

Pero si sé en qué minutos estuvo cada uno en el campo, y sé el minuto
y el valor de cada tiro del rival, entonces puedo medir CUÁNTO XG
ENCAJA SU EQUIPO MIENTRAS ÉL JUEGA, y compararlo con lo que encaja
cuando él no está. Eso sí se puede calcular con lo que hay, y se
puede calcular para los once.

Lo que mide y lo que no, dicho desde ahora: mide cómo defiende el
EQUIPO con él en el campo, no lo que hace él. Un central en un equipo
que defiende bien sale bien aunque sea malo. Está lleno de ruido. Pero
es un dato de verdad, calculado con datos de verdad, y eso es más de
lo que había.

CUANDO LAS CUENTAS NO SALEN
---------------------------
Una expulsión rompe la aritmética: el expulsado se va y nadie entra en
su sitio, así que los minutos ya no suman 990 y el complemento de un
titular no aparece.

En ese caso NO se adivina. El partido se marca como no reconstruible y
se queda fuera del cálculo, diciéndolo. Un partido menos es mucho
mejor que un partido inventado.
"""

MINUTOS_PARTIDO = 90

# Cuántos minutos de diferencia se toleran al cuadrar las cuentas.
# Cero sería lo ideal; uno deja sitio a que una fuente redondee el
# descuento de otra manera.
TOLERANCIA = 1


class NoSePuedeReconstruir(Exception):
    """Las cuentas de ese partido no cuadran, así que no se inventa."""

    def __init__(self, motivo, detalle=""):
        self.motivo = motivo
        self.detalle = detalle
        super().__init__(f"{motivo}: {detalle}" if detalle else motivo)


def tramos(jugadores: list) -> list:
    """Para cada jugador, el tramo [desde, hasta] que estuvo en el campo.

    La lectura más probable. Si hay más de una, `soluciones` las da
    todas, y es `reparto_de_un_partido` quien decide si la duda
    importa.

    Lanza NoSePuedeReconstruir si las cuentas no cuadran.
    """
    return soluciones(jugadores)[0]


def _once_en_cada_minuto(tramos_: list) -> bool:
    return all(sum(1 for t in tramos_ if t["desde"] <= m < t["hasta"]) == 11
               for m in range(MINUTOS_PARTIDO))


def soluciones(jugadores: list) -> list:
    """TODAS las formas de colocar los cambios que cuadran.

    Normalmente hay una. Cuando hay varias es porque la fuente no da
    para distinguirlas: un hueco a los 60 y dos suplentes de 25 y 5
    minutos pueden ser «entra el de 25 y le cambian en el 85» o «entra
    el de 5, le cambian en el 65 y entra el de 25». Las dos lecturas
    son compatibles con lo que publica Understat.

    Que haya varias NO es motivo para tirar el partido: si los tiros
    caen fuera de los minutos en disputa, todas dan exactamente el
    mismo resultado. Por eso esto devuelve la lista y es
    `reparto_de_un_partido` quien decide, que es el único que sabe
    dónde cayeron los tiros.

    La primera es la más probable: la que menos cambios encadena.
    """
    if not jugadores:
        raise NoSePuedeReconstruir("sin_alineacion",
                                   "no hay jugadores para ese equipo")

    titulares = [j for j in jugadores if not j.get("suplente")]
    suplentes = [j for j in jugadores if j.get("suplente")
                 and (j.get("minutos") or 0) > 0]

    if len(titulares) != 11:
        raise NoSePuedeReconstruir(
            "titulares_raros",
            f"salen {len(titulares)} titulares y tienen que ser 11")

    total = sum((j.get("minutos") or 0) for j in titulares + suplentes)
    esperado = 11 * MINUTOS_PARTIDO
    if abs(total - esperado) > TOLERANCIA * 11:
        # Lo normal cuando pasa esto es una expulsión: el expulsado se
        # va y nadie entra en su sitio.
        raise NoSePuedeReconstruir(
            "minutos_no_cuadran",
            f"suman {total} y tendrían que sumar {esperado}; "
            f"suele ser una expulsión, y entonces no se puede saber "
            f"quién estaba en el campo en cada minuto")

    return _colocar(titulares, suplentes)


# Understat redondea los minutos al minuto, así que al otro lado de
# un cambio las cuentas se pueden ir de uno. Visto con el Barça:
#
#   Barcelona 5-2 Rayo   titulares salen en [68, 68, 81, 81]
#                        suplentes de [1, 9, 9, 22, 22] minutos
#
# Los huecos piden 22+22+9+9 = 62 minutos y los suplentes traen 63.
# Ese minuto de más es el del cambio: alguien entró en el 81, salió
# en el 82, y al que entró en su lugar le apuntaron 9 minutos cuando
# jugó 8.
#
# Exigiendo cuadre exacto se perdían dos de los nueve partidos del
# Barça, el 22 % de la temporada. Con un minuto de margen por hueco se
# recuperan, y un minuto mal repartido no mueve una tasa por 90
# minutos de forma apreciable.
MARGEN_POR_HUECO = 1


def _reparte_en_huecos(duraciones: list, huecos: list, margen: int):
    """Parte los suplentes en grupos, uno por hueco.

    Cada titular que sale en el minuto e abre un hueco de 90 − e
    minutos, que hay que tapar con una cadena de suplentes: el primero
    entra en e, y si a ése le cambian entra el siguiente, y así hasta
    el 90.

    O sea que esto es repartir las duraciones en grupos cuya suma sea
    la del hueco, con el margen. Devuelve TODAS las formas distintas,
    porque luego hay que ver si dan el mismo resultado.
    """
    salidas = []

    def busca(restantes, pendientes, acumulado):
        if len(salidas) > 400:      # un tope por si acaso
            return
        if not pendientes:
            if not restantes:
                salidas.append([list(g) for g in acumulado])
            return
        objetivo = pendientes[0]
        n = len(restantes)
        for mascara in range(1, 1 << n):
            grupo = [restantes[k] for k in range(n) if mascara >> k & 1]
            if abs(sum(d for _, d in grupo) - objetivo) > margen:
                continue
            quedan = [restantes[k] for k in range(n) if not mascara >> k & 1]
            busca(quedan, pendientes[1:], acumulado + [grupo])

    busca(list(duraciones), list(huecos), [])
    return salidas


def _colocar(titulares: list, suplentes: list) -> list:
    """Todas las formas de colocar los cambios que dejan once en cada minuto.

    CÓMO SE PLANTEA
    ---------------
    Cada titular que sale en el minuto e deja un hueco que va de e al
    90, y ese hueco lo tapa una cadena de suplentes: entra uno, y si a
    ése también le cambian entra otro.

    Así que colocar los cambios es repartir a los suplentes en grupos,
    uno por hueco, cuyas duraciones sumen lo que mide el hueco.

    UN SUPLENTE TAMBIÉN PUEDE SER SUSTITUIDO, y eso es justo lo que
    hace falta un grupo de dos o más. Salió probando con el Barça: dos
    de sus nueve partidos daban doce y trece jugadores en el campo en
    el minuto 89 con la regla sencilla de «un suplente acaba en el 90».

    Se devuelven TODAS las repartidas que cuadran, con la más probable
    primero: la que menos cambios encadena, porque que a un suplente
    le vuelvan a cambiar es raro. Quién decide si la duda importa es
    `reparto_de_un_partido`, el único que sabe dónde cayeron los tiros.
    """
    base = [{**j, "desde": 0,
             "hasta": min(j.get("minutos") or 0, MINUTOS_PARTIDO)}
            for j in titulares]

    huecos_min = sorted(t["hasta"] for t in base if t["hasta"] < MINUTOS_PARTIDO)

    if not suplentes:
        if huecos_min:
            raise NoSePuedeReconstruir(
                "once_imposible",
                f"salen titulares en los minutos {huecos_min} y no hay "
                f"suplentes que los sustituyan; suele ser una expulsión")
        if not _once_en_cada_minuto(base):
            raise NoSePuedeReconstruir(
                "once_imposible",
                "sin cambios y aun así no salen once en cada minuto")
        return [base]

    if not huecos_min:
        raise NoSePuedeReconstruir(
            "once_imposible",
            f"hay {len(suplentes)} suplentes con minutos y ningún titular "
            f"sale antes del 90")

    if len(suplentes) > 8:
        raise NoSePuedeReconstruir(
            "demasiados_cambios",
            f"{len(suplentes)} suplentes con minutos; son demasiadas "
            f"combinaciones para probarlas todas")

    duraciones = [(s, (s.get("minutos") or 0)) for s in suplentes]
    tamanos = [MINUTOS_PARTIDO - e for e in huecos_min]
    repartidas = _reparte_en_huecos(duraciones, tamanos, MARGEN_POR_HUECO)

    if not repartidas:
        raise NoSePuedeReconstruir(
            "once_imposible",
            f"ninguna forma de repartir los cambios cuadra. Salen titulares "
            f"en los minutos {huecos_min}, o sea huecos de {tamanos} minutos, "
            f"y hay suplentes de {[d for _, d in duraciones]} minutos. Lo "
            f"normal es que haya habido una expulsión")

    salidas, vistas = [], set()
    for reparto in repartidas:
        tramos_ = list(base)
        encadenados = 0
        # Dentro de cada hueco, el orden de la cadena importa: el
        # primero entra cuando sale el titular. Se prueban todos.
        from itertools import permutations, product
        for ordenes in product(*[list(permutations(g)) for g in reparto]):
            tramos_ = list(base)
            encadenados = 0
            ok = True
            for entrada, cadena in zip(huecos_min, ordenes):
                t = entrada
                for k, (jug, dur) in enumerate(cadena):
                    fin = t + dur
                    if k == len(cadena) - 1:
                        # el último de la cadena llega al final; aquí
                        # se absorbe el minuto de redondeo
                        fin = MINUTOS_PARTIDO
                    if fin > MINUTOS_PARTIDO or fin <= t:
                        ok = False
                        break
                    tramos_.append({**jug, "desde": t, "hasta": fin})
                    t = fin
                    if k < len(cadena) - 1:
                        encadenados += 1
                if not ok:
                    break
            if not ok or not _once_en_cada_minuto(tramos_):
                continue
            huella = tuple(sorted(
                (str(t.get("player_id") or t.get("nombre")), t["desde"], t["hasta"])
                for t in tramos_))
            if huella in vistas:
                continue
            vistas.add(huella)
            por_entrada = sorted((t for t in tramos_ if t.get("suplente")),
                                 key=lambda t: t["desde"])
            salidas.append((encadenados,
                            [-(t["hasta"] - t["desde"]) for t in por_entrada],
                            tramos_))

    if not salidas:
        raise NoSePuedeReconstruir(
            "once_imposible",
            f"los cambios se pueden repartir en los huecos pero ninguna "
            f"colocación deja once jugadores en cada minuto. Huecos de "
            f"{tamanos} minutos, suplentes de {[d for _, d in duraciones]}")

    salidas.sort(key=lambda x: (x[0], x[1]))
    return [t for _, _, t in salidas]


def xg_en_el_tramo(tiros: list, desde: int, hasta: int) -> float:
    """El xG de los tiros que caen dentro de un tramo de minutos."""
    return round(sum(float(t.get("xg", t.get("xG", 0)) or 0) for t in tiros
                     if desde <= int(t.get("minuto", t.get("minute", 0)) or 0) < hasta), 4)


# Cuánto xG puede bailar un jugador entre dos lecturas antes de que
# la duda deje de ser un detalle. 0,10 de xG es menos de lo que vale
# un tiro flojo desde fuera del área.
UMBRAL_DE_DUDA = 0.10


def reparto_de_un_partido(jugadores: list, tiros_a_favor: list,
                          tiros_en_contra: list) -> dict:
    """Por jugador, el xG a favor y en contra mientras estuvo jugando.

    Y también el de los minutos en que NO estuvo, que es con lo que hay
    que compararlo: un equipo que encaja poco hace que todos sus
    jugadores parezcan buenos defendiendo.

    CUANDO HAY VARIAS LECTURAS POSIBLES
    -----------------------------------
    A veces los minutos admiten más de una colocación de los cambios
    (ver `soluciones`). Pasa de verdad: en el Barça, tres de sus nueve
    partidos. Casi siempre la duda es de un minuto —quién entró en el
    81 y quién en el 82— y afecta como mucho a un tiro.

    Tirar un tercio de la temporada por un minuto sería peor que el
    problema. Así que:

      · si todas las lecturas dan lo mismo, no hay nada que decidir
      · si difieren POCO, se devuelve la media de todas y se marca el
        partido como dudoso, diciendo cuánto baila la cifra
      · si difieren MUCHO, se para: ahí sí, elegir sería inventar

    La media de dos lecturas igual de probables no es un número
    inventado: es lo que se sabe. Lo que sería inventar es dar una de
    las dos como si fuera la buena.
    """
    todas = soluciones(jugadores)
    repartos = [_reparto_de_unos_tramos(ts, tiros_a_favor, tiros_en_contra)
                for ts in todas]
    if len(repartos) == 1:
        return repartos[0]

    claves = set()
    for r in repartos:
        claves |= set(r)

    salida, mayor_baile = {}, 0.0
    for pid in claves:
        trozos = [r[pid] for r in repartos if pid in r]
        if len(trozos) != len(repartos):
            # En una lectura este jugador no aparece: eso no es una
            # duda de un minuto, es otra alineación.
            raise NoSePuedeReconstruir(
                "ambiguo",
                f"{pid} aparece en unas lecturas y en otras no")
        medio = dict(trozos[0])
        for campo in ("minutos_dentro", "minutos_fuera", "xg_favor_dentro",
                      "xg_contra_dentro", "xg_favor_fuera", "xg_contra_fuera"):
            valores = [t[campo] for t in trozos]
            medio[campo] = sum(valores) / len(valores)
            if campo.startswith("xg"):
                medio[campo] = round(medio[campo], 4)
                mayor_baile = max(mayor_baile, max(valores) - min(valores))
            else:
                # Los minutos son minutos: un «288,67» en pantalla sólo
                # sirve para que quien lo lea se pregunte qué es eso.
                medio[campo] = int(round(medio[campo]))
        salida[pid] = medio

    if mayor_baile > UMBRAL_DE_DUDA:
        raise NoSePuedeReconstruir(
            "ambiguo",
            f"los minutos admiten {len(repartos)} colocaciones distintas de "
            f"los cambios y a algún jugador le bailan {mayor_baile:.2f} de "
            f"xG según cuál sea la buena; eso ya no es un detalle")

    for d in salida.values():
        d["lectura_dudosa"] = True
        d["cuanto_baila"] = round(mayor_baile, 4)
    return salida


def _reparto_de_unos_tramos(ts: list, tiros_a_favor: list,
                            tiros_en_contra: list) -> dict:
    salida = {}
    for t in ts:
        dentro_f = xg_en_el_tramo(tiros_a_favor, t["desde"], t["hasta"])
        dentro_c = xg_en_el_tramo(tiros_en_contra, t["desde"], t["hasta"])
        fuera_f = xg_en_el_tramo(tiros_a_favor, 0, MINUTOS_PARTIDO) - dentro_f
        fuera_c = xg_en_el_tramo(tiros_en_contra, 0, MINUTOS_PARTIDO) - dentro_c
        salida[t.get("player_id") or t.get("nombre")] = {
            "nombre": t.get("nombre"),
            "puesto": t.get("puesto"),
            "minutos_dentro": t["hasta"] - t["desde"],
            "minutos_fuera": MINUTOS_PARTIDO - (t["hasta"] - t["desde"]),
            "xg_favor_dentro": round(dentro_f, 4),
            "xg_contra_dentro": round(dentro_c, 4),
            "xg_favor_fuera": round(fuera_f, 4),
            "xg_contra_fuera": round(fuera_c, 4),
        }
    return salida
