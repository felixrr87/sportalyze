# -*- coding: utf-8 -*-
"""
PRUEBAS DEL SIMULADOR
=====================
    python3 -m pytest tests/test_simulador.py -v

Sin red. Trabajan sobre tests/datos/laliga_2026_27.json: el calendario
real de 380 partidos con los resultados reales hasta la jornada 7,
envuelto en la forma que devuelve football-data.org.

QUÉ SE PRUEBA, Y POR QUÉ ESTO Y NO OTRA COSA
--------------------------------------------
Lo caro de un simulador no es que calcule mal: es que calcule bien
sobre datos malos y nadie se entere. Así que la mitad de estas pruebas
no comprueban números, comprueban NEGATIVAS: que se niegue cuando el
calendario viene a medias, cuando la fuente va con retraso y cuando hay
tan poco jugado que el resultado no diría nada.

La otra mitad comprueba las identidades que tienen que cumplirse
siempre: las probabilidades de título suman 1, las de Champions suman
4, las de descenso suman 3, cada 1X2 suma exactamente 1 y cada
distribución de posiciones suma 1. Si el motor se rompe, alguna de esas
cuentas deja de cuadrar.
"""
import copy
import json
import os
import sys

import pytest

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(AQUI))

from backend.ml import simulador as S     # noqa: E402

DATOS = os.path.join(AQUI, "datos", "laliga_2026_27.json")

# El día después del último partido del fichero (jornada 7, 20 de
# septiembre). Con esta fecha los datos están al día; con la de hoy,
# desfasados, y eso también se prueba.
AL_DIA = "2026-09-22"


