"""Stickers personnalisés : un dossier par situation, tirage au hasard dans le dossier."""

import random
from pathlib import Path

STICKERS_DIR = Path(__file__).parent / "stickers"
MAX_OCTETS = 500 * 1024  # limite WhatsApp d'un sticker animé

_dernier: dict[str, Path] = {}


def choisir_sticker(situation: str) -> Path | None:
    """Un .webp du dossier `situation`, différent du précédent s'il y a le choix."""
    fichiers = [
        p for p in (STICKERS_DIR / situation).glob("*.webp") if 0 < p.stat().st_size <= MAX_OCTETS
    ]
    if not fichiers:
        return None
    if len(fichiers) > 1 and _dernier.get(situation) in fichiers:
        fichiers.remove(_dernier[situation])
    choisi = random.choice(fichiers)  # noqa: S311
    _dernier[situation] = choisi
    return choisi
