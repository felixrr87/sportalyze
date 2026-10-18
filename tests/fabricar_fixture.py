# -*- coding: utf-8 -*-
"""
FABRICAR EL FIXTURE DEL SCOUTING
================================
Genera la respuesta de /api/scouting tal y como la devuelve el servidor
de verdad, para poder comprobar la pantalla sin pedirle nada a Understat.

NO ES UN JSON ESCRITO A MANO. Los jugadores de entrada son inventados,
pero pasan por `run_scouting_pipeline`, que es el mismo código que corre
en producción: los percentiles, el agrupamiento y las coordenadas del
PCA salen del motor. Si el motor cambia de forma, el fixture cambia con
él y el comprobador de la maqueta se enterará.

Un JSON a mano comprobaría que la pantalla pinta lo que yo escribí.
Esto comprueba que pinta lo que calcula el servidor.
"""
import json
import random
import sys

sys.path.insert(0, ".")

from backend.ml.scouting import run_scouting_pipeline
from backend.temporada import nombre_temporada, temporada_actual

CAMPOS_DE_UNDERSTAT = (
    "player_id name team position games time goals xG assists xA shots "
    "key_passes npg npxG xGChain xGBuildup xG_per90 xA_per90 goals_diff"
).split()


def jugador(n: int, rnd: random.Random, puesto: str) -> dict:
    """Un jugador con exactamente los campos que da get_league_players."""
    minutos = rnd.randint(300, 900)
    partidos = max(1, minutos // 85)
    tiros = rnd.randint(2, 40)
    goles = rnd.randint(0, 9)
    xg = round(rnd.uniform(0.2, 9.5), 2)
    asis = rnd.randint(0, 7)
    xa = round(rnd.uniform(0.1, 6.0), 2)
    return {
        "player_id": str(1000 + n),
        "name": f"Jugador {n:02d} Apellido{n:02d}",
        "team": f"Equipo {n % 7}",
        "position": puesto,
        "games": partidos,
        "time": minutos,
        "goals": goles,
        "xG": xg,
        "assists": asis,
        "xA": xa,
        "shots": tiros,
        "key_passes": rnd.randint(0, 40),
        "npg": max(0, goles - rnd.randint(0, 1)),
        "npxG": round(max(0.0, xg - rnd.uniform(0, 1.2)), 2),
        "xGChain": round(rnd.uniform(0.5, 12.0), 2),
        "xGBuildup": round(rnd.uniform(0.2, 8.0), 2),
        "xG_per90": round(xg / minutos * 90, 3),
        "xA_per90": round(xa / minutos * 90, 3),
        "goals_diff": round(goles - xg, 2),
    }


def tiro(n: int, rnd: random.Random) -> dict:
    """Un tiro con los campos de get_player_shots. x e y van de 0 a 1."""
    return {
        "id": str(50000 + n),
        "minute": rnd.randint(1, 90),
        "result": rnd.choice(["Goal", "SavedShot", "MissedShots", "BlockedShot"]),
        "x": round(rnd.uniform(0.60, 0.99), 4),
        "y": round(rnd.uniform(0.20, 0.80), 4),
        "xG": round(rnd.uniform(0.01, 0.78), 4),
        "player": "Jugador 01 Apellido01",
        "situation": rnd.choice(["OpenPlay", "FromCorner", "SetPiece"]),
        "season": str(temporada_actual()),
        "shot_type": rnd.choice(["RightFoot", "LeftFoot", "Head"]),
        "match_id": str(900 + n),
        "home_team": "Equipo 1",
        "away_team": "Equipo 2",
        "date": "2026-10-05",
    }


def main() -> None:
    rnd = random.Random(7)
    jugadores = [jugador(n, rnd, "F S") for n in range(1, 29)]
    for p in jugadores:
        p["league"] = "PD"
        faltan = [c for c in CAMPOS_DE_UNDERSTAT if c not in p]
        assert not faltan, f"al fixture le faltan campos reales: {faltan}"

    salida = run_scouting_pipeline(
        players=jugadores, position="FW", max_age=50, min_minutes=270)
    salida["ligas"] = ["PD"]
    salida["season"] = temporada_actual()
    salida["temporada"] = nombre_temporada()

    pl = salida["players"]
    assert pl, "el motor no ha devuelto jugadores"
    for p in pl:
        for clave in ("score", "percentiles", "por_90", "cluster",
                      "pca_x", "pca_y", "pca_variance", "player_id"):
            assert clave in p, f"el motor no pone {clave}: la pantalla lo necesita"
    assert all(pl[i - 1]["score"] >= pl[i]["score"] for i in range(1, len(pl))), \
        "el motor no los devuelve ordenados"

    with open("tests/datos/scouting_fixture.json", "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=1)

    # La respuesta de /api/player/{id}/shots tal y como queda ahora:
    # los de ESTA temporada, más el reparto de toda la carrera. Esa
    # diferencia es el fallo que apareció con datos reales —Raphinha
    # con 550 tiros desde 2019 bajo una cabecera que decía 26—, así
    # que el fixture tiene que llevarla para poder probarla.
    lista = [tiro(n, rnd) for n in range(1, 24)]
    tiros = {
        "shots": lista,
        "total": len(lista),
        "temporada": nombre_temporada(),
        "total_carrera": len(lista) + 527,
        "por_temporada": {str(temporada_actual()): len(lista),
                          "2025": 180, "2024": 200, "2023": 147},
    }
    with open("tests/datos/tiros_fixture.json", "w", encoding="utf-8") as f:
        json.dump(tiros, f, ensure_ascii=False, indent=1)

    print(f"{len(pl)} jugadores puntuados por el motor de verdad")
    print(f"percentiles: {list(pl[0]['percentiles'])}")
    print(f"el primero: {pl[0]['name']} · {pl[0]['score']} · "
          f"pca ({pl[0]['pca_x']}, {pl[0]['pca_y']})")
    print(f"grupos: " + ", ".join(
        f"{c}={sum(1 for p in pl if p['cluster'] == c)}" for c in range(4)))
    print(f"{tiros['total']} tiros de {tiros['total_carrera']} de carrera")


if __name__ == "__main__":
    main()
