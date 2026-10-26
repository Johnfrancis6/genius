"""Client Groq : appels texte et vision.

Aucun contenu de message ni texte d'erreur dans les logs : seulement le modèle,
la durée et le nom de la classe d'exception.
"""

from __future__ import annotations

import base64
import logging
import time
from collections.abc import Mapping, Sequence
from typing import Any

from groq import AsyncGroq

from agent.settings import get_setting

logger = logging.getLogger(__name__)

TIMEOUT_TEXTE_S = 30.0
TIMEOUT_VISION_S = 20.0
MAX_RETRIES = 1
MAX_TOKENS_TEXTE = 1024
MAX_TOKENS_VISION = 4096


class LLMError(Exception):
    """Échec d'un appel LLM. Le message est fixe : jamais de contenu ni de texte d'erreur."""


_client: AsyncGroq | None = None


def _get_client() -> AsyncGroq:
    """Crée le client à la première utilisation (les réglages sont obligatoires)."""
    global _client
    if _client is None:
        _client = AsyncGroq(
            api_key=get_setting().GROQ_API_KEY,
            timeout=TIMEOUT_TEXTE_S,
            max_retries=MAX_RETRIES,
        )
    return _client


def reset_client() -> None:
    """Pour les tests."""
    global _client
    _client = None


def _reglage(nom: str) -> str:
    try:
        return str(getattr(get_setting(), nom))
    except Exception as e:
        logger.warning("LLM réglages invalides exc=%s", type(e).__name__)
        raise LLMError("réglages LLM invalides") from None


def _ms(debut: float) -> int:
    return int((time.monotonic() - debut) * 1000)


async def _appeler(
    *,
    model: str,
    messages: Sequence[Mapping[str, Any]],
    delai_s: float,
    max_tokens: int,
    json_mode: bool = False,
    temperature: float | None = None,
    extra_body: dict[str, Any] | None = None,
) -> str:
    debut = time.monotonic()
    try:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": list(messages),
            "max_completion_tokens": max_tokens,
            "timeout": delai_s,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if extra_body:
            kwargs["extra_body"] = extra_body
        reponse = await _get_client().chat.completions.create(stream=False, **kwargs)
        contenu = reponse.choices[0].message.content
    except Exception as e:
        logger.warning("LLM échec model=%s ms=%d exc=%s", model, _ms(debut), type(e).__name__)
        raise LLMError("appel LLM échoué") from None

    if not contenu or not contenu.strip():
        logger.warning("LLM réponse vide model=%s ms=%d", model, _ms(debut))
        raise LLMError("réponse LLM vide")
    logger.info("LLM ok model=%s ms=%d", model, _ms(debut))
    return contenu


def _contient_json(messages: Sequence[Mapping[str, Any]]) -> bool:
    for m in messages:
        contenu = m.get("content")
        if isinstance(contenu, str) and "json" in contenu.lower():
            return True
    return False


async def complete_text(
    messages: Sequence[Mapping[str, Any]],
    model: str | None = None,
    json_mode: bool = False,
    temperature: float | None = None,
    max_tokens: int = MAX_TOKENS_TEXTE,
) -> str:
    """Complétion texte. `model` vaut GROQ_MODEL_TEXT par défaut.

    json_mode exige le mot « json » dans au moins un message (règle de la doc Groq :
    instructions JSON explicites). Toute erreur devient LLMError.
    """
    if json_mode and not _contient_json(messages):
        raise LLMError("json_mode sans instruction JSON")
    return await _appeler(
        model=model or _reglage("GROQ_MODEL_TEXT"),
        messages=messages,
        delai_s=TIMEOUT_TEXTE_S,
        max_tokens=max_tokens,
        json_mode=json_mode,
        temperature=temperature,
    )


# ===========================
#  Vision
# ===========================


def detecter_mime(data: bytes) -> str:
    """Type MIME d'après la signature (JPEG, PNG, WebP). Format inconnu : LLMError."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise LLMError("format d'image non pris en charge")


async def appel_vlm(image: bytes, prompt: str) -> str:
    """Compatible avec `Call_VLM`. Une image par appel, en URL `data:` base64."""
    mime = detecter_mime(image)
    url = f"data:{mime};base64,{base64.b64encode(image).decode('ascii')}"
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": url}},
            ],
        }
    ]
    return await _appeler(
        model=_reglage("GROQ_MODEL_VISION"),
        messages=messages,
        delai_s=TIMEOUT_VISION_S,
        max_tokens=MAX_TOKENS_VISION,
        extra_body={"reasoning_effort": "none"},
    )
