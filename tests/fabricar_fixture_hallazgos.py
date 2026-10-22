# -*- coding: utf-8 -*-
"""
FABRICAR LOS FIXTURES DE HALLAZGOS Y DE MÉTODO
==============================================
Las dos respuestas salen de las rutas DE VERDAD, con Understat
sustituido por una plantilla inventada. La corrección de
Benjamini-Hochberg, la binomial y el recuento de pruebas los hace el
servidor, no este fichero.

La plantilla está pensada, no sacada al azar:

  · 240 jugadores que convierten EXACTAMENTE a su xG (tirando la
    moneda de verdad, con semilla fija). De estos no debería salir
    casi ninguno: son el ruido.
  · 2 que no cuadran de forma escandalosa, uno por arriba y otro por
    abajo. Son los que tienen que sobrevivir.
  · 1 con pocos tiros y 1 con pocos minutos, para que la muestra de
    descartados tenga algo que enseñar.

Así el fixture contiene a la vez un hallazgo de verdad y la prueba de
que el ruido no se cuela.
"""
import json
import os
import random
import sys

sys.path.insert(0, ".")

AQUI = os.path.dirname(os.path.abspath(__file__))
DATOS = os.path.join(AQUI, "datos")

EQUIPOS = ["Real Sociedad", "Girona", "Osasuna", "Celta", "Betis"]


def plantilla():
    rnd = random.Random(20261022)
    gente = []

    for i in range(240):
        tiros = rnd.randint(16, 65)
        xg_tiro = rnd.uniform(0.07, 0.20)
        goles = sum(1 for _ in range(tiros) if rnd.random() < xg_tiro)
        gente.append({
            "player_id": f"r{i}", "name": f"Jugador {i}",
            "team": EQUIPOS[i % len(EQUIPOS)], "position": "F M",
            "time": rnd.randint(500, 2400), "shots": tiros,
            "npg": goles, "npxG": round(tiros * xg_tiro, 2),
            "goals": goles, "xG": round(tiros * xg_tiro, 2),
        })

    # El que mete el triple de lo que le tocaba.
    gente.append({
        "player_id": "arriba", "name": "El Que Mete",
        "team": "Alaves", "position": "F", "time": 1500,
        "shots": 55, "npg": 21, "npxG": 6.80,
        "goals": 24, "xG": 9.08,
    })
    # El que falla lo que debería meter.
    gente.append({
        "player_id": "abajo", "name": "El Que Falla",
        "team": "Valencia", "position": "F", "time": 1700,
        "shots": 70, "npg": 1, "npxG": 13.40,
        "goals": 1, "xG": 13.40,
    })
    # Los dos que no se pueden medir.
    gente.append({
        "player_id": "pocostiros", "name": "El Central",
        "team": "Getafe", "position": "D", "time": 2000,
        "shots": 5, "npg": 1, "npxG": 0.45,
        "goals": 1, "xG": 0.45,
    })
    gente.append({
        "player_id": "pocosminutos", "name": "El Recién Llegado",
        "team": "Mallorca", "position": "F", "time": 120,
        "shots": 20, "npg": 7, "npxG": 2.10,
        "goals": 7, "xG": 2.10,
    })
    return gente


def main():
    from fastapi.testclient import TestClient
    import main as servidor

    gente = plantilla()

    async def falso_get_league_players(liga, season=None):
        return json.loads(json.dumps(gente))

    de_verdad = servidor.get_league_players
    servidor.get_league_players = falso_get_league_players
    try:
        cliente = TestClient(servidor.app, raise_server_exceptions=False)

        r = cliente.get("/api/hallazgos", params={"liga": "PD"})
        assert r.status_code == 200, f"hallazgos: {r.status_code} {r.text[:200]}"
        hz = r.json()
        assert hz["hallazgos"], "el fixture no tiene ni un hallazgo"
        assert hz["cuantos_descartados"] >= 2, "faltan descartados"

        m = cliente.get("/api/metodo")
        assert m.status_code == 200, f"metodo: {m.status_code}"
        mt = m.json()
        assert mt["numeros_que_se_pueden_discutir"], "método sin constantes"
    finally:
        servidor.get_league_players = de_verdad

    for nombre, d in (("hallazgos_fixture.json", hz),
                      ("metodo_fixture.json", mt)):
        with open(os.path.join(DATOS, nombre), "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False, indent=1)

    return hz, mt


if __name__ == "__main__":
    hz, mt = main()
    print(f"hallazgos: {len(hz['hallazgos'])} de {hz['cuantos_probados']} "
          f"probados · sin corregir pasarían {hz['pasarian_sin_corregir']} "
          f"· por azar {hz['esperados_por_puro_azar']}")
    for h in hz["hallazgos"]:
        print(f"   {h['name']:20s} {h['goles_sin_penalti']:3d} goles "
              f"vs {h['npxg']:5.2f} npxG   p={h['p']}")
    print(f"metodo: {len(mt['numeros_que_se_pueden_discutir'])} constantes, "
          f"{mt['como_se_prueba']['pruebas']['total']} pruebas")
