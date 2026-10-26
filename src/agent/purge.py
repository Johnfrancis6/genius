"""Purge des données expirées."""

import asyncio
import logging
from typing import Any, cast

from sqlalchemy import delete as sa_delete
from sqlalchemy import func
from sqlalchemy.engine import CursorResult

from agent.db import session_scope
from agent.models import ExtractionResult, Image, Message, VoiceNote

logger = logging.getLogger(__name__)

PURGE_INTERVAL_SECONDS = 60
_EXPIRING_MODELS = (Message, Image, ExtractionResult, VoiceNote)


async def purge_expired() -> dict[str, int]:
    """Un DELETE par table, chacun dans sa transaction. Renvoie {table: lignes}."""
    counts: dict[str, int] = {}
    for model in _EXPIRING_MODELS:
        async with session_scope() as session:
            result = cast(
                "CursorResult[Any]",
                await session.execute(
                    sa_delete(model)
                    .where(model.expires_at <= func.now())
                    .execution_options(synchronize_session=False)
                ),
            )
            counts[model.__tablename__] = result.rowcount
    return counts


async def purge_loop(interval: float = PURGE_INTERVAL_SECONDS) -> None:
    while True:
        try:
            counts = await purge_expired()
            if any(counts.values()):
                logger.info("purge: %s", counts)
        except Exception:  # CancelledError n'en hérite pas : elle se propage
            logger.exception("purge_expired a échoué")
        await asyncio.sleep(interval)
