# -*- coding: utf-8 -*-
"""
BAJAR LAS FECHAS DE NACIMIENTO DE UNA LIGA
==========================================
    python3 herramientas/descargar_edades.py PD
    python3 herramientas/descargar_edades.py PD PL SA BL1 FL1

Deja un fichero por liga en backend/datos/, que es lo que luego leen
el Scouting y la lista de jugadores para poder filtrar por edad.

POR QUÉ ESTO SE EJECUTA A MANO Y NO AL VUELO
--------------------------------------------
Una plantilla es una petición a football-data. Una liga son veinte
equipos. Con nueve peticiones por minuto —que es lo que deja el plan
gratuito, dejando uno de margen— bajar una liga tarda unos dos
minutos y medio, y las cinco grandes, once.

Eso no cabe dentro de una visita a una página web. Así que se baja
aquí, una vez, y la aplicación lee el resultado. Si el fichero no
está, el filtro de edad no se aplica y la pantalla lo dice.

LO QUE SE GUARDA
----------------
La FECHA DE NACIMIENTO, no la edad. La edad se calcula al preguntar,
así que los cumpleaños no la estropean. Lo que sí envejece es la
plantilla —en enero hay mercado—, y por eso el fichero lleva el día
en que se bajó y la aplicación avisa cuando pasa de 45 días.

EL EMPAREJADO ES LA PARTE PELIGROSA
-----------------------------------
Los nombres no coinciden exactos entre las dos fuentes, y en el Barça
de esta temporada hay un Eric García y un Joan García. Emparejar por
apellido pondría la fecha de uno en la ficha del otro sin que nada lo
delatara. Por eso se usa `emparejar_jugador`, que se niega cuando dos
candidatos comparten apellido, y por eso se empareja EQUIPO A EQUIPO
en vez de contra toda la liga.

Los que no se emparejan NO se inventan: se quedan fuera y se cuentan
al final, con su motivo.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, RAIZ)

from backend.ml import edades as ed                        # noqa: E402
from backend.ml.emparejar_jugadores import emparejar_jugador  # noqa: E402
from backend.scrapers.football_data import football_client   # noqa: E402
from backend.scrapers.understat import (                     # noqa: E402
    get_league_players, _normaliza)
from backend.temporada import temporada_actual              # noqa: E402

LIGAS = ("PD", "PL", "SA", "BL1", "FL1")


async def una_liga(codigo: str, season: int) -> dict:
    codigo = codigo.upper()
    print(f"\n=== {codigo} {season}/{str(season + 1)[-2:]} "
          f"{'=' * 30}")

    print("  Understat...", end=" ", flush=True)
    de_understat = await get_league_players(codigo, season)
    print(f"{len(de_understat)} jugadores")

    print("  Clasificación (para saber qué equipos hay)...",
          end=" ", flush=True)
    tabla = (await football_client.get_standings(codigo)).get("table", [])
    print(f"{len(tabla)} equipos")

    jugadores, sin_emparejar, motivos = {}, [], {}
    for i, fila in enumerate(tabla, 1):
        nombre_equipo = fila["team_name"]
        print(f"  [{i:>2}/{len(tabla)}] {nombre_equipo:<28}",
              end=" ", flush=True)

        equipo = await football_client.get_team(fila["team_id"])
        plantilla = equipo.get("squad") or []

        # Sólo los de ESTE equipo. Contra toda la liga, dos apellidos
        # iguales en equipos distintos serían un cambiazo invisible.
        corto = _normaliza(equipo.get("name", nombre_equipo))
        suyos = [p for p in de_understat
                 if _normaliza(p.get("team", "")) == corto]

        hechos = 0
        for j in plantilla:
            if not j.get("dateOfBirth"):
                motivos["sin_fecha_en_football_data"] = \
                    motivos.get("sin_fecha_en_football_data", 0) + 1
                continue
            encontrado, motivo = emparejar_jugador(
                j.get("name"), suyos, clave=lambda x: x.get("name", ""))
            if not encontrado:
                motivos[motivo] = motivos.get(motivo, 0) + 1
                sin_emparejar.append({"equipo": nombre_equipo,
                                      "nombre": j.get("name"),
                                      "motivo": motivo})
                continue
            jugadores[str(encontrado.get("player_id"))] = {
                "nacimiento": j["dateOfBirth"][:10],
                "nacionalidad": j.get("nationality"),
                "nombre_football_data": j.get("name"),
                "nombre_understat": encontrado.get("name"),
                "equipo": nombre_equipo,
            }
            hechos += 1
        print(f"{hechos:>3} de {len(plantilla):>3}"
              f"{'   (Understat no tiene este equipo)' if not suyos else ''}")

    return {
        "liga": codigo,
        "season": season,
        "descargado": date.today().isoformat(),
        "jugadores_en_understat": len(de_understat),
        "emparejados": len(jugadores),
        "motivos_de_los_que_no": motivos,
        "sin_emparejar": sin_emparejar,
        "jugadores": jugadores,
    }


async def main():
    codigos = [c.upper() for c in sys.argv[1:]] or list(LIGAS)
    malos = [c for c in codigos if c not in LIGAS]
    if malos:
        # Mejor parar que bajar media cosa: una liga que Understat no
        # cubre deja un fichero vacío que parece bueno.
        print(f"No conozco {', '.join(malos)}. Las que hay: "
              f"{', '.join(LIGAS)}")
        return 1

    season = temporada_actual()
    os.makedirs(ed.CARPETA, exist_ok=True)

    resumen = []
    for codigo in codigos:
        datos = await una_liga(codigo, season)
        destino = ed.ruta(codigo, season)
        with open(destino, "w", encoding="utf-8") as fh:
            json.dump(datos, fh, indent=2, ensure_ascii=False)
        resumen.append((codigo, datos))
        print(f"  -> {os.path.relpath(destino, RAIZ)}")

    print(f"\n{'=' * 46}\nRESUMEN\n{'=' * 46}")
    for codigo, d in resumen:
        n, total = d["emparejados"], d["jugadores_en_understat"]
        pct = (100 * n / total) if total else 0
        print(f"  {codigo:<5} {n:>4} fechas para {total:>4} jugadores "
              f"de Understat  ({pct:.0f} %)")
        for motivo, cuantos in sorted(d["motivos_de_los_que_no"].items(),
                                      key=lambda x: -x[1]):
            print(f"          {cuantos:>4}  {motivo}")
    print("\nLos que no se han emparejado NO llevan edad, y la pantalla")
    print("lo dice. Un jugador sin edad se queda en la lista: no haber")
    print("podido emparejarlo no es motivo para darlo por viejo.\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
