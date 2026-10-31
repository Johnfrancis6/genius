"""Traitement d'un message WhatsApp entrant, de la réception à la réponse."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from pywa_async import WhatsApp, types

from agent.conversation.graph import Graphe, run_graph
from agent.conversation.locks import user_lock
from agent.conversation.replies import render_reply
from agent.conversation.state import ConversationState, build_turn_state
from agent.stores import (
    ConversationStateStore,
    MessageStore,
    PgImageStore,
    get_or_create_user,
)
from agent.whatsapp.claviers import Clavier
from agent.whatsapp.claviers import clavier as choisir_clavier
from agent.whatsapp.envoi_stickers import choisir_sticker
from agent.whatsapp.media import recevoir_image, recevoir_image_par_id

logger = logging.getLogger(__name__)

TIMEOUT_TOUR_S = 60
RELANCE_ENVOI_S = 3
TYPES_GERES = frozenset({"text", "image", "audio", "location"})
MAX_CORPS_CLAVIER = 1024  # limite Meta du corps d'un message à boutons
NIVEAU_SANS_CLAVIER = 3  # URGENT et au-dessus : texte fixe, jamais de bouton
CLE_PHOTO_FLOW = "photo_piece"  # clé de la photo dans le payload `complete` du Flow

Tour = Callable[[str, str], Awaitable[None]]


def _texte_entrant(msg: types.Message) -> str | None:
    """Texte à enregistrer : le texte, la légende d'une image, sinon rien."""
    if msg.text is not None:
        return msg.text
    if msg.image is not None:
        return msg.image.caption
    return None


def _fusionner_localisation(state: ConversationState, loc: types.Location) -> None:
    """lat/lng, plus nom et adresse du lieu s'ils existent, dans `search` sans écraser le reste."""
    search = state["search"]
    search["lat"] = loc.latitude
    search["lng"] = loc.longitude
    if loc.name:
        search["place_name"] = loc.name
    if loc.address:
        search["address"] = loc.address


SANS_STICKER = frozenset({"urgence", "urgence_numeros", "probleme_technique", "aide_humaine"})


def _sticker_permis(final: dict[str, Any]) -> bool:
    """Sticker seulement en fin de demande traitée, jamais en urgence ni en repli."""
    if final.get("step") != "answered":
        return False
    if final.get("urgency") or final.get("urgency_level", 1) != 1:
        return False
    return final.get("reply_key") not in SANS_STICKER


