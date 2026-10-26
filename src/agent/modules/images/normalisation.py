"""Normalisation et comparaison de noms de médicaments."""

import logging
import re
import unicodedata

from agent.modules.images.image_data import (
    ILLISIBLE,
    Accepte,
    Drug,
    IdCardFields,
    Ordonnance_output,
    ReasonRejet,
    Reject,
    Resultat,
    parse_modele,
)

logger = logging.getLogger(__name__)

# Frontière lettre/chiffre, dans les deux sens ("500mg" -> "500 mg")
_LETTRE_CHIFFRE = re.compile(r"(?<=[^\W\d_])(?=\d)|(?<=\d)(?=[^\W\d_])")


def normaliser(texte: str) -> str:
    r"""Forme comparable d'un texte d'ordonnance (casse, accents, ponctuation, espaces)."""
    texte = unicodedata.normalize("NFKD", texte.casefold())
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    texte = re.sub(r"[\W_]+", " ", texte)
    texte = _LETTRE_CHIFFRE.sub(" ", texte)
    return re.sub(r"\s+", " ", texte).strip()


def mots(texte: str) -> frozenset[str]:
    return frozenset(normaliser(texte).split())


def _present(medicament: Drug, lignes: list[Drug]) -> bool:
    """Tous les mots du médicament figurent dans une même ligne (ordre libre).
    Ensemble vide -> False : il serait inclus dans tout."""
    words = mots(medicament.text)
    return bool(words) and any(words <= mots(ligne.text) for ligne in lignes)


def valider_ordonnance(brut: str) -> Resultat[Ordonnance_output]:
    out = parse_modele(brut, Ordonnance_output)
    if isinstance(out, Reject):
        return out

    if out.signe_medical_visible:
        return Reject(ReasonRejet.SIGNE_MEDICAL, retryable=False)

    for m in out.medicaments_ecrits:
        if ILLISIBLE in m.text:
            continue
        if not _present(m, out.lignes):
            logger.warning(
                "Extraction rejetée : %s (réessayable=%s)",
                ReasonRejet.MEDICAMENT_ABSENT,
                True,
            )
            return Reject(ReasonRejet.MEDICAMENT_ABSENT, retryable=True)
    return Accepte(out)


def valider_piece_identite(brut: str) -> Resultat[IdCardFields]:
    out = parse_modele(brut, IdCardFields)
    return out if isinstance(out, Reject) else Accepte(out)
