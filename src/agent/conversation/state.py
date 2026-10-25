from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

# L'intention de l'agent
Intent = Literal[
    "unknown",
    "search",
    "transport",
    "weather",
    "document",
    "image_analysis",
    "memory",
    "reminder",
    "prevention",
    "human_help",
    "out_of_scope",
]

# Les étapes qu'il va suivre
Step = Literal["start", "menu", "clarify", "collect", "answered"]

# La donnée attendue à la prochaine réponse de l'utilisateur
Awaiting = Literal["location", "choice", "confirm", "free_text", "image"]


class SearchParams(TypedDict, total=False):
    kind: str  # pharmacie, centre de santé, garde
    open_now: bool
    quartier: str
    lat: float
    lng: float


def keep_last(n: int):
    """Reducer : concatène puis ne garde que les n derniers éléments."""

    def _reduce(old: list[str] | None, new: list[str] | None) -> list[str]:
        if new is None:
            return []
        return ((old or []) + new)[-n:]

    return _reduce


class ConversationState(TypedDict, total=False):
    # Entrée de tour, réécrite à chaque message
    conversation_id: str  # = str(users.id)
    user_id: str  # = conversation_id
    inbound_id: str  # whatsapp_id du message en cours
    msg_type: str

    # Boucle outil du tour uniquement (ToolMessage).
    # L'historique n'est PAS ici : il vit dans MessageStore.
    messages: Annotated[list[AnyMessage], add_messages]

    # Routage
    intent: Intent
    urgency: bool
    reply_key: str | None
    reply_args: dict[str, str]

    # Conversation en cours
    awaiting: Awaiting | None
    awaiting_since: str | None
    search: SearchParams
    recent_results: Annotated[list[str], keep_last(10)]
    step: Step

    # Image
    pending_image_id: str | None
    expected_image_type: str | None
    image_status: str | None
    image_type_detected: str | None
    image_result_id: str | None


class EscalationStatus(StrEnum):
    MEDECIN_NOTIFIE = "medecin_notifie"
    SECOND_CANAL = "second_canal"
    SANS_REPONSE = "sans_reponse"
    ACCUSEE = "accusee"


def new_turn(
    conversation_id: str, inbound_id: str, msg_type: str
) -> ConversationState:
    """Entrée d'un tour. conversation_id = str(users.id), repris dans user_id."""
    return {
        "conversation_id": conversation_id,
        "user_id": conversation_id,
        "inbound_id": inbound_id,
        "msg_type": msg_type,
        "intent": "unknown",
        "urgency": False,
        "reply_key": None,
        "reply_args": {},
        "image_status": None,
        "image_type_detected": None,
        "image_result_id": None,
    }