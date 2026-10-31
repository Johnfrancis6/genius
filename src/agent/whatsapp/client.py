"""Client WhatsApp (PyWa) : vérification de la configuration Meta et construction."""

from fastapi import FastAPI
from pywa_async import WhatsApp

from agent.settings import get_setting

WEBHOOK_ENDPOINT = "/webhook"


def creer_client(app: FastAPI) -> WhatsApp:
    """Échoue si une variable Meta manque (sans secret, PyWa coupe la validation de signature)."""
    s = get_setting()
    requises = {
        "META_APP_SECRET": s.META_APP_SECRET,
        "WEBHOOK_VERIFY_TOKEN": s.WEBHOOK_VERIFY_TOKEN,
        "WHATSAPP_ACCESS_TOKEN": s.WHATSAPP_ACCESS_TOKEN,
        "WHATSAPP_PHONE_NUMBER_ID": s.WHATSAPP_PHONE_NUMBER_ID,
    }
    manquantes = [nom for nom, valeur in requises.items() if not valeur]
    if manquantes:
        raise RuntimeError(f"Variables Meta manquantes : {', '.join(manquantes)}")
    return WhatsApp(
        phone_id=s.WHATSAPP_PHONE_NUMBER_ID,
        token=s.WHATSAPP_ACCESS_TOKEN,
        server=app,
        webhook_endpoint=WEBHOOK_ENDPOINT,
        verify_token=s.WEBHOOK_VERIFY_TOKEN,
        app_secret=s.META_APP_SECRET,
        validate_updates=True,
    )
