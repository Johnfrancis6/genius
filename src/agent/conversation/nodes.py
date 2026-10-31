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
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent.conversation.meny import CALLBACK_AUTRE, MENU_PAR_TITRE, LigneMenu
from agent.conversation.replies import render_reply, texte_localisation
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
from agent.modules.lieux.recherche import Statut, chercher_lieux
from agent.modules.lieux.rendu import rendre_recherche
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
        return {
            k: v for k, v in state["search"].items() if k in ("lat", "lng", "place_name", "address")
        }
    return {}

ATTENTE_VIDE: dict[str, Any] = {
    "awaiting": None,
    "awaiting_since": None,
    "awaiting_detail": None,
    "step": "start",
}


async def _recents(messages: MessageStore, state: ConversationState, limit: int) -> list[Any]:
    try:
        return await messages.recent(state["user_id"], limit=limit)
    except Exception as e:
        logger.warning("route : lecture des messages échouée : %s", type(e).__name__)
        return []


def _afficher_menu(premier: bool) -> dict[str, Any]:
    return {
        "reply_key": "menu_accueil" if premier else "menu_rappel",
        "step": "menu",
        "awaiting": "choice",
        "awaiting_since": datetime.now(UTC).isoformat(),
        "awaiting_detail": "menu",
    }


def _appliquer_ligne(state: ConversationState, ligne: LigneMenu) -> dict[str, Any]:
    if ligne.callback == CALLBACK_AUTRE:
        return {"intent": "unknown", "reply_key": "menu_autre", "step": "start"}
    search = _search_neuf(state)
    if ligne.kind:
        search = {**search, "kind": ligne.kind}
    return {"intent": ligne.intent, "step": "start", "search": search}
def creer_noeud_route(messages: MessageStore) -> Noeud:
    async def route(state: ConversationState) -> dict[str, Any]:
        recents = await _recents(messages, state, 2)
        dernier = recents[-1] if recents and recents[-1].direction == "in" else None
        texte = (dernier.text or "") if dernier is not None else ""
        # Premier message : seule ligne en base = le message en cours, et c'est du texte.
        premier = len(recents) == 1 and dernier is not None and state["msg_type"] == "text"
        maj: dict[str, Any] = {}
        awaiting = state["awaiting"]

        # Réponse au menu : titre exact d'abord, sinon texte libre (classé plus bas).
        if awaiting and state["awaiting_detail"] == "menu":
            maj |= ATTENTE_VIDE
            awaiting = None
            ligne = MENU_PAR_TITRE.get(texte.strip().casefold())
            if ligne is not None:
                return maj | _appliquer_ligne(state, ligne)

        intent: Intent
        if awaiting:
            intent = state["intent"]  # awaiting actif : intent persisté, sans appel LLM
        elif premier and not _est_sobre(state):
            intent = "menu"
        else:
            intent = await _classer(messages, state)
        maj["intent"] = intent

        if intent == "menu" and not _est_sobre(state):
            maj |= _afficher_menu(premier)
        elif intent == "out_of_scope":
            maj["reply_key"] = "hors_perimetre"
        elif intent == "human_help":
            maj["reply_key"] = "aide_humaine"
        elif intent in INTENTS_A_CLARIFIER and state["step"] == "answered":
            # Nouvelle demande : on garde mobilité, situation et identité.
            maj["step"] = "start"
            maj["search"] = _search_neuf(state)
        return maj

    return route

def apres_route(state: ConversationState) -> Literal["fin", "clarificateur", "lieux", "genius"]:
    """Arête après route : fin, clarificateur (search/transport non terminés), lieux ou genius."""
    if state["reply_key"] or state["reply_text"]:
        return "fin"
    if state["intent"] in INTENTS_A_CLARIFIER and state["step"] != "answered":
        return "clarificateur"
    if state["intent"] == "search":
        return "lieux"
    return "genius"


def apres_clarificateur(state: ConversationState) -> Literal["lieux", "genius", "fin"]:
    """Même règle de fin que suite_ou_fin ; ensuite lieux pour search, genius sinon."""
    if suite_ou_fin(state) == "fin":
        return "fin"
    return "lieux" if state["intent"] == "search" else "genius"


def _manquants(connu: Mapping[str, Any], identite: bool, intent: str) -> list[Item]:
    s = connu["search"]
    localisation_connue = bool(s.get("quartier") or ("lat" in s and "lng" in s))
    manquants: list[Item] = []
    if intent == "search" and not s.get("kind"):
        manquants.append("kind")
    if connu["mobility"] is None:
        manquants.append("mobility")
    if connu["mobility"] == "cannot_move" and not identite:
        manquants.append("identity")
    if connu["situation"] is None:
        manquants.append("situation")
    if not localisation_connue:
        manquants.append("location")
    return manquants

# ===========================
#  Clarificateur
# ===========================

