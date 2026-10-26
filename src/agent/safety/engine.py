# Execussion des regles sur chaque message avant tout llm calling ; Renvoi le niveau le plus grave et enregistre un safety_event
# Fonction pure
# - evalue  les regles

# classification
#
# decision

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

from agent.safety.errors import RuleError
from agent.safety.events import MessageClasse
from agent.safety.levels import Level

MAX_TEXT_CHARS = 4096  # limite d'un message texte WhatsApp ; jamais en dessous
AUCUNE_REGLE = "aucune_regle"
ERREUR_MOTEUR = "erreur_moteur"


@dataclass(frozen=True)
class AccuseMedecin:
    """Lorsque le médecin confirme la réception"""

    escalation_id: str


@dataclass(frozen=True)
class InboundMessage:
    type: str
    at: datetime
    text: str | None = None

    def __post_init__(self) -> None:
        if self.at.tzinfo is None:
            raise ValueError("InboundMessage.at doit avoir un fuseau horaire (UTC)")


@dataclass(frozen=True)
class RuleMatch:
    rule_id: str
    level: Level
    trigger: str  # keywords | regex | repetition | media | interne


@dataclass(frozen=True)
class Classification:
    level: Level
    matches: tuple[RuleMatch, ...] = ()
    degraded: bool = False

    @property
    def decisive(self) -> RuleMatch | None:
        return self.matches[0] if self.matches else None

    @property
    def rule_id(self) -> str:
        return self.matches[0].rule_id if self.matches else AUCUNE_REGLE

    def to_event(self) -> MessageClasse:
        return MessageClasse(niveau=self.level, rule_id=self.rule_id)


# compilation


@dataclass(frozen=True)
class _Ctx:
    text: str
    message: InboundMessage
    history: tuple[InboundMessage, ...]


Matcher = Callable[[_Ctx], bool]


def _phrase_pattern(phrase: str, normalizer: Callable[[str], str]) -> str:
    """Expressions vers motif. Mots entiers ; un mot terminer par * accepte une suite de lettre"""
    pieces: list[str] = []
    for token in phrase.split():
        etoile = token.endswith("*")
        sous_mots = normalizer(token.rstrip("*")).split()

        if not sous_mots:
            continue
        parts = [re.escape(m) for m in sous_mots]

        if etoile:
            parts[-1] += r"\w*"
        pieces.extend(parts)
    if not pieces:
        raise RuleError(f"expression vide après normalisation : {phrase!r}")
    return r"(?<!\w)" + r"\s+".join(pieces) + r"(?!\w)"


def _keyword_matcher(
    any_of: Iterable[str],
    all_of: Iterable[str],
    normalizer: Callable[[str], str],
) -> Callable[[str], bool]:
    any_list = [_phrase_pattern(p, normalizer) for p in any_of]
    any_re = re.compile("|".join(any_list)) if any_list else None
    all_res = [re.compile(_phrase_pattern(p, normalizer)) for p in all_of]

    def match(text: str) -> bool:
        return (any_re is None or any_re.search(text) is not None) and all(
            r.search(text) is not None for r in all_res
        )

    return match
