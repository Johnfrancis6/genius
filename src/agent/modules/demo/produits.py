"""Noms de produits : normalisation partagée entre la démo et le parcours stock."""

from __future__ import annotations

import re
import unicodedata

# Noms seulement : jamais de dose, de prix ni de quantité.
PRODUITS_DEMO: tuple[str, ...] = (
    "paracétamol",
    "amoxicilline",
    "artéméther-luméfantrine",
    "sels de réhydratation orale",
    "ibuprofène",
    "salbutamol",
    "oméprazole",
    "métronidazole",
    "zinc",
    "vitamine C",
)


def normaliser_produit(texte: str) -> str:
    """Minuscules, sans accents, tout séparateur ramené à un espace."""
    decompose = unicodedata.normalize("NFD", texte)
    sans_accents = "".join(c for c in decompose if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", sans_accents.casefold()).strip()
