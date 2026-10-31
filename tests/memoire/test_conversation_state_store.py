"""Tests de ConversationStateStore sur un vrai PostgreSQL (testcontainers)."""

import json

import pytest
from sqlalchemy import select

from agent.conversation.state import PERSISTED_KEYS, build_turn_state
from agent.db import session_scope
from agent.memoire.crypto import decrypt_text
from agent.models import ConversationStateRow  # ADAPTE si le modèle est ailleurs
from agent.stores import ConversationStateStore, forget_user, get_or_create_user

pytestmark = [
    pytest.mark.asyncio(loop_scope="session"),
    pytest.mark.usefixtures("clean_db"),
]

ETAT = {
    "awaiting": "location",
    "awaiting_since": "2026-10-25T10:00:00+00:00",
    "search": {"kind": "pharmacie", "quartier": "Zogona"},
    "recent_results": ["r1", "r2"],
    "step": "clarify",
    "expected_image_type": "piece_identite",
    "pending_image_id": "img1",
    "mobility": "cannot_move",
    "situation": "pregnant",
    "awaiting_detail": "quartier",
    "clarify_turns": 2,
    "identity_received": True,
}


def phone(n: int) -> str:
    """Numéro fictif au format E.164 (indicatif du Burkina Faso)."""
    return f"+2267{n:07d}"


async def make_user(n: int = 1) -> str:
    return str(await get_or_create_user(phone(n)))


async def ligne_chiffree(user_key: str):
    from agent.stores import to_uuid

    async with session_scope() as session:
        return (
            await session.execute(
                select(ConversationStateRow.state_enc).where(
                    ConversationStateRow.user_id == to_uuid(user_key)
                )
            )
        ).scalar_one()


async def test_load_sans_etat():
    store = ConversationStateStore()
    assert await store.load(await make_user()) == {}


async def test_aller_retour_des_cles_persistees():
    store, user = ConversationStateStore(), await make_user()
    await store.save(user, {**ETAT, "intent": "search"})
    charge = await store.load(user)
    assert charge == {**ETAT, "intent": "search"}
    assert set(charge) - {"intent"} == set(PERSISTED_KEYS)


async def test_cles_non_persistees_jamais_sauvees():
    store, user = ConversationStateStore(), await make_user()
    await store.save(
        user,
        {
            **ETAT,
            "urgency_level": 4,
            "urgency": True,
            "reply_text": "texte",
            "image_instruction": "consigne",
            "user_id": user,
        },
    )
    charge = await store.load(user)
    for cle in ("urgency_level", "urgency", "reply_text", "image_instruction", "user_id"):
        assert cle not in charge
    brut = json.loads(decrypt_text(await ligne_chiffree(user)))
    assert "consigne" not in json.dumps(brut) and "texte" not in json.dumps(brut)


async def test_intent_sauve_seulement_si_awaiting():
    store, user = ConversationStateStore(), await make_user()
    await store.save(user, {**ETAT, "awaiting": None, "intent": "search"})
    assert "intent" not in await store.load(user)
    await store.save(user, {**ETAT, "intent": "transport"})
    assert (await store.load(user))["intent"] == "transport"
    await store.save(user, ETAT)  # awaiting actif, intent absent
    assert (await store.load(user))["intent"] == "unknown"


async def test_deuxieme_save_remplace_le_premier():
    store, user = ConversationStateStore(), await make_user()
    await store.save(user, ETAT)
    await store.save(user, {"step": "answered", "clarify_turns": 0, "awaiting": None})
    assert await store.load(user) == {
        "step": "answered",
        "clarify_turns": 0,
        "awaiting": None,
    }


async def test_isolation_entre_utilisateurs():
    store = ConversationStateStore()
    u1, u2 = await make_user(1), await make_user(2)
    await store.save(u1, ETAT)
    assert await store.load(u2) == {}
    await store.save(u2, {"step": "start"})
    assert (await store.load(u1))["step"] == "clarify"


async def test_etat_chiffre_en_base():
    store, user = ConversationStateStore(), await make_user()
    await store.save(user, ETAT)
    brut = repr(await ligne_chiffree(user))
    assert "pregnant" not in brut and "Zogona" not in brut


async def test_clear():
    store, user = ConversationStateStore(), await make_user()
    await store.save(user, ETAT)
    await store.clear(user)
    assert await store.load(user) == {}


async def test_forget_user_supprime_l_etat():
    store, user = ConversationStateStore(), await make_user()
    await store.save(user, ETAT)
    assert await forget_user(user) is True
    assert await store.load(user) == {}


async def test_build_turn_state_apres_un_vrai_aller_retour():
    store, user = ConversationStateStore(), await make_user()
    await store.save(user, {**ETAT, "intent": "search"})
    etat = build_turn_state(user, "in1", "text", await store.load(user))
    assert etat["clarify_turns"] == 2 and etat["mobility"] == "cannot_move"
    assert etat["intent"] == "search"
    assert etat["urgency_level"] == 1 and etat["reply_text"] is None


async def test_build_turn_state_apres_un_etat_ancien_sans_nouveaux_champs():
    store, user = ConversationStateStore(), await make_user()
    await store.save(user, {"awaiting": "choice", "step": "menu", "intent": "weather"})
    etat = build_turn_state(user, "in2", "text", await store.load(user))
    assert etat["clarify_turns"] == 0 and etat["situation"] is None
    assert etat["intent"] == "weather" and etat["step"] == "menu"
