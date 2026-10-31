"""Mise en forme WhatsApp du texte produit par le modèle (fonction pure, idempotente).

Appelée une fois par run_graph, sur les réponses du modèle seulement : jamais sur les
textes fixes de replies.py. Pas de coupe à 4096 caractères, pas de conversion de tableaux
(le prompt les interdit).
"""

from __future__ import annotations

import re

MAX_EMOJIS = 3

_BASE = "\U0001f000-\U0001faff\u2300-\u23ff\u2600-\u27bf\u2b00-\u2bff"
_PEAU = "\U0001f3fb-\U0001f3ff"
_ELEMENT = rf"[{_BASE}](?:\uFE0F|[{_PEAU}])*"
_EMOJI = re.compile(rf"[\U0001F1E6-\U0001F1FF]{{2}}|{_ELEMENT}(?:\u200D{_ELEMENT})*")
_ALARME = re.compile("\U0001f6a8\ufe0f?")

_GRAS = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_BARRE = re.compile(r"~~(.+?)~~", re.DOTALL)
_TITRE = re.compile(r"^[ \t]*#{1,6}[ \t]+", re.MULTILINE)
_PUCE = re.compile(r"^[ \t]*[-*][ \t]+", re.MULTILINE)
_DEBUT_LIGNE = re.compile(r"^[ \t]+", re.MULTILINE)
_FIN_LIGNE = re.compile(r"[ \t]+$", re.MULTILINE)
_ESPACES = re.compile(r"[ \t]{2,}")
_LIGNES_VIDES = re.compile(r"\n{3,}")


def _limiter_emojis(texte: str, maximum: int) -> str:
    """Garde les `maximum` premiers emojis, retire les suivants."""
    compteur = 0

    def _garder(m: re.Match[str]) -> str:
        nonlocal compteur
        compteur += 1
        return m.group(0) if compteur <= maximum else ""

    return _EMOJI.sub(_garder, texte)


def normaliser_pour_whatsapp(texte: str, *, sobre: bool = False) -> str:
    """Rend `texte` conforme à la syntaxe WhatsApp.

    sobre=True (niveau INCERTAIN ou plus) : aucun emoji. Sinon 3 au plus.
    """
    t = texte.replace("\r\n", "\n").replace("\r", "\n")
    t = _GRAS.sub(r"*\1*", t)
    t = _BARRE.sub(r"~\1~", t)
    t = _TITRE.sub("", t)
    t = _PUCE.sub("• ", t)
    t = _ALARME.sub("", t)
    t = _limiter_emojis(t, 0 if sobre else MAX_EMOJIS)
    t = _ESPACES.sub(" ", t)
    t = _DEBUT_LIGNE.sub("", t)
    t = _FIN_LIGNE.sub("", t)
    t = _LIGNES_VIDES.sub("\n\n", t)
    return t.strip()
