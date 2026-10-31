"""Claviers WhatsApp (boutons, liste, Flow) choisis d'après ce que le clarificateur attend."""

from pywa_async import types

from agent.conversation.meny import MENU
from agent.settings import get_setting

Clavier = list[types.Button] | types.SectionList | types.FlowButton

BOUTONS_MOBILITE = (
    ("Je peux me déplacer", "mobility:can_move"),
    ("Je ne peux pas", "mobility:cannot_move"),
)
BOUTONS_TYPE = (
    ("Pharmacie", "kind:pharmacy"),
    ("Centre de santé", "kind:health_center"),
    ("Pharmacie de garde", "kind:on_call"),
)

LIGNES_SITUATION = (
    ("Femme enceinte", "situation:pregnant"),
    ("Asthme", "situation:asthma"),
    ("Bébé malade", "situation:sick_baby"),
    ("Problème cardiaque", "situation:heart"),
    ("Accident", "situation:accident"),
    ("Autre situation", "situation:other"),
)
TITRE_FLOW = "Envoyer ma pièce"


def clavier(
    awaiting_detail: str | None,
    flow_id: str | None,
    flow_brouillon: bool,
) -> Clavier | None:
    if awaiting_detail == "mobility":
        return [types.Button(title=t, callback_data=d) for t, d in BOUTONS_MOBILITE]
    if awaiting_detail == "situation":
        lignes = [types.SectionRow(title=t, callback_data=d) for t, d in LIGNES_SITUATION]
        return types.SectionList(
            button_title="Choisir",
            sections=[types.Section(title="Situation", rows=lignes)],
        )
    if awaiting_detail == "identity" and flow_id:
        if flow_brouillon:
            return types.FlowButton(title=TITRE_FLOW, flow_id=flow_id, mode=types.FlowStatus.DRAFT)
        return types.FlowButton(title=TITRE_FLOW, flow_id=flow_id, mode=types.FlowStatus.PUBLISHED)
    if awaiting_detail == "kind":
        return [types.Button(title=t, callback_data=d) for t, d in BOUTONS_TYPE]
    if awaiting_detail == "menu":
        demo = get_setting().DEMO_MODE
        lignes = [
            types.SectionRow(title=ligne.titre, callback_data=ligne.callback)
            for ligne in MENU
            if demo or not ligne.demo
        ]
        return types.SectionList(
            button_title="Choisir",
            sections=[types.Section(title="Menu", rows=lignes)],
        )
    return None
