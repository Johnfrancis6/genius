"""Nœuds du graphe V1 : transcrire, urgence, traiter_image (+ arête suite_ou_fin)."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from agent.conversation.replies import render_reply
from agent.conversation.state import (
    Awaiting,
    ConversationState,
    Intent,
    Mobility,
    Situation,
)
from agent.core import llm
from agent.core.prompt import CLARIFICATEUR, GENIUS, INTENT_PROMPT
from agent.modules.images.image_data import Call_VLM, TypeImage
from agent.modules.images.image_tool import (
    Extracteur,
    Status,
    analyser_image_en_attente,
)
from agent.safety.evaluation import evaluer_urgence
from agent.safety.levels import Level, raise_only, urgency_from_level, worst
from agent.stores import ExtractionStore, MessageStore, PgImageStore

logger = logging.getLogger(__name__)


class Noeud(Protocol):
    async def __call__(self, state: ConversationState) -> dict[str, Any]: ...


def _maj_niveau(niveau: Level) -> dict[str, Any]:
    """urgency_level est la source ; urgency en est dérivé."""
    return {"urgency_level": int(niveau), "urgency": urgency_from_level(niveau)}


def suite_ou_fin(state: ConversationState) -> Literal["suite", "fin"]:
    """Arête : fin du tour dès qu'une réponse est prête."""
    return "fin" if state["reply_key"] or state["reply_text"] else "suite"


async def transcrire(state: ConversationState) -> dict[str, Any]:
    """Audio : réponse fixe, fin du tour (STT pas encore branché)."""
    if state["msg_type"] == "audio":
        return {"reply_key": "audio_bientot"}
    return {}


async def urgence(state: ConversationState) -> dict[str, Any]:
    """Le moteur seul note la gravité ; le niveau ne baisse jamais ici."""
    courant = Level(state["urgency_level"])
    try:
        decide = evaluer_urgence(state).new_state.level
    except Exception as e:
        logger.warning("evaluer_urgence a échoué : %s", type(e).__name__)
        decide = Level.INCERTAIN  # un moteur en panne ne vaut jamais NORMAL
    niveau = worst(courant, decide)
    maj = _maj_niveau(niveau)
    if niveau >= Level.URGENT:
        maj["reply_key"] = "urgence"
    return maj


def creer_noeud_traiter_image(
    images: PgImageStore,
    resultats: ExtractionStore,
    appel: Call_VLM,
    extracteurs: dict[TypeImage, Extracteur],
) -> Noeud:
    async def traiter_image(state: ConversationState) -> dict[str, Any]:
        if not state["pending_image_id"]:
            return {}
        maj = await analyser_image_en_attente(state, images, resultats, appel, extracteurs)
        if maj["image_status"] == Status.MEDICAL_SIGN.value:
            niveau = raise_only(Level(state["urgency_level"]), Level.INCERTAIN)
            maj.update(_maj_niveau(niveau))
        return maj

    return traiter_image


# ===========================
#  Route (intention)
# ===========================

INTENTS_A_CLARIFIER = frozenset({"search", "transport"})
MAX_CAR_MESSAGE = 300


class _IntentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Intent


def _coupe(texte: str) -> str:
    return texte if len(texte) <= MAX_CAR_MESSAGE else texte[:MAX_CAR_MESSAGE] + "…"


async def _classer(messages: MessageStore, state: ConversationState) -> Intent:
    """Classification Groq. Toute erreur : "unknown" (le chemin vers genius, sans risque)."""
    try:
        records = await messages.recent(state["user_id"], limit=4)
    except Exception as e:
        logger.warning("route : lecture des messages échouée : %s", type(e).__name__)
        return "unknown"
    if not records or records[-1].direction == "out" or not records[-1].text:
        return "unknown"  # location, image seule, etc.

    lignes = [
        f"{'Genius' if r.direction == 'out' else 'Patient'} : {_coupe(r.text)}"
        for r in records[:-1]
        if r.text
    ]
    contenu = f"DERNIER MESSAGE : {_coupe(records[-1].text)}"
    if lignes:
        contenu = "Messages précédents :\n" + "\n".join(lignes) + "\n\n" + contenu
    try:
        brut = await llm.complete_text(
            [
                {"role": "system", "content": INTENT_PROMPT},
                {"role": "user", "content": contenu},
            ],
            json_mode=True,
            temperature=0,
            max_tokens=512,
        )
        return _IntentOut.model_validate_json(brut).intent
    except (llm.LLMError, ValidationError) as e:
        logger.warning("route : classification échouée : %s", type(e).__name__)
        return "unknown"