@pytest.fixture(scope="module")
def crudos():
    with open(DATOS, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def ed(crudos):
    return S.edicion(crudos, "PD", "La Liga", hoy=AL_DIA)


# ════════════════════════════════════════════════════════════════
# EL ADAPTADOR
# ════════════════════════════════════════════════════════════════

def _partido(estado="FINISHED", gl=1, gv=0, jornada=1,
             fecha="2026-08-15", casa="Local CF", visita="Visitante CF"):
    return {"matchday": jornada, "utcDate": fecha + "T18:30:00Z",
            "status": estado,
            "homeTeam": {"name": casa}, "awayTeam": {"name": visita},
            "score": {"fullTime": {"home": gl, "away": gv}}}


def test_solo_cuenta_como_jugado_lo_que_esta_acabado():
    """Un partido en juego no es un resultado, es un partido en juego."""
    for estado in ("IN_PLAY", "PAUSED", "TIMED", "SCHEDULED",
                   "POSTPONED", "SUSPENDED"):
        ps = S.desde_football_data([_partido(estado, 2, 1)])
        assert ps[0]["gl"] is None, f"{estado} no debería contar como jugado"
    ps = S.desde_football_data([_partido("FINISHED", 2, 1)])
    assert (ps[0]["gl"], ps[0]["gv"]) == (2, 1)


def test_un_finished_sin_goles_no_cuenta():
    """Pasa de verdad: FINISHED con el marcador a null. No es un 0-0."""
    ps = S.desde_football_data([_partido("FINISHED", None, None)])
    assert ps[0]["gl"] is None and ps[0]["gv"] is None


def test_un_partido_sin_equipos_se_descarta():
    """En las copas hay cruces sin equipo asignado todavía."""
    m = _partido()
    m["homeTeam"] = {"name": None}
    assert S.desde_football_data([m]) == []


def test_el_adaptador_guarda_el_estado():
    """Hace falta para distinguir un aplazado de una fuente parada."""
    ps = S.desde_football_data([_partido("POSTPONED", None, None)])
    assert ps[0]["estado"] == "POSTPONED"


# ════════════════════════════════════════════════════════════════
# EL CALENDARIO: SE NIEGA SI NO CUADRA
# ════════════════════════════════════════════════════════════════

def test_el_calendario_real_cuadra(crudos):
    cal = S.validar_calendario(S.desde_football_data(crudos))
    assert cal["equipos"] == 20
    assert cal["partidos"] == 380          # 20 × 19
    assert cal["jugados"] == 69
    assert cal["jornada"] == 7


def test_sin_partidos_no_simula():
    with pytest.raises(S.CalendarioIncompleto):
        S.validar_calendario([])


def test_media_temporada_no_vale(crudos):
    """El fallo más probable de verdad: la fuente devuelve una página."""
    ps = S.desde_football_data(crudos)[:200]
    with pytest.raises(S.CalendarioIncompleto) as e:
        S.validar_calendario(ps)
    assert "380" in str(e.value)


def test_un_equipo_contra_si_mismo_revienta(crudos):
    ps = copy.deepcopy(S.desde_football_data(crudos))
    ps[0]["visitante"] = ps[0]["local"]
    with pytest.raises(S.CalendarioIncompleto) as e:
        S.validar_calendario(ps)
    assert "contra sí mismo" in str(e.value)


def test_un_partido_repetido_revienta(crudos):
    ps = copy.deepcopy(S.desde_football_data(crudos))
    ps[1]["local"], ps[1]["visitante"] = ps[0]["local"], ps[0]["visitante"]
    with pytest.raises(S.CalendarioIncompleto) as e:
        S.validar_calendario(ps)
    assert "dos veces" in str(e.value)


def test_un_partido_sin_jornada_revienta(crudos):
    ps = copy.deepcopy(S.desde_football_data(crudos))
    ps[5]["jornada"] = None
    with pytest.raises(S.CalendarioIncompleto) as e:
        S.validar_calendario(ps)
    assert "jornada" in str(e.value)


# ════════════════════════════════════════════════════════════════
# LA SALUD DE LOS DATOS: SE NIEGA SI LA FUENTE VA ATRASADA
# ════════════════════════════════════════════════════════════════

def test_al_dia_no_hay_aviso(crudos):
    s = S.salud_datos(S.desde_football_data(crudos), hoy=AL_DIA)
    assert s["vencidos_sin_resultado"] == 0
    assert s["dias_de_retraso"] == 0
    assert s["aviso"] is None


def test_una_fuente_parada_se_detecta(crudos):
    """Esto es exactamente lo que pasa con openfootball hoy: tiene el
    calendario bien y los resultados de hace dos jornadas."""
    ps = S.desde_football_data(crudos)
    with pytest.raises(S.DatosDesfasados) as e:
        S.salud_datos(ps, hoy="2026-10-18")
    assert "sin dar su resultado" in str(e.value)


def test_un_dia_de_retraso_avisa_pero_no_revienta(crudos):
    """El margen existe para los partidos de anoche que la fuente aún
    no ha cerrado. Avisa, que no es lo mismo que callarse."""
    ps = S.desde_football_data(crudos)
    s = S.salud_datos(ps, hoy="2026-10-10")   # la jornada 8 empezó el 9
    assert s["vencidos_sin_resultado"] > 0
    assert s["aviso"] and "sin resultado" in s["aviso"]


def test_un_aplazado_no_cuenta_como_retraso():
    """Un partido aplazado conserva su fecha vieja. Si contara como
    retraso, el simulador se quedaría roto el resto de la temporada."""
    ps = S.desde_football_data([
        _partido("POSTPONED", None, None, fecha="2026-01-01")])
    s = S.salud_datos(ps, hoy="2026-10-18")
    assert s["aplazados"] == 1
    assert s["vencidos_sin_resultado"] == 0
    assert s["dias_de_retraso"] == 0


def test_el_margen_es_de_dos_dias():
    """Fijado a propósito: si alguien lo sube, que lo suba a sabiendas."""
    assert S.DIAS_TOLERADOS == 2


# ════════════════════════════════════════════════════════════════
# DEMASIADO PRONTO
# ════════════════════════════════════════════════════════════════

def test_con_una_jornada_no_simula(crudos):
    """En la jornada 1 el modelo da números bonitos y nada más."""
    ps = S.desde_football_data(crudos)
    for p in ps:                       # deja sólo la jornada 1 jugada
        if (p["jornada"] or 0) > 1:
            p["gl"] = p["gv"] = None
    with pytest.raises(S.DemasiadoPronto) as e:
        S.exigir_bastante_jugado(ps)
    assert "no diría nada" in str(e.value)


def test_con_la_temporada_acabada_no_hay_nada_que_simular(crudos):
    ps = S.desde_football_data(crudos)
    for p in ps:
        if p["gl"] is None:
            p["gl"], p["gv"] = 1, 1
    with pytest.raises(S.DemasiadoPronto):
        S.exigir_bastante_jugado(ps)


# ════════════════════════════════════════════════════════════════
# LAS CUENTAS QUE TIENEN QUE CUADRAR SIEMPRE
# ════════════════════════════════════════════════════════════════

def test_los_titulos_suman_uno(ed):
    assert abs(sum(f["p_titulo"] for f in ed["tabla"]) - 1) < 2e-3


def test_la_champions_suma_cuatro(ed):
    assert abs(sum(f["p_champions"] for f in ed["tabla"]) - 4) < 2e-3


def test_el_descenso_suma_tres(ed):
    assert abs(sum(f["p_descenso"] for f in ed["tabla"]) - 3) < 2e-3


def test_cada_distribucion_suma_uno(ed):
    for f in ed["tabla"]:
        assert abs(sum(f["dist"]) - 1) < 2e-3, f["corto"]
        assert len(f["dist"]) == 20


def test_los_rangos_estan_en_orden_y_dentro_del_campo(ed):
    for f in ed["tabla"]:
        assert 1 <= f["p10"] <= f["mediana"] <= f["p90"] <= 20, f["corto"]
        assert 1 <= f["media"] <= 20


def test_la_tabla_de_hoy_no_repite_posiciones(ed):
    assert sorted(f["pos_hoy"] for f in ed["tabla"]) == list(range(1, 21))


def test_cada_1x2_suma_exactamente_uno(ed):
    """Exactamente, no casi: el resto del redondeo va a la casilla
    mayor para que nadie sume 101 % en pantalla."""
    for p in ed["proximos"]:
        assert p["p_local"] + p["p_empate"] + p["p_visitante"] == 1.0, p


def test_los_puntos_de_hoy_son_los_de_verdad(ed, crudos):
    """Los partidos jugados NO se simulan. Si los puntos de la tabla no
    salen de los resultados reales, se está simulando el pasado."""
    cl = S.clasificacion(S.desde_football_data(crudos), 7)
    reales = {f["equipo"]: f["pts"] for f in cl}
    for f in ed["tabla"]:
        assert f["pts_hoy"] == reales[f["equipo"]], f["corto"]
    # 69 partidos jugados: 3 puntos por victoria, 2 por empate repartidos
    assert sum(f["pts_hoy"] for f in ed["tabla"]) <= 69 * 3


def test_los_goles_a_favor_son_los_goles_en_contra(ed):
    assert (sum(f["gf"] for f in ed["tabla"])
            == sum(f["gc"] for f in ed["tabla"]))


# ════════════════════════════════════════════════════════════════
# QUE NO SE TOQUEN LOS NÚMEROS DEL MODELO A MANO
# ════════════════════════════════════════════════════════════════

def test_las_constantes_del_modelo_son_las_validadas():
    """LAMBDA y ESCALA_INCERT salieron de validar.py sobre 58
    temporadas. Cambiarlas a ojo para que salga un número más bonito es
    la forma más fácil de estropear esto, así que quedan clavadas aquí.
    """
    assert S.LAMBDA == 7.0
    assert S.ESCALA_INCERT == 0.45
    assert S.N_SIM == 10000
    assert S.SEMILLA == 7


def test_mismos_datos_mismo_resultado(crudos):
    """Con semilla fija, dos ejecuciones dan lo mismo. Si no, no se
    puede comprobar nada de lo de arriba."""
    a = S.edicion(crudos, "PD", "La Liga", hoy=AL_DIA)
    b = S.edicion(crudos, "PD", "La Liga", hoy=AL_DIA)
    assert [f["p_titulo"] for f in a["tabla"]] == \
           [f["p_titulo"] for f in b["tabla"]]
    assert a["anchura_media_rango80"] == b["anchura_media_rango80"]


def test_el_rango_es_ancho_porque_quedan_31_jornadas(ed):
    """Una comprobación de olfato: en la jornada 7, un rango del 80 %
    de dos puestos de ancho sería mentira. Si esto baja de 5, es que el
    segundo dado ha dejado de tirarse."""
    assert ed["anchura_media_rango80"] > 5, ed["anchura_media_rango80"]


def test_sin_el_segundo_dado_el_rango_se_estrecha(crudos):
    """Comprueba que la incertidumbre de las fuerzas hace algo. Con
    escala 0 el modelo se cree su propia estimación y los rangos se
    encogen: ésa era la versión mala."""
    ps = S.desde_football_data(crudos)
    eq, con, _ = S.simular(ps, 7, n_sim=1500)
    eq2, sin, _ = S.simular(ps, 7, n_sim=1500, escala=0.0)
    import numpy as np
    ancho = lambda m: np.mean(np.percentile(m, 90, axis=0)
                              - np.percentile(m, 10, axis=0))
    assert ancho(con) > ancho(sin), (ancho(con), ancho(sin))


# ════════════════════════════════════════════════════════════════
# LA PROCEDENCIA SE PUBLICA CON EL NÚMERO
# ════════════════════════════════════════════════════════════════

def test_la_edicion_dice_de_donde_viene(ed):
    """Un rango sin fecha ni fuente no se puede comprobar, y todo lo
    que sale de aquí tiene que poder comprobarlo cualquiera."""
    for campo in ("fuente", "jornada", "ultima_fecha", "partidos_jugados",
                  "partidos_calendario", "equipos", "calculado", "modelo"):
        assert ed.get(campo) not in (None, ""), campo
    assert ed["fuente"] == "football-data.org"
    assert ed["modelo"]["simulaciones"] == 10000


def test_la_edicion_viaja_como_json(ed):
    assert json.loads(json.dumps(ed))["jornada"] == 7


def test_los_proximos_llevan_su_jornada(ed):
    """Se ordenan por FECHA, no por jornada, porque con un aplazado de
    por medio 'la próxima jornada' no es lo próximo que se juega."""
    assert len(ed["proximos"]) == 10
    fechas = [p["fecha"] for p in ed["proximos"]]
    assert fechas == sorted(fechas)
    for p in ed["proximos"]:
        assert p["jornada"] >= 1


# ════════════════════════════════════════════════════════════════
# NOMBRES
# ════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("largo,corto", [
    ("Club Atlético de Madrid", "Atlético"),
    ("Real Betis Balompié", "Betis"),
    ("RC Deportivo La Coruña", "Deportivo"),
    ("Real Madrid CF", "Real Madrid"),
    ("Athletic Club", "Athletic"),
    ("Villarreal CF", "Villarreal"),
])
def test_los_nombres_se_recortan(largo, corto):
    assert S.corto(largo) == corto


