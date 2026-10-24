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


class CompeticionNoIncluida(Exception):
    """Esta competición no entra en el plan contratado de la fuente.

    POR QUÉ ESTE ERROR EXISTE APARTE
    --------------------------------
    football-data contesta a una competición fuera de tu plan con:

        400  {"message": "Your API token is invalid."}

    Y eso es MENTIRA, o por lo menos es engañoso. La clave es
    perfectamente válida: en el mismo arranque, con siete segundos de
    diferencia, Premier y Ligue 1 contestaron 200 y La Liga, Serie A
    y Bundesliga contestaron ese 400.

    Repetir ese mensaje al visitante es decirle que la aplicación
    está rota cuando lo que pasa es que esa liga no está incluida.
    Son dos cosas distintas y llevan a decisiones distintas: una se
    arregla cambiando la clave, la otra pagando un plan o mirando
    otra liga.

    CÓMO SE DISTINGUE, SIN MIRAR EL TEXTO
    -------------------------------------
    No por el mensaje, que viene en el idioma del que pregunta
    («Your API token is invalid» / «Su token de API no es válido»),
    sino por un hecho: si esa misma clave ya ha traído datos de otra
    competición, la clave NO está rota.
    """

    def __init__(self, competicion: str, plan: str = "gratuito"):
        self.competicion = competicion
        self.plan = plan
        super().__init__(
            f"La competición {competicion} no entra en el plan {plan} "
            f"de football-data"
        )


class ClaveInvalida(Exception):
    """La clave no vale para nada: no ha funcionado ni una vez."""

    def __init__(self, detalle: str = ""):
        self.detalle = detalle
        super().__init__(
            "La clave de football-data no es válida"
            + (f": {detalle}" if detalle else "")
        )


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
