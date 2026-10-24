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


class CuatrocientosSinExplicar(Exception):
    """football-data ha contestado 400 y no sabemos por qué.

    QUÉ HABÍA AQUÍ ANTES, Y POR QUÉ SE FUE
    --------------------------------------
    Aquí vivía `CompeticionNoIncluida`, que afirmaba que ese 400
    significaba «esta competición no entra en tu plan gratuito».
    Esa clase se escribió el 24 de octubre de 2026 con esta prueba:
    en un mismo arranque, con siete segundos entre llamadas, Premier
    y Ligue 1 contestaron 200 y La Liga, Serie A y Bundesliga
    contestaron 400 «Your API token is invalid». De ahí salió el
    razonamiento: la clave funciona, así que el 400 tiene que ser
    el plan.

    EL 25 DE OCTUBRE ESO SE CAYÓ. Revisando la web desplegada:

        11:0x  PL   200  (tabla completa de la Premier)
        11:0x  PD   200  (tabla completa de La Liga)
        11:1x  PL   503  «no entra en el plan»
        11:1x  FL1  503  «no entra en el plan»

    Premier devolvió la clasificación entera y minutos después la
    propia aplicación decía que no estaba en el plan. Ligue 1 hizo
    el camino contrario. Un plan contratado NO cambia cada minuto.
    Lo que varía es qué llamadas llegaron a entrar en la caché.

    O sea: el razonamiento de ayer era un segundo diagnóstico
    equivocado encima del primero. Y publicado, que es peor.

    QUÉ SE AFIRMA AHORA, Y QUÉ NO
    -----------------------------
    Sólo lo que está comprobado:

      · la clave no está rota, si ha traído datos alguna vez
      · esa competición sí funcionó antes, si está en el registro
      · el motivo del 400: NO SE SABE, y se dice así

    No se mira el texto del mensaje, igual que antes: llega en el
    idioma de quien pregunta («Your API token is invalid» / «Su
    token de API no es válido»), así que comprobarlo por texto se
    rompe el día que cambien de idioma o de redacción.

    Un hueco explicado vale más que un número inventado, y un «no
    sé por qué» vale más que un motivo que se contradice solo.
    """

    def __init__(self, competicion: str, habia_funcionado: bool = False):
        self.competicion = competicion
        self.habia_funcionado = habia_funcionado
        super().__init__(
            f"football-data ha contestado 400 para {competicion} y no se "
            f"sabe por qué"
            + (" (esa misma competición sí funcionó antes en este arranque)"
               if habia_funcionado else "")
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
