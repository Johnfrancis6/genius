"""Composition : stores, graphe compilé une fois, client PyWa et handler des messages."""

from fastapi import FastAPI
from pywa_async.handlers import (
    CallbackButtonHandler,
    CallbackSelectionHandler,
    FlowCompletionHandler,
    MessageHandler,
)

from agent.conversation.graph import build_graph
from agent.conversation.replies import verifier_numeros_urgence
from agent.core.llm import appel_vlm
from agent.db import get_sessionmaker
from agent.modules.images.extracteurs import extraire_ordonnance, extraire_piece_identite
from agent.modules.images.image_data import TypeImage
from agent.modules.images.image_tool import Extracteur
from agent.settings import get_setting
from agent.stores import ConversationStateStore, ExtractionStore, MessageStore, PgImageStore
from agent.whatsapp.client import creer_client
from agent.whatsapp.handler import Traiteur


def demarrer_whatsapp(app: FastAPI) -> None:
    """À appeler dans le lifespan. Lève RuntimeError si la config Meta est incomplète."""
    if not verifier_numeros_urgence():
        raise RuntimeError("EMERGENCY_NUMBERS vide : démarrage refusé")
    images = PgImageStore()
    resultats = ExtractionStore()
    messages = MessageStore()
    extracteurs: dict[TypeImage, Extracteur] = {
        "ordonnance": extraire_ordonnance,
        "piece_identite": extraire_piece_identite,
    }
    graphe = build_graph(images, resultats, messages, appel_vlm, extracteurs, get_sessionmaker())
    wa = creer_client(app)
    reglages = get_setting()
    traiteur = Traiteur(
        wa,
        graphe,
        images,
        messages,
        ConversationStateStore(),
        flow_id=reglages.WHATSAPP_FLOW_ID,
        flow_brouillon=reglages.WHATSAPP_FLOW_BROUILLON,
    )
    wa.add_handlers(
        MessageHandler(traiteur.traiter),  # type: ignore[arg-type]
        CallbackButtonHandler(traiteur.traiter_clic),  # type: ignore[arg-type]
        CallbackSelectionHandler(traiteur.traiter_clic),  # type: ignore[arg-type]
        FlowCompletionHandler(traiteur.traiter_flow),  # type: ignore[arg-type]
    )
