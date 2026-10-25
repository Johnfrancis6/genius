"""Tests du lifespan de agent.app : démarrage, boucle de purge, arrêt.

Le lifespan est lancé via app.router.lifespan_context(app), quel que soit le
nom de la fonction dans app.py. La purge est observée en remplaçant
agent.purge.purge_expired par un enregistreur : purge_loop le cherche à chaque
tour dans le module, donc le remplacement fonctionne sans dépendre de la façon
dont app.py importe purge_loop.
"""
import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from agent import purge

pytestmark = [
    pytest.mark.asyncio(loop_scope="session"),
    pytest.mark.usefixtures("clean_db"),
]


def _get_app():
    # Import tardif : app.py ne doit pas être importé avant l'environnement de test.
    from agent.app import app

    return app


def _clear_caches() -> None:
    from agent.memoire import crypto
    from agent.settings import get_setting  # ADAPTE : comme dans conftest.py

    for fn in (get_setting, crypto.get_fernet):
        clear = getattr(fn, "cache_clear", None)
        if clear is not None:
            clear()


def _purge_tasks() -> list[asyncio.Task]:
    return [
        task
        for task in asyncio.all_tasks()
        if getattr(task.get_coro(), "__qualname__", "") == "purge_loop"
    ]


@pytest.fixture
def purge_calls(monkeypatch) -> list[int]:
    calls: list[int] = []

    async def recording() -> dict[str, int]:
        calls.append(1)
        return {}

    monkeypatch.setattr(purge, "purge_expired", recording)
    return calls


async def test_lifespan_runs_purge_loop_then_stops_it(purge_calls):
    app = _get_app()
    async with app.router.lifespan_context(app):
        for _ in range(200):
            if purge_calls:
                break
            await asyncio.sleep(0.01)
        assert purge_calls, "la boucle de purge n'a pas démarré"
        assert len(_purge_tasks()) == 1

    await asyncio.sleep(0.05)
    assert _purge_tasks() == []  # tâche annulée et terminée
    seen = len(purge_calls)
    await asyncio.sleep(0.05)
    assert len(purge_calls) == seen  # plus aucun appel après l'arrêt


async def test_lifespan_disposes_engine_on_shutdown(purge_calls, monkeypatch):
    disposed: list[AsyncEngine] = []
    original = AsyncEngine.dispose

    async def spy(self, *args, **kwargs):
        disposed.append(self)
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(AsyncEngine, "dispose", spy)
    app = _get_app()
    async with app.router.lifespan_context(app):
        assert disposed == []
    assert len(disposed) == 1


async def test_lifespan_refuses_to_start_with_invalid_fernet_keys(
    purge_calls, monkeypatch
):
    monkeypatch.setenv("FERNET_KEYS", "pas-une-cle-fernet")
    _clear_caches()
    app = _get_app()
    try:
        with pytest.raises(Exception) as except_info:
            print(type(except_info.value))
            async with app.router.lifespan_context(app):
                pytest.fail("le lifespan n'aurait pas dû démarrer")
    finally:
        _clear_caches()  # avant la restauration de l'environnement par monkeypatch

    await asyncio.sleep(0.05)
    assert purge_calls == []  # la purge n'a pas démarré
    assert _purge_tasks() == []