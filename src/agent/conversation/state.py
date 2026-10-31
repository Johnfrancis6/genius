from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Annotated, Any, Literal, TypedDict, cast

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
    "menu",

]
Mobility = Literal["can_move", "cannot_move"]
Situation = Literal["pregnant", "asthma", "sick_baby", "heart", "accident", "other"]

PERSISTED_KEYS: tuple[str, ...] = (
    "awaiting",
    "awaiting_since",
    "search",
    "recent_results",
    "step",
    "expected_image_type",
    "pending_image_id",
    "mobility",
    "situation",
    "awaiting_detail",
    "clarify_turns",
    "identity_received",
)
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
    place_name: str
    address: str


def keep_last(n: int) -> Callable[[list[str] | None, list[str] | None], list[str]]:
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

    # clarifier
    mobility: Mobility | None
    situation: Situation | None
    awaiting_detail: str | None  # sur quoi porte "choice" / "confirm"
    clarify_turns: int
    identity_received: bool

    # Routage
    intent: Intent
    urgency: bool
    reply_key: str | None
    reply_args: dict[str, str]
    urgency_level: int
    reply_text: str | None

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
    image_instruction: str | None


class EscalationStatus(StrEnum):
    MEDECIN_NOTIFIE = "medecin_notifie"
    SECOND_CANAL = "second_canal"
    SANS_REPONSE = "sans_reponse"
    ACCUSEE = "accusee"


def new_turn(conversation_id: str, inbound_id: str, msg_type: str) -> ConversationState:
    """Entrée d'un tour. conversation_id = str(users.id), repris dans user_id."""
    return {
        "conversation_id": conversation_id,
        "user_id": conversation_id,
        "inbound_id": inbound_id,
        "msg_type": msg_type,
        "intent": "unknown",
        "urgency_level": 1,
        "urgency": False,
        "reply_key": None,
        "reply_args": {},
        "reply_text": None,
        "mobility": None,
        "situation": None,
        "awaiting_detail": None,
        "clarify_turns": 0,
        "identity_received": False,
        "awaiting": None,
        "awaiting_since": None,
        "search": {},
        "recent_results": [],
        "step": "start",
        "pending_image_id": None,
        "expected_image_type": None,
        "image_status": None,
        "image_type_detected": None,
        "image_result_id": None,
        "image_instruction": None,
    }


def build_turn_state(
    conversation_id: str,
    inbound_id: str,
    msg_type: str,
    persisted: Mapping[str, Any] | None = None,
) -> ConversationState:
    """État d'entrée d'un tour : new_turn + clés persistées.

    `intent` n'est repris que si `awaiting` est actif dans l'état persisté.
    """
    state = new_turn(conversation_id, inbound_id, msg_type)
    if not persisted:
        return state
    data = cast(dict[str, Any], state)
    for k in persisted:
        if k in PERSISTED_KEYS:
            data[k] = persisted[k]
    if persisted.get("awaiting") and "intent" in persisted:
        state["intent"] = persisted["intent"]
    return state
