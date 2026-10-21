# -*- coding: utf-8 -*-
"""
FABRICAR EL FIXTURE DEL RANKING DE GOLES Y ASISTENCIAS
======================================================
Genera la respuesta de /api/goles-asistencias tal y como la devuelve el
servidor de verdad, para poder comprobar la pantalla sin pedirle nada a
Understat.

NO ES UN JSON ESCRITO A MANO. Los jugadores de entrada son inventados,
pero salen por la ruta de verdad: la resta de la diferencia, el orden y
el recorte los hace main.py. Si la ruta cambia de forma, el fixture
cambia con ella y el comprobador de la maqueta se entera.

Se fabrican DOS respuestas a propósito:

  ranking_fixture.json        ordenada por G+A, que es lo normal
  ranking_fixture_dif.json    ordenada por diferencia

La segunda existe por una razón concreta: comprobar que el que lleva
poco G+A pero mucha diferencia SALE en la lista. Si el recorte se
hiciera antes de ordenar —que es como estaba al principio— ese jugador
se quedaría fuera y nadie lo vería.
"""
import json
import os
import sys

sys.path.insert(0, ".")

AQUI = os.path.dirname(os.path.abspath(__file__))
DATOS = os.path.join(AQUI, "datos")


def _jug(pid, nombre, equipo, puesto, minutos, partidos,
         goles, asis, xg, xa, tiros=0, pases=0):
    """Un jugador con los campos que da get_league_players."""
    return {
        "player_id": str(pid), "name": nombre, "team": equipo,
        "position": puesto, "games": partidos, "time": minutos,
        "goals": goles, "assists": asis, "xG": xg, "xA": xa,
        "shots": tiros, "key_passes": pases,
    }


# Los de entrada. Están pensados, no sacados al azar:
#
#   · Oyarzabal lleva mucho y mete más de lo que le toca
#   · Vinícius lleva mucho y mete MENOS de lo que le toca
#   · Baena lleva poco pero con una diferencia enorme: es el que se
#     cae de la lista si se recorta antes de ordenar
#   · Le Normand apenas tiene G+A: tiene que quedar el último por G+A
#   · Oroz no llega a los minutos mínimos y no debe aparecer
POR_LIGA = {
    "PD": [
        # Los decimales de éste están puestos a propósito: 12 de G+A
        # menos 9,57 de xG+xA son 2,43, que redondeado a un decimal
        # sería 2,4. Así, si la pantalla recalculara la resta en vez
        # de pintar la que manda el servidor, la prueba lo nota.
        _jug(1, "Mikel Oyarzabal", "Real Sociedad", "F M", 810, 9, 9, 3, 7.13, 2.44, 34, 18),
        _jug(2, "Vinicius Junior", "Real Madrid", "F", 780, 9, 5, 4, 8.90, 3.60, 41, 22),
        _jug(3, "Alex Baena", "Atletico Madrid", "M", 300, 5, 3, 2, 0.80, 0.50, 9, 11),
        _jug(4, "Robin Le Normand", "Atletico Madrid", "D", 810, 9, 1, 0, 0.60, 0.20, 4, 1),
        _jug(5, "Aimar Oroz", "Osasuna", "M", 120, 3, 2, 1, 0.90, 0.40, 5, 4),
    ],
    "PL": [
        _jug(10, "Erling Haaland", "Manchester City", "F", 840, 10, 14, 1, 12.40, 1.10, 52, 7),
        _jug(11, "Bukayo Saka", "Arsenal", "F M", 720, 9, 4, 8, 4.20, 6.90, 28, 31),
    ],
    "BL1": [
        _jug(20, "Harry Kane", "Bayern Munich", "F", 810, 9, 13, 5, 11.80, 3.20, 48, 26),
    ],
    "SA": [
        _jug(30, "Lautaro Martinez", "Inter", "F", 750, 9, 8, 2, 7.60, 1.80, 36, 12),
    ],
    "FL1": [
        _jug(40, "Ousmane Dembele", "Paris Saint Germain", "F M", 690, 9, 7, 6, 6.10, 4.40, 30, 28),
    ],
}


def main():
    from fastapi.testclient import TestClient
    import main as servidor

    async def falso_get_league_players(liga, season=None):
        # Copia profunda: la ruta escribe `league` dentro de cada
        # jugador y no debe tocar la tabla de arriba.
        return json.loads(json.dumps(POR_LIGA[liga]))

    de_verdad = servidor.get_league_players
    servidor.get_league_players = falso_get_league_players
    try:
        cliente = TestClient(servidor.app, raise_server_exceptions=False)
        salidas = {}
        for nombre, params in (
            ("ranking_fixture.json",
             {"orden": "ga", "min_minutes": 270, "limit": 150}),
            ("ranking_fixture_dif.json",
             {"orden": "diferencia", "min_minutes": 270, "limit": 150}),
        ):
            r = cliente.get("/api/goles-asistencias", params=params)
            assert r.status_code == 200, f"{nombre}: {r.status_code} {r.text[:200]}"
            d = r.json()
            assert d["jugadores"], f"{nombre}: lista vacía"
            ruta = os.path.join(DATOS, nombre)
            with open(ruta, "w", encoding="utf-8") as fh:
                json.dump(d, fh, ensure_ascii=False, indent=1)
            salidas[nombre] = d
    finally:
        servidor.get_league_players = de_verdad

    return salidas


if __name__ == "__main__":
    for nombre, d in main().items():
        print(f"{nombre}: {len(d['jugadores'])} jugadores, "
              f"orden '{d['orden']}', primero {d['jugadores'][0]['name']}")
