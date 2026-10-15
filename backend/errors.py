# backend/errors.py
# ============================================================
# Errores propios de Sportalyze.
#
# POR QUÉ EXISTE ESTE ARCHIVO
# ---------------------------
# Antes, cuando una fuente de datos fallaba, el scraper se tragaba la
# excepción y devolvía una lista vacía. La API respondía entonces:
#
#     HTTP 200   {"players": [], "summary": {}, "top_prospects": []}
#
# Es decir: «todo bien, no hay jugadores que cumplan tus criterios».
# Cuando la verdad era «la fuente lleva rota desde el primer día».
#
# Un cliente que lea eso toma una decisión equivocada y nunca se
# entera. Una lista vacía SÓLO puede significar «he mirado y no hay
# nada», jamás «no he podido mirar».
# ============================================================


class FuenteNoDisponible(Exception):
    """La fuente de datos externa no ha podido contestar.

    NO significa que no haya datos: significa que no se sabe. Quien la
    reciba debe devolver un 503, nunca un 200 con la lista vacía.
    """

    def __init__(self, fuente: str, detalle: str = ""):
        self.fuente = fuente
        self.detalle = detalle
        super().__init__(
            f"{fuente} no ha podido responder"
            + (f": {detalle}" if detalle else "")
        )