def test_recortar_nunca_deja_el_nombre_vacio(ed):
    """Quitarle las siglas a un equipo no puede dejarlo sin nombre."""
    for f in ed["tabla"]:
        assert f["corto"].strip(), f["equipo"]
    assert S.corto("CF") == "CF"
    assert S.corto("") == ""


def test_los_nombres_cortos_no_se_repiten(ed):
    """Si dos equipos se quedan con el mismo nombre corto, la tabla
    miente."""
    cortos = [f["corto"] for f in ed["tabla"]]
    assert len(set(cortos)) == len(cortos), cortos


# ════════════════════════════════════════════════════════════════
# LA RUTA
# ════════════════════════════════════════════════════════════════
#
# Con un cliente de pega: estas pruebas no tocan football-data. Lo que
# comprueban es el contrato de la ruta —qué código y qué `motivo`
# devuelve en cada caso—, que es lo que la pantalla necesita para dar
# una explicación en vez de un hueco.

def _al_dia(crudos, dias_desde_el_ultimo=1):
    """Corre todas las fechas del fichero para que el último partido
    jugado caiga `dias_desde_el_ultimo` días antes de hoy.

    Sin esto la prueba del camino bueno caducaría: el fichero se queda
    en septiembre de 2026 y el simulador, con razón, lo rechaza por
    desfasado. Se mueve el calendario entero, no los resultados.
    """
    from datetime import date, datetime, timedelta
    crudos = copy.deepcopy(crudos)
    ultima = max(m["utcDate"][:10] for m in crudos
                 if m["status"] == "FINISHED")
    desfase = (date.today() - timedelta(days=dias_desde_el_ultimo)
               - date.fromisoformat(ultima))
    for m in crudos:
        d = datetime.fromisoformat(m["utcDate"][:10]) + desfase
        m["utcDate"] = d.strftime("%Y-%m-%d") + m["utcDate"][10:]
    return crudos


