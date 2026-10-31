"""Fixtures PostgreSQL réelles (testcontainers) pour tests/memoire.

Rien n'est autouse : seuls les modules qui déclarent usefixtures("clean_db")
démarrent le conteneur (test_crypto.py et les tests sans base restent rapides).
Une seule boucle asyncio pour toute la session (loop_scope="session") : le
moteur n'est jamais partagé entre plusieurs boucles.

Les tables sont créées avec Base.metadata.create_all (pas Alembic) : le test ne
dépend ni d'alembic.ini ni de env.py et ne peut pas migrer la base de dev par
erreur. La conformité migration/modèles reste le travail de `alembic check`.
"""

import os
import secrets

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.engine import make_url
from testcontainers.community.postgres import PostgresContainer

from agent.db import dispose_engine, get_engine, session_scope
from agent.models import Base


def _clear_caches() -> None:
    """Vide les lru_cache : réglages, moteur et clés relisent l'environnement."""
    from agent import db
    from agent.memoire import crypto
    from agent.settings import get_setting  # ADAPTE : module qui définit get_setting()

    for fn in (get_setting, db.get_engine, db.get_sessionmaker, crypto.get_fernet):
        clear = getattr(fn, "cache_clear", None)
        if clear is not None:
            clear()


@pytest.fixture(scope="session")
def postgres_url():
    with PostgresContainer("postgres:16", driver="psycopg") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def test_env(postgres_url):
    """Environnement de test : base du conteneur et clés jetables."""
    forced = {
        "ENV": "dev",
        "DATABASE_URL": postgres_url,
        "FERNET_KEYS": Fernet.generate_key().decode(),
        "PSEUDONYM_HMAC_KEY": secrets.token_hex(32),
    }
    fillers = {
        "GROQ_API_KEY": "test",
        "GROQ_MODEL_TEXT": "test",
        "GROQ_MODEL_VISION": "test",
        "STT_MODEL_NAME": "test",
        "POSTGRES_PASSWORD": "test",
        "POSTGRES_DB": "test",
    }
    saved = {key: os.environ.get(key) for key in (*forced, *fillers)}
    os.environ.update(forced)
    for key, value in fillers.items():
        os.environ.setdefault(key, value)
    _clear_caches()
    yield
    for key, old in saved.items():
        if old is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old
    _clear_caches()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def pg_engine(test_env, postgres_url):
    engine = get_engine()
    expected = make_url(postgres_url)
    # Garde-fou : ne jamais exécuter ces tests contre la base de dev.
    assert (engine.url.host, engine.url.port) == (expected.host, expected.port), (
        "le moteur ne pointe pas sur le conteneur de test"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await dispose_engine()


@pytest_asyncio.fixture(loop_scope="session")
async def clean_db(pg_engine):
    """Base vide avant chaque test (TRUNCATE ... CASCADE depuis users)."""
    async with session_scope() as session:
        await session.execute(text("TRUNCATE users CASCADE"))
    yield
