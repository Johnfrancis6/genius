"""Évaluation d'urgence d'un tour. PROVISOIRE : renvoie toujours NORMAL.

Le moteur complet (règles YAML, escalade médecin) est une session à part.
"""

from collections.abc import Mapping
from typing import Any

from agent.safety.levels import Level
from agent.safety.state_machine import Decision, SafetyState


def evaluer_urgence(state: Mapping[str, Any]) -> Decision:
    return Decision(SafetyState(Level.NORMAL))