@pytest.fixture
def cliente(monkeypatch):
    """La app con el cliente de football-data sustituido."""
    from fastapi.testclient import TestClient
    import main

    main._simulaciones.clear()

    estado = {"devuelve": [], "revienta": None}

    async def falso(codigo):
        if estado["revienta"]:
            raise estado["revienta"]
        return estado["devuelve"]

    monkeypatch.setattr(main.football_client, "get_competition_season", falso)
    return TestClient(main.app), estado


def test_la_ruta_devuelve_la_edicion(cliente, crudos):
    cli, estado = cliente
    estado["devuelve"] = _al_dia(crudos)
    r = cli.get("/api/simulador/PD")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["competicion"] == "PD"
    assert len(d["tabla"]) == 20
    assert d["partidos_calendario"] == 380
    assert d["fuente"] == "football-data.org"


def test_la_ruta_no_distingue_mayusculas(cliente, crudos):
    cli, estado = cliente
    estado["devuelve"] = _al_dia(crudos)
    assert cli.get("/api/simulador/pd").status_code == 200


def test_la_ruta_guarda_la_simulacion(cliente, crudos):
    """La segunda visita no vuelve a pedir ni a simular: son 1,5 s de
    CPU y una de las diez peticiones del minuto."""
    cli, estado = cliente
    estado["devuelve"] = _al_dia(crudos)
    assert cli.get("/api/simulador/PD").status_code == 200
    estado["revienta"] = RuntimeError("no deberían volver a pedirlo")
    assert cli.get("/api/simulador/PD").status_code == 200


