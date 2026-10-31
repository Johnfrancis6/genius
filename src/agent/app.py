import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from agent.db import check_connection, dispose_engine
from agent.memoire.crypto import get_fernet
from agent.purge import purge_loop
from agent.whatsapp.setup import demarrer_whatsapp


@asynccontextmanager
async def lifespan(app: FastAPI):
    await check_connection()
    get_fernet()  # plante au démarrage si FERNET_KEYS est invalide
    demarrer_whatsapp(app)  # plante si une variable Meta manque
    purge_task = asyncio.create_task(purge_loop(), name="purge_loop")

    try:
        yield
    finally:
        purge_task.cancel()
        with suppress(asyncio.CancelledError):
            await purge_task
        await dispose_engine()


app = FastAPI(lifespan=lifespan)
