"""Point d'entrée du module de traitement d'image."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import StrEnum
from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from agent.modules.images.image_classification import classifier
from agent.modules.images.image_data import (
    Call_VLM,
    ReasonRejet,
    Reject,
    Resultat,
    TypeImage,
)
from agent.stores import ExtractionStore, PgImageStore

Extracteur = Callable[[bytes, Call_VLM], Awaitable[Resultat]]
TIMEOUT_S = 60
logger = logging.getLogger(__name__)

TYPES_ATTENDUS = frozenset({"ordonnance", "piece_identite"})
class Status(StrEnum):
    NO_IMAGE = "pas_d_image"
    EXTRACTED = "extrait"
    IMAGE_TO_RESEND = "image_a_renvoyer"
    MEDICAL_SIGN = "signe_medical"
    EXPECTED_TYPE = "type_attendu"
    TYPE_TO_CONFIRM = "type_a_preciser"
    OTHER = "autre"
    TECHNICAL_ERROR = "erreur_technique"


@dataclass(frozen=True)
class AnalyseResult:
    status: Status
    type_detected: TypeImage | None = None
    type_expected: TypeImage | None = None
    description: str = field(default="", repr=False)
    data: object | None = field(default=None, repr=False)
    reason: ReasonRejet | None = None


async def image_analysis(
    image: bytes,
    expected_type: TypeImage | None,
    appel: Call_VLM,
    extracteurs: dict[TypeImage, Extracteur],
) -> AnalyseResult:
    try:
        async with asyncio.timeout(TIMEOUT_S):
            return await _analyse(image, expected_type, appel, extracteurs)
    except TimeoutError:
        logger.warning("Analyse image : timeout après %ds", TIMEOUT_S)
        return AnalyseResult(
            Status.TECHNICAL_ERROR, reason=ReasonRejet.ERREUR_FOURNISSEUR
        )


async def _analyse(
    image: bytes,
    expected_type: TypeImage | None,
    appel: Call_VLM,
    extracteurs: dict[TypeImage, Extracteur],
) -> AnalyseResult:
    c = await classifier(image, appel)
    if isinstance(c, Reject):
        return AnalyseResult(Status.TECHNICAL_ERROR, reason=c.reason)
    cl = c.output

    if cl.signe_medical_visible:
        return AnalyseResult(Status.MEDICAL_SIGN)

    if cl.type == "illisible" or cl.lisibilite == "mauvaise":
        return AnalyseResult(Status.IMAGE_TO_RESEND, type_detected=cl.type)

    if expected_type and cl.type != expected_type:
        return AnalyseResult(
            Status.EXPECTED_TYPE, type_expected=expected_type, type_detected=cl.type
        )
    if cl.type == "autre":
        return AnalyseResult(
            Status.OTHER, type_detected="autre", description=cl.description
        )
    if cl.type == "piece_identite" and expected_type is None:
        return AnalyseResult(
            Status.TYPE_TO_CONFIRM, type_detected=cl.type, description=cl.description
        )
    extracteur = extracteurs.get(cl.type)
    if extracteur is None:
        return AnalyseResult(Status.TECHNICAL_ERROR, type_detected=cl.type)

    result = await extracteur(image, appel)

    if isinstance(result, Reject):
        return AnalyseResult(
            Status.TECHNICAL_ERROR,
            type_detected=cl.type,
            type_expected=expected_type,
            reason=result.reason,
        )
    return AnalyseResult(Status.EXTRACTED, type_detected=cl.type, data=result.output)


# ==========================
#  Implémentation de l'outil
# ==========================

MESSAGES: dict[Status, str] = {
        Status.NO_IMAGE: "Aucune image en attente. Demande au patient de l'envoyer.",
    Status.EXTRACTED: "Image lue et enregistrée. Ne répète pas son contenu.",
    Status.IMAGE_TO_RESEND: "Image inutilisable. Demande au patient de renvoyer une photo nette, bien éclairée et entière.",
    Status.MEDICAL_SIGN: "Image non analysée. Ne la décris pas ; oriente le patient vers un professionnel de santé.",
    Status.OTHER: "Image sans rapport avec le service. Demande ce dont le patient a besoin.",
    Status.EXPECTED_TYPE: "Type de document à confirmer avec le patient avant toute lecture.",
    Status.TYPE_TO_CONFIRM: "Type de document incertain. Demande au patient s'il s'agit d'une ordonnance ou d'une pièce d'identité avant toute lecture.",
    Status.TECHNICAL_ERROR: "Problème technique. Ne dis pas que la photo est mauvaise ; propose de réessayer.",
}


def _to_payload(data: object) -> dict:
    """Résultat d'extraction -> dict sérialisable en JSON pour ExtractionStore."""
    if hasattr(data, "model_dump"):  # Pydantic
        return data.model_dump(mode="json")
    if is_dataclass(data) and not isinstance(data, type):
        return asdict(data)
    raise TypeError(f"extraction non sérialisable : {type(data).__name__}")


def creer_outil_image(
    images: PgImageStore,
    resultats: ExtractionStore,
    appel: Call_VLM,
    extracteurs: dict[TypeImage, Extracteur],
):
    @tool("analyser_image_recue")
    async def analyser_image_recue(
        state: Annotated[dict, InjectedState],
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command:
        """Analyse l'image que le patient vient d'envoyer. Aucun argument."""
        user_id = state.get("user_id")
        image_id = state.get("pending_image_id")
        expected = state.get("expected_image_type")
        if expected not in TYPES_ATTENDUS:
            expected = None
        reference = None
        if not (user_id  and image_id):
            result = AnalyseResult(Status.NO_IMAGE)
        else:
            result = AnalyseResult(
                Status.TECHNICAL_ERROR, reason=ReasonRejet.IMAGE_INVALIDE
            )
        try:
            if user_id and image_id:
                image = await images.get(user_id, image_id)
                if image is not None:
                    result = await image_analysis(
                        image, expected, appel, extracteurs
                    )
                    if result.status == Status.EXTRACTED:
                        reference = await resultats.put(
                            user_id,
                            str(result.type_detected),
                            _to_payload(result.data),
                        )
        except Exception as e:
            logger.warning("Analyse image échouée : %s", type(e).__name__)
            result = AnalyseResult(
                Status.TECHNICAL_ERROR, reason=ReasonRejet.ERREUR_FOURNISSEUR
            )
        finally:
            if user_id and image_id:
                try:
                    await images.delete(user_id, image_id)
                except Exception as e:
                    # Sans gravité : purge_expired supprime l'image à 15 min.
                    logger.warning(
                        "Suppression de l'image échouée : %s", type(e).__name__
                    )

        return Command(
            update={
                "image_status": result.status.value,
                "image_type_detected": result.type_detected,
                "image_result_id": reference,
                "pending_image_id": None,
                "messages": [
                    ToolMessage(content=_texte(result), tool_call_id=tool_call_id)
                ],
            }
        )

    return analyser_image_recue


def _texte(result: AnalyseResult) -> str:
    if result.status == Status.EXPECTED_TYPE:
        return (
            f"Le patient devait envoyer : {result.type_expected}. "
            f"L'image reçue semble être : {result.type_detected}. "
            "Clarifie avec lui sans rien lire."
        )
    return MESSAGES[result.status]