class Traiteur:
    def __init__(
        self,
        wa: WhatsApp,
        graphe: Graphe,
        images: PgImageStore,
        messages: MessageStore,
        etats: ConversationStateStore,
        flow_id: str | None = None,
        flow_brouillon: bool = True,
    ) -> None:
        self.wa = wa
        self.graphe = graphe
        self.images = images
        self.messages = messages
        self.etats = etats
        self.flow_id = flow_id
        self.flow_brouillon = flow_brouillon

    async def traiter(self, _wa: WhatsApp, msg: types.Message) -> None:
        await self._gerer(msg.id, msg.from_user.wa_id, lambda uk, w: self._tour(uk, w, msg))

    async def traiter_clic(
        self, _wa: WhatsApp, clic: types.CallbackButton | types.CallbackSelection
    ) -> None:
        await self._gerer(clic.id, clic.from_user.wa_id, lambda uk, w: self._tour_clic(uk, w, clic))

    async def traiter_flow(self, _wa: WhatsApp, fin: types.FlowCompletion) -> None:
        await self._gerer(fin.id, fin.from_user.wa_id, lambda uk, w: self._tour_flow(uk, w, fin))

    async def _gerer(self, update_id: str, wa_id: str | None, tour: Tour) -> None:
        if not wa_id:
            logger.info("message sans numéro ignoré")
            return
        try:
            await self.wa.indicate_typing(message_id=update_id)  # marque lu + saisie
        except Exception as e:
            logger.warning("saisie non signalée : %s", type(e).__name__)
        try:
            user_key = str(await get_or_create_user(wa_id))
        except Exception as e:
            logger.error("utilisateur non résolu : %s", type(e).__name__)
            return
        async with user_lock(user_key):
            try:
                await tour(user_key, wa_id)
            except Exception as e:
                logger.error("tour interrompu : %s", type(e).__name__)
                await self._repondre_fixe(user_key, wa_id, "probleme_technique")

    async def _tour(self, user_key: str, wa_id: str, msg: types.Message) -> None:
        msg_type = msg.type.value
        nouveau = await self.messages.add(
            user_key, "in", msg_type, _texte_entrant(msg), inbound_id=msg.id
        )
        if not nouveau:
            logger.info("doublon ignoré")
            return
        if msg_type not in TYPES_GERES:
            if msg_type == "sticker" and await self._envoyer_sticker(wa_id, "reponse_sticker"):
                return
            await self._repondre_fixe(user_key, wa_id, "type_non_gere")
            return

        image_id: str | None = None
        if msg_type == "image":
            image_id = await recevoir_image(self.wa, self.images, user_key, msg)
            if image_id is None:
                await self._repondre_fixe(user_key, wa_id, "image_a_renvoyer")
                return
        await self._lancer_graphe(user_key, wa_id, msg.id, msg_type, image_id, msg.location)

    async def _tour_clic(
        self,
        user_key: str,
        wa_id: str,
        clic: types.CallbackButton | types.CallbackSelection,
    ) -> None:
        """Un clic entre dans le graphe comme un message texte égal au titre cliqué."""
        nouveau = await self.messages.add(user_key, "in", "text", clic.title, inbound_id=clic.id)
        if not nouveau:
            logger.info("doublon ignoré")
            return
        await self._lancer_graphe(user_key, wa_id, clic.id, "text", None, None)

    async def _tour_flow(self, user_key: str, wa_id: str, fin: types.FlowCompletion) -> None:
        """La fin du Flow entre dans le graphe comme un message image (pièce d'identité)."""
        nouveau = await self.messages.add(user_key, "in", "image", None, inbound_id=fin.id)
        if not nouveau:
            logger.info("doublon ignoré")
            return
        image_id: str | None = None
        try:
            media: types.Image = fin.get_media(types.Image, CLE_PHOTO_FLOW)
            image_id = await recevoir_image_par_id(self.wa, self.images, user_key, media.id)
        except Exception as e:
            logger.warning("photo du Flow introuvable : %s", type(e).__name__)
        if image_id is None:
            await self._repondre_fixe(user_key, wa_id, "image_a_renvoyer")
            return
        await self._lancer_graphe(user_key, wa_id, fin.id, "image", image_id, None)

    async def _lancer_graphe(
        self,
        user_key: str,
        wa_id: str,
        msg_id: str,
        msg_type: str,
        image_id: str | None,
        localisation: types.Location | None,
    ) -> None:
        persisted = await self.etats.load(user_key)
        state = build_turn_state(user_key, msg_id, msg_type, persisted)
        if image_id is not None:
            state["pending_image_id"] = image_id
        if localisation is not None:
            _fusionner_localisation(state, localisation)

        try:
            reponse, final = await asyncio.wait_for(run_graph(self.graphe, state), TIMEOUT_TOUR_S)
        except Exception as e:
            logger.error("graphe en échec : %s", type(e).__name__)
            await self._repondre_fixe(user_key, wa_id, "probleme_technique")
            return
        await self.etats.save(user_key, final)
        position = _position_demandee(final, reponse)
        clavier = (
            None if position else _clavier_permis(final, reponse, self.flow_id, self.flow_brouillon)
        )
        envoye = await self._envoyer(user_key, wa_id, reponse, clavier, position)
        if envoye and _sticker_permis(final):
            await self._envoyer_sticker(wa_id, "termine")

    async def _repondre_fixe(self, user_key: str, wa_id: str, cle: str) -> None:
        await self._envoyer(user_key, wa_id, render_reply(cle))

    async def _envoyer_sticker(self, wa_id: str, situation: str) -> bool:
        """Envoie un sticker de la situation. Sans relance, sans enregistrement ; False si échec."""
        fichier = choisir_sticker(situation)
        if fichier is None:
            return False
        try:
            await self.wa.send_sticker(to=wa_id, sticker=fichier, mime_type="image/webp")
        except Exception as e:
            logger.warning("sticker non envoyé : %s", type(e).__name__)
            return False
        return True

    async def _envoyer(
        self,
        user_key: str,
        wa_id: str,
        texte: str,
        clavier: Clavier | None = None,
        position: bool = False,
    ) -> bool:
        """Essai 1 : position ou clavier. Essai 2 : texte simple. « out » enregistré si l'envoi réussit."""
        for tentative in (1, 2):
            try:
                if position and tentative == 1:
                    await self.wa.request_location(to=wa_id, text=texte)
                else:
                    await self.wa.send_message(
                        to=wa_id, text=texte, buttons=clavier if tentative == 1 else None
                    )
                break
            except Exception as e:
                logger.warning("envoi échoué (essai %d) : %s", tentative, type(e).__name__)
                if tentative == 1:
                    await asyncio.sleep(RELANCE_ENVOI_S)
        else:
            logger.error("envoi abandonné")
            return False
        try:
            await self.messages.add(user_key, "out", "text", texte)
        except Exception as e:
            logger.error("« out » non enregistré : %s", type(e).__name__)
        return True


def _question_permise(final: dict[str, Any], texte: str) -> bool:
    """Question en cours, hors urgence, repli et corps trop long."""
    if final.get("step") == "answered" or final.get("reply_key") in SANS_STICKER:
        return False
    if final.get("urgency_level", 1) >= NIVEAU_SANS_CLAVIER:
        return False
    return len(texte) <= MAX_CORPS_CLAVIER


def _clavier_permis(
    final: dict[str, Any], texte: str, flow_id: str | None, flow_brouillon: bool
) -> Clavier | None:
    if not _question_permise(final, texte):
        return None
    return choisir_clavier(final.get("awaiting_detail"), flow_id, flow_brouillon)


def _position_demandee(final: dict[str, Any], texte: str) -> bool:
    """Demande de localisation interactive : mêmes gardes que les claviers."""
    return _question_permise(final, texte) and final.get("awaiting_detail") == "location"
