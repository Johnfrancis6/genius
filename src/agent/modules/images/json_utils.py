import re

# Regex pour retirer les balises ``` autour d'un JSON
_BALISES = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def extraire_json(brut: str) -> str:
    """Retire les balises ``` autour d'un JSON."""
    return _BALISES.sub("", brut.strip())
