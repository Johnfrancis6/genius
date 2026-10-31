"""Réception d'une image WhatsApp : contrôle de taille, téléchargement, stockage chiffré."""

import logging

from pywa_async import WhatsApp, types

from agent.stores import PgImageStore

logger = logging.getLogger(__name__)

MAX_IMAGE_OCTETS = 14 * 1024 * 1024  # base64 +1/3 reste sous la limite Groq de 20 Mo


async def recevoir_image_par_id(
    wa: WhatsApp, images: PgImageStore, user_key: str, media_id: str
) -> str | None:
    """Id de l'image stockée, ou None (échec, taille excessive, type refusé)."""
    try:
        info = await wa.get_media_url(media_id)
        if info.file_size > MAX_IMAGE_OCTETS:
            logger.info("image refusée : taille excessive")
            return None
        data = await wa.get_media_bytes(info.url)
        if len(data) > MAX_IMAGE_OCTETS:
            logger.info("image refusée : taille excessive")
            return None
        return await images.put(user_key, data, info.mime_type)
    except Exception as e:
        logger.warning("image non reçue : %s", type(e).__name__)
        return None


async def recevoir_image(
    wa: WhatsApp, images: PgImageStore, user_key: str, msg: types.Message
) -> str | None:
    """Id de l'image stockée pour un message image, ou None."""
    if msg.image is None:
        return None
    return await recevoir_image_par_id(wa, images, user_key, msg.image.id)