MAX_CAR_QUESTION = 300
MAX_QUESTIONS = 6
Item = Literal["kind", "mobility", "identity", "situation", "location"]
KINDS_VALIDES = frozenset({"pharmacy", "health_center", "on_call"})
AWAITING_PAR_ITEM: dict[Item, Awaiting] = {
    "kind": "choice",
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
        f"- intent : {state['intent']}",
        f"- mobility : {state['mobility']}",
        f"- situation : {state['situation']}",
        f"- quartier : {s.get('quartier')}",
        f"- kind : {s.get('kind')}",
        f"- position WhatsApp reçue : {'oui' if 'lat' in s and 'lng' in s else 'non'}",
        f"- pièce d'identité reçue : {'oui' if identite else 'non'}",
    ]
    if state["image_instruction"]:
        lignes.append(f"CONSIGNE IMAGE : {state['image_instruction']}")
    if _est_sobre(state):
        lignes.append(REGISTRE_SOBRE_CLARIF)
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
        if sortie.kind and sortie.kind.strip() in KINDS_VALIDES:
            search["kind"] = sortie.kind.strip()
    return {"mobility": mobility, "situation": situation, "search": search}

STEMS_PROPRES: dict[Item, tuple[str, ...]] = {
    "kind": ("pharmacie", "centre", "type", "lieu"),
    "mobility": ("déplac",),
    "identity": ("identit", "pièce"),
    "situation": ("situation", "se passe", "expliquer"),
}
STEMS_DISTINCTIFS: dict[Item, tuple[str, ...]] = {
    "mobility": ("déplac",),
    "identity": ("identit",),
    "situation": ("situation",),
    "location": ("quartier", "position"),
}


def _question_valide(item: Item, question: str) -> bool:
    """Garde-fou : une question, sur l'information demandée seulement."""
    q = question.casefold()
    if question.count("?") != 1:
        return False
    if not any(m in q for m in STEMS_PROPRES.get(item, ())):
        return False
    autres = (m for i, mots in STEMS_DISTINCTIFS.items() if i != item for m in mots)
    return not any(m in q for m in autres)
def creer_noeud_clarificateur(messages: MessageStore) -> Noeud:
    async def clarificateur(state: ConversationState) -> dict[str, Any]:
        identite = state["identity_received"] or _identite_lue(state)
        sortie = await _extraire(messages, state, identite)
        connu = _fusion(state, sortie)
        base: dict[str, Any] = {**connu, "identity_received": identite}
        manquants = _manquants(connu, identite, state["intent"])

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
        awaiting = AWAITING_PAR_ITEM[item]
        question = ""
        if item == "location":
            question = texte_localisation(
                state["intent"], connu["search"].get("kind"), _est_sobre(state)
            )
        elif (
            sortie is not None
            and sortie.awaiting_detail == item
            and _question_valide(item, sortie.question)
        ):
            question = sortie.question
        if not question:
            question = render_reply("clarif_kind" if item == "kind" else f"clarif_{awaiting}")
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
    "CONSIGNE DE SERVICE : le transport et le contact d'un médecin ne sont pas "
    "encore disponibles. Si le patient en demande un, explique simplement que ce "
    "service n'est pas encore disponible. Ne promets ni réservation, ni appel. "
    "La recherche de lieux est faite par un autre module : ne cite jamais toi-même "
    "de lieu, d'horaire ni de numéro."
)
CONSIGNE_SOBRE = (
    "REGISTRE : sobre. La situation est peut-être sérieuse. Calme et direct, "
    "l'action utile en premier, phrases très courtes, une demi-phrase d'empathie "
    "au plus, aucun emoji, aucune réassurance. Gras réservé à l'action ou au numéro."
)
REGISTRE_SOBRE_CLARIF = "REGISTRE : sobre. Question courte et directe, aucun emoji."


def _est_sobre(state: ConversationState) -> bool:
    return Level(state["urgency_level"]).value >= Level.INCERTAIN.value


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

        if _est_sobre(state):
            consignes.append(CONSIGNE_SOBRE)
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
# A_COMPLETER = frozenset({Statut.TYPE_MANQUANT, Statut.POSITION_MANQUANTE, Statut.QUARTIER_INCONNU})
SUITE_PAR_STATUT: dict[Statut, tuple[Awaiting, str]] = {
    Statut.TYPE_MANQUANT: ("choice", "kind"),
        Statut.POSITION_MANQUANTE: ("free_text", "quartier"),
    Statut.QUARTIER_INCONNU: ("location", "location"),
}


def creer_noeud_lieux(sessionmaker: async_sessionmaker[AsyncSession]) -> Noeud:
    async def lieux(state: ConversationState) -> dict[str, Any]:
        
        try:
            async with sessionmaker() as session:
                recherche = await chercher_lieux(session, state["search"])
        except SQLAlchemyError as e:
            logger.warning("lieux : base indisponible : %s", type(e).__name__)
            return {"reply_key": "probleme_technique"}
        maj: dict[str, Any] = {"reply_text": rendre_recherche(recherche, _est_sobre(state))}
        suite = SUITE_PAR_STATUT.get(recherche.statut)
        if suite is not None:
            awaiting, detail = suite
            maj |= {
                "step": "clarify",
                "awaiting": awaiting,
                "awaiting_since": datetime.now(UTC).isoformat(),
                "awaiting_detail": detail,
            }
            if recherche.statut is Statut.QUARTIER_INCONNU:
                # Sans ça, _manquants juge la localisation connue et on boucle.
                maj["search"] = {k: v for k, v in state["search"].items() if k != "quartier"}
        return maj

    return lieux