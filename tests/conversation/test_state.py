from agent.conversation.state import PERSISTED_KEYS, build_turn_state, new_turn
from agent.safety.levels import Level, urgency_from_level


def test_new_turn_demarre_a_normal():
    assert new_turn("u", "i", "text")["urgency_level"] == Level.NORMAL


def test_urgency_from_level():
    assert [urgency_from_level(n) for n in Level] == [False, False, True, True]


def test_ancien_etat_sans_nouveaux_champs():
    s = build_turn_state("u", "i", "text", {"awaiting": None, "step": "clarify"})
    assert s["clarify_turns"] == 0 and s["mobility"] is None and s["step"] == "clarify"


def test_cles_non_persistees():
    assert not {"urgency_level", "urgency", "image_instruction", "reply_text"} & set(PERSISTED_KEYS)


def test_intent_repris_seulement_si_awaiting():
    avec = build_turn_state("u", "i", "text", {"awaiting": "location", "intent": "search"})
    sans = build_turn_state("u", "i", "text", {"awaiting": None, "intent": "search"})
    assert avec["intent"] == "search" and sans["intent"] == "unknown"


def test_cles_non_persistees_ignorees():
    s = build_turn_state("u", "i", "text", {"urgency_level": 4, "reply_text": "x", "autre": 1})
    assert s["urgency_level"] == Level.NORMAL and s["reply_text"] is None
    assert "autre" not in s