def test_la_ruta_avisa_de_datos_desfasados(cliente, crudos):
    """El fichero tal cual: resultados hasta septiembre de 2026."""
    cli, estado = cliente
    estado["devuelve"] = crudos
    r = cli.get("/api/simulador/PD")
    assert r.status_code == 503
    assert r.json()["detail"]["motivo"] == "datos_desfasados"
    assert "sin dar su resultado" in r.json()["detail"]["detalle"]


def test_la_ruta_avisa_de_calendario_incompleto(cliente, crudos):
    cli, estado = cliente
    estado["devuelve"] = _al_dia(crudos)[:150]
    r = cli.get("/api/simulador/PD")
    assert r.status_code == 503
    assert r.json()["detail"]["motivo"] == "calendario_incompleto"


def test_la_ruta_avisa_de_que_es_pronto(cliente, crudos):
    cli, estado = cliente
    ms = _al_dia(crudos)
    for m in ms:                       # deja sólo la jornada 1 jugada
        if (m["matchday"] or 0) > 1:
            m["status"] = "TIMED"
            m["score"]["fullTime"] = {"home": None, "away": None}
            # y en el futuro, para que no cuente como retraso
            m["utcDate"] = "2027-05-01" + m["utcDate"][10:]
    estado["devuelve"] = ms
    r = cli.get("/api/simulador/PD")
    assert r.status_code == 503
    assert r.json()["detail"]["motivo"] == "demasiado_pronto"


def test_la_ruta_devuelve_429_al_agotar_el_limite(cliente, crudos):
    from backend.scrapers.football_data import LimiteAlcanzado
    cli, estado = cliente
    estado["revienta"] = LimiteAlcanzado("diez por minuto")
    r = cli.get("/api/simulador/PD")
    assert r.status_code == 429
    assert r.json()["detail"]["motivo"] == "limite_alcanzado"


def test_la_ruta_devuelve_503_si_la_fuente_no_contesta(cliente):
    cli, estado = cliente
    estado["revienta"] = ConnectionError("no hay salida a internet")
    r = cli.get("/api/simulador/PD")
    assert r.status_code == 503
    assert r.json()["detail"]["motivo"] == "fuente_caida"


def test_la_ruta_nunca_devuelve_una_tabla_a_medias(cliente, crudos):
    """Lo importante de todo lo de arriba, en una frase: o viene la
    edición entera, o viene un motivo. Nunca un 200 con huecos."""
    cli, estado = cliente
    for datos in (crudos, _al_dia(crudos)[:150], []):
        import main
        main._simulaciones.clear()
        estado["devuelve"] = datos
        r = cli.get("/api/simulador/PD")
        assert r.status_code != 200, datos[:1]
        assert "motivo" in r.json()["detail"]


def test_trocear_no_cambia_ni_un_numero(crudos):
    """El simulador calcula por trozos para no reventar la memoria de
    un servidor pequeño. Trocear NO puede cambiar el resultado.

    La primera versión troceada sí lo cambiaba: sacaba los goles
    locales y los visitantes de cada trozo seguidos, lo que ALTERNA las
    dos tiradas en el generador y da otra secuencia. Cambiaba el 83 %
    de las posiciones finales. Ahora se hace primero la tirada local
    entera y después la visitante entera, y sale idéntico.

    Esta prueba es la que justifica poder decir «misma semilla, mismo
    resultado» después de haber tocado el motor por memoria.
    """
    import numpy as np
    ps = S.desde_football_data(crudos)
    antes = S.TROZO
    try:
        S.TROZO = 10 ** 9                      # de una sola tacada
        _, entero, _ = S.simular(ps, 7, n_sim=2000)
        for trozo in (1000, 137, 1):
            S.TROZO = trozo
            _, por_trozos, _ = S.simular(ps, 7, n_sim=2000)
            assert np.array_equal(entero, por_trozos), f"trozo {trozo}"
    finally:
        S.TROZO = antes


def test_los_goles_caben_en_un_byte():
    """Se guardan en int8 para ahorrar memoria. Si alguien sube
    MAX_GOLES por encima de 127, los goles darían la vuelta y un 5-3
    se convertiría en algo absurdo sin avisar."""
    assert S.MAX_GOLES <= 127
    assert S.TROZO >= 1
