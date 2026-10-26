from agent.core.prompt import ORDONNANCE_PROMPT, PIECE_IDENTITE_PROMPT
from agent.modules.images.image_data import (
    Accepte,
    Call_VLM,
    IdCardFields,
    Ordonnance_output,
    Reject,
    Resultat,
    extraction,
    parse_modele,
)
from agent.modules.images.normalisation import valider_ordonnance


def valider_piece_identite(brut: str) -> Resultat[IdCardFields]:
    out = parse_modele(brut, IdCardFields)
    return out if isinstance(out, Reject) else Accepte(out)


async def extraire_ordonnance(image: bytes, appel: Call_VLM) -> Resultat[Ordonnance_output]:
    return await extraction(image, ORDONNANCE_PROMPT, appel, valider_ordonnance)


async def extraire_piece_identite(image: bytes, appel: Call_VLM) -> Resultat[IdCardFields]:
    return await extraction(image, PIECE_IDENTITE_PROMPT, appel, valider_piece_identite)
