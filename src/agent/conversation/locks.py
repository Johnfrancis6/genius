# src/agent/conversation/locks.py
import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


@asynccontextmanager
async def user_lock(user_key: str) -> AsyncIterator[None]:
    async with _locks[user_key]:
        yield