def _search_neuf(state: ConversationState) -> dict[str, Any]:
    """Nouvelle demande : localisation vide, sauf la position envoyée dans ce tour."""
    if state["msg_type"] == "location":
        return {k: v for k, v in state["search"].items() if k in ("lat", "lng")}
    return {}


def creer_noeud_route(messages: MessageStore) -> Noeud:
    async def route(state: ConversationState) -> dict[str, Any]:
        # awaiting actif : l'intent persisté est conservé, sans appel LLM
        intent: Intent = state["intent"] if state["awaiting"] else await _classer(messages, state)
        maj: dict[str, Any] = {"intent": intent}
        if intent == "out_of_scope":
            maj["reply_key"] = "hors_perimetre"
        elif intent == "human_help":
            maj["reply_key"] = "aide_humaine"
        elif intent in INTENTS_A_CLARIFIER and state["step"] == "answered":
            # Nouvelle demande : on garde mobilité, situation et identité.
            maj["step"] = "start"
            maj["search"] = _search_neuf(state)
        return maj

    return route


def apres_route(state: ConversationState) -> Literal["fin", "clarificateur", "genius"]:
    """Arête après route : fin, clarificateur (search/transport non terminés) ou genius."""
    if state["reply_key"] or state["reply_text"]:
        return "fin"
    if state["intent"] in INTENTS_A_CLARIFIER and state["step"] != "answered":
        return "clarificateur"
    return "genius"


# ===========================
#  Clarificateur
# ===========================

MAX_QUESTIONS = 5
MAX_CAR_QUESTION = 300
Item = Literal["mobility", "identity", "situation", "location"]
AWAITING_PAR_ITEM: dict[Item, Awaiting] = {
    "mobility": "choice",
    "identity": "image",
    "situation": "free_text",
    "location": "location",
}


class _ClarifOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mobility: Mobility | None = None
    situation: Situation | None = None
    quartier: str | None = Field(default=None, max_length=100)
    kind: str | None = Field(default=None, max_length=60)
    next_awaiting: Awaiting | None = None
    awaiting_detail: Item | None = None
    question: str = Field(default="", max_length=MAX_CAR_QUESTION)

    @field_validator("question")
    @classmethod
    def _une_question(cls, v: str) -> str:
        v = v.strip()
        if v.count("?") > 1:
            raise ValueError("plusieurs questions")
        return v

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        d = self.awaiting_detail
        if d is not None and self.next_awaiting != AWAITING_PAR_ITEM[d]:
            raise ValueError("awaiting incohérent")
        return self


def _identite_lue(state: ConversationState) -> bool:
    return (
        state["image_status"] == Status.EXTRACTED.value
        and state["image_type_detected"] == "piece_identite"
    )


async def _contexte(messages: MessageStore, state: ConversationState, identite: bool) -> str:
    try:
        records = await messages.recent(state["user_id"], limit=8)
    except Exception as e:
        logger.warning("clarificateur : lecture échouée : %s", type(e).__name__)
        records = []
    s = state["search"]
    lignes = [
        "ÉTAT CONNU",
        f"- mobility : {state['mobility']}",
        f"- situation : {state['situation']}",
        f"- quartier : {s.get('quartier')}",
        f"- kind : {s.get('kind')}",
        f"- position WhatsApp reçue : {'oui' if 'lat' in s and 'lng' in s else 'non'}",
        f"- pièce d'identité reçue : {'oui' if identite else 'non'}",
    ]
    if state["image_instruction"]:
        lignes.append(f"CONSIGNE IMAGE : {state['image_instruction']}")
    lignes += ["", "MESSAGES"]
    lignes += [
        f"{'Genius' if r.direction == 'out' else 'Patient'} : {_coupe(r.text)}"
        for r in records
        if r.text
    ]
    return "\n".join(lignes)


async def _extraire(
    messages: MessageStore, state: ConversationState, identite: bool
) -> _ClarifOut | None:
    """Une relance au plus ; LLMError : None tout de suite ; échec : None (question de repli)."""
    msgs = [
        {"role": "system", "content": CLARIFICATEUR},
        {"role": "user", "content": await _contexte(messages, state, identite)},
    ]
    for essai in range(2):
        try:
            brut = await llm.complete_text(msgs, json_mode=True, temperature=0, max_tokens=1024)
        except llm.LLMError:
            logger.warning("clarificateur : appel LLM échoué")
            return None
        try:
            return _ClarifOut.model_validate_json(brut)
        except ValidationError as e:
            logger.warning("clarificateur : sortie invalide")
            if essai == 0:
                erreurs = "; ".join(
                    f"{'.'.join(map(str, x['loc']))}: {x['msg']}"
                    for x in e.errors(include_url=False, include_input=False)
                )
                msgs = [
                    *msgs,
                    {"role": "assistant", "content": brut},
                    {
                        "role": "user",
                        "content": "Ta sortie est invalide (" + erreurs + "). "
                        "Renvoie uniquement un objet json valide avec exactement les clés demandées.",
                    },
                ]
    return None


def _fusion(state: ConversationState, sortie: _ClarifOut | None) -> dict[str, Any]:
    """Une valeur connue n'est jamais écrasée par null."""
    search: dict[str, Any] = dict(state["search"])
    mobility, situation = state["mobility"], state["situation"]
    if sortie is not None:
        mobility = sortie.mobility or mobility
        situation = sortie.situation or situation
        if sortie.quartier and sortie.quartier.strip():
            search["quartier"] = sortie.quartier.strip()
        if sortie.kind and sortie.kind.strip():
            search["kind"] = sortie.kind.strip()
    return {"mobility": mobility, "situation": situation, "search": search}


def _manquants(connu: Mapping[str, Any], identite: bool) -> list[Item]:
    manquants: list[Item] = []
    if connu["mobility"] is None:
        manquants.append("mobility")
    if connu["mobility"] == "cannot_move" and not identite:
        manquants.append("identity")
    if connu["situation"] is None:
        manquants.append("situation")
    s = connu["search"]
    if not (s.get("quartier") or ("lat" in s and "lng" in s)):
        manquants.append("location")
    return manquants


def creer_noeud_clarificateur(messages: MessageStore) -> Noeud:
    async def clarificateur(state: ConversationState) -> dict[str, Any]:
        identite = state["identity_received"] or _identite_lue(state)
        sortie = await _extraire(messages, state, identite)
        connu = _fusion(state, sortie)
        base: dict[str, Any] = {**connu, "identity_received": identite}
        manquants = _manquants(connu, identite)

        if not manquants or state["clarify_turns"] >= MAX_QUESTIONS:
            return {
                **base,
                "step": "answered",
                "clarify_turns": 0,
                "awaiting": None,
                "awaiting_since": None,
                "awaiting_detail": None,
                "expected_image_type": None,
            }

        # Le LLM choisit parmi les informations manquantes ; jamais une info connue.
        item: Item = manquants[0]
        question = ""
        if sortie is not None and sortie.question:
            detail = sortie.awaiting_detail
            if detail is not None and detail in manquants:
                item, question = detail, sortie.question
        awaiting = AWAITING_PAR_ITEM[item]
        if not question:
            question = render_reply(f"clarif_{awaiting}")
        return {
            **base,
            "step": "clarify",
            "reply_text": question,
            "awaiting": awaiting,
            "awaiting_since": datetime.now(UTC).isoformat(),
            "awaiting_detail": item,
            "expected_image_type": "piece_identite" if awaiting == "image" else None,
            "clarify_turns": state["clarify_turns"] + 1,
        }

    return clarificateur


# ===========================
#  Genius (réponse)
# ===========================

HISTORIQUE_GENIUS = 20
CONSIGNE_ATTENTE = (
    "CONSIGNE DE SERVICE : la recherche de lieux, le transport et le contact d'un "
    "médecin ne sont pas encore disponibles. Si le patient en demande un, explique "
    "simplement que ce service n'est pas encore disponible. Ne promets ni recherche, "
    "ni réservation, ni appel."
)


async def _historique(messages: MessageStore, user_id: str) -> list[dict[str, str]]:
    """Historique du patient. Le message en cours y est déjà : ne pas le rajouter."""
    records = await messages.recent(user_id, limit=HISTORIQUE_GENIUS)
    return [
        {"role": "assistant" if r.direction == "out" else "user", "content": r.text}
        for r in records
        if r.text
    ]


def creer_noeud_genius(messages: MessageStore) -> Noeud:
    async def genius(state: ConversationState) -> dict[str, Any]:
        consignes = [CONSIGNE_ATTENTE]
        if state["image_instruction"]:
            consignes.append(f"CONSIGNE IMAGE : {state['image_instruction']}")
        historique = await _historique(messages, state["user_id"])
        chat: list[dict[str, str]] = [
            {"role": "system", "content": "\n\n".join([GENIUS, *consignes])},
            *historique,
        ]
        # Image ou position : pas de texte en base, le LLM a besoin d'un tour patient.
        if state["msg_type"] in ("image", "location"):
            chat.append(
                {"role": "user", "content": f"[Le patient a envoyé : {state['msg_type']}.]"}
            )
        try:
            texte = await llm.complete_text(chat)
        except llm.LLMError as e:
            logger.warning("genius : appel LLM échoué : %s", type(e).__name__)
            return {"reply_key": "probleme_technique"}
        return {"reply_text": texte.strip()}

    return genius
