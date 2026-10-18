# -*- coding: utf-8 -*-
"""Calcula una edición con el motor y la deja en edicion.json, para que
el comprobador de maqueta tenga con qué trabajar.

    python3 generar_edicion.py
"""
import json
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(AQUI)))

from backend.ml import simulador as S     # noqa: E402

CRUDOS = os.path.join(os.path.dirname(AQUI), "datos", "laliga_2026_27.json")
# La fecha en que el fichero de pruebas estaba al día. Con la de hoy el
# motor lo rechaza por desfasado, que es justo lo que debe hacer.
AL_DIA = "2026-09-22"


def main():
    with open(CRUDOS, encoding="utf-8") as fh:
        crudos = json.load(fh)
    ed = S.edicion(crudos, "PD", "La Liga", hoy=AL_DIA)
    salida = os.path.join(AQUI, "edicion.json")
    with open(salida, "w", encoding="utf-8") as fh:
        json.dump(ed, fh, ensure_ascii=False)
    print(f"jornada {ed['jornada']}, {len(ed['tabla'])} equipos "
          f"-> {os.path.basename(salida)}")


if __name__ == "__main__":
    main()
