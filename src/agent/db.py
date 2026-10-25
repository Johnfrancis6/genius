import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from agent.settings import get_setting

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    return create_async_engine(
        get_setting().DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Ouvre une session : commit si tout va bien, rollback sinon."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def check_connection() -> None:
    """Vérifie la connexion à la base (appelée au démarrage dans le lifespan)."""
    logger.info("Vérification de la connexion à la base de données")
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error("Connexion à la base impossible : %s", type(exc).__name__)
        raise
    logger.info("Connexion OK")


async def dispose_engine() -> None:
    """Ferme le moteur (s'il a été créé) et vide les caches."""
    try:
        if get_engine.cache_info().currsize:
            await get_engine().dispose()
            logger.info("Engine fermé")
    finally:
        get_sessionmaker.cache_clear()
        get_engine.cache_clear()
        
        
        
