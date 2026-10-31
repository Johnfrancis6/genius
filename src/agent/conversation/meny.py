"""Menu d'accueil : source unique des lignes (titre, callback, intention, type)."""

from __future__ import annotations

from dataclasses import dataclass

from agent.conversation.state import Intent

CALLBACK_AUTRE = "menu:other"


@dataclass(frozen=True)
class LigneMenu:
    titre: str  # 24 caractères au plus (limite WhatsApp)
    callback: str
    intent: Intent
    kind: str | None = None


MENU: tuple[LigneMenu, ...] = (
    LigneMenu("Centre de santé", "menu:health_center", "search", "health_center"),
    LigneMenu("Pharmacie", "menu:pharmacy", "search", "pharmacy"),
    LigneMenu("Pharmacie de garde", "menu:on_call", "search", "on_call"),
    LigneMenu("Me faire transporter", "menu:transport", "transport"),
    LigneMenu("Autre demande", CALLBACK_AUTRE, "unknown"),
)

MENU_PAR_TITRE: dict[str, LigneMenu] = {ligne.titre.casefold(): ligne for ligne in MENU}