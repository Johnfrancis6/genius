"""Stores Postgres."""

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from agent.conversation.state import PERSISTED_KEYS
from agent.db import session_scope
from agent.memoire.crypto import (
    decrypt,
    decrypt_text,
    encrypt,
    encrypt_text,
    normalize_phone,
    phone_hmac,
)
from agent.models import ConversationStateRow, ExtractionResult, Image, Message, User

MESSAGE_TTL = timedelta(days=7)
IMAGE_TTL = timedelta(minutes=15)
EXTRACTION_TTL = timedelta(hours=24)
VOICE_TTL = timedelta(minutes=15)

ALLOWED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}


def to_uuid(user_key: str) -> uuid.UUID:
    """str(users.id) -> UUID. ValueError si invalide."""
    return uuid.UUID(user_key)


async def get_or_create_user(phone: str) -> uuid.UUID:
    normalized = normalize_phone(phone)
    phone_key = phone_hmac(normalized)
    async with session_scope() as session:
        user_id = (
            await session.execute(
                pg_insert(User)
                .values(phone_hmac=phone_key, phone_enc=encrypt_text(normalized))
                .on_conflict_do_nothing(index_elements=["phone_hmac"])
                .returning(User.id)
            )
        ).scalar_one_or_none()
        if user_id is None:
            user_id = (
                await session.execute(select(User.id).where(User.phone_hmac == phone_key))
            ).scalar_one()
        await session.execute(
            update(User).where(User.id == user_id).values(last_seen_at=func.now())
        )
        return user_id


class PgImageStore:
    async def put(self, user_key: str, data: bytes, mime_type: str) -> str:
        user_id = to_uuid(user_key)
        if mime_type not in ALLOWED_IMAGE_MIME_TYPES:
            raise ValueError(f"mime_type non autorisé : {mime_type}")
        data_enc = encrypt(data)
        async with session_scope() as session:
            image = Image(
                user_id=user_id,
                data_enc=data_enc,
                mime_type=mime_type,
                expires_at=func.now() + IMAGE_TTL,
            )
            session.add(image)
            await session.flush()
            return str(image.id)

    async def get(self, user_key: str, image_id: str) -> bytes | None:
        user_id = to_uuid(user_key)
        image_uuid = to_uuid(image_id)
        async with session_scope() as session:
            data_enc = (
                await session.execute(
                    select(Image.data_enc).where(
                        Image.user_id == user_id,
                        Image.id == image_uuid,
                        Image.expires_at > func.now(),
                    )
                )
            ).scalar_one_or_none()
        return decrypt(data_enc) if data_enc is not None else None

    async def delete(self, user_key: str, image_id: str) -> None:
        user_id = to_uuid(user_key)
        image_uuid = to_uuid(image_id)
        async with session_scope() as session:
            await session.execute(
                sa_delete(Image).where(
                    Image.user_id == user_id,
                    Image.id == image_uuid,
                    # Image.expires_at > func.now(),
                )
            )


class ExtractionStore:
    async def put(self, user_key: str, image_type: str, payload: dict) -> str:
        user_id = to_uuid(user_key)
        payload_enc = encrypt_text(json.dumps(payload, ensure_ascii=False))
        async with session_scope() as session:
            result = ExtractionResult(
                user_id=user_id,
                image_type=image_type,
                payload_enc=payload_enc,
                expires_at=func.now() + EXTRACTION_TTL,
            )
            session.add(result)
            await session.flush()
            return str(result.id)

    async def get(self, user_key: str, result_id: str) -> dict | None:
        user_id = to_uuid(user_key)
        result_uuid = to_uuid(result_id)
        async with session_scope() as session:
            payload_enc = (
                await session.execute(
                    select(ExtractionResult.payload_enc).where(
                        ExtractionResult.user_id == user_id,
                        ExtractionResult.id == result_uuid,
                        ExtractionResult.expires_at > func.now(),
                    )
                )
            ).scalar_one_or_none()
        if payload_enc is None:
            return None
        return json.loads(decrypt_text(payload_enc))


@dataclass(frozen=True)
class MessageRecord:
    direction: str
    msg_type: str
    text: str | None
    created_at: datetime


class MessageStore:
    async def add(
        self,
        user_key: str,
        direction: str,
        msg_type: str,
        text: str | None,
        inbound_id: str | None = None,
    ) -> bool:
        """Message store interface"""
        user_id = to_uuid(user_key)
        content_enc = encrypt_text(text) if text is not None else None
        async with session_scope() as session:
            inserted_id = (
                await session.execute(
                    pg_insert(Message)
                    .values(
                        user_id=user_id,
                        direction=direction,
                        msg_type=msg_type,
                        content_enc=content_enc,
                        inbound_id=inbound_id,
                        expires_at=func.now() + MESSAGE_TTL,
                    )
                    .on_conflict_do_nothing(index_elements=["inbound_id"])
                    .returning(Message.id)
                )
            ).scalar_one_or_none()
        return inserted_id is not None

    async def recent(self, user_key: str, limit: int = 20) -> list[MessageRecord]:
        user_id = to_uuid(user_key)
        async with session_scope() as session:
            rows = (
                await session.execute(
                    select(
                        Message.direction,
                        Message.msg_type,
                        Message.content_enc,
                        Message.created_at,
                    )
                    .where(Message.user_id == user_id, Message.expires_at > func.now())
                    .order_by(Message.created_at.desc())
                    .limit(limit)
                )
            ).all()
        return [
            MessageRecord(
                direction=r.direction,
                msg_type=r.msg_type,
                text=decrypt_text(r.content_enc) if r.content_enc is not None else None,
                created_at=r.created_at,
            )
            for r in reversed(rows)
        ]


async def forget_user(user_key: str) -> bool:
    """Supprime l'utilisateur ; la cascade (FK) supprime le reste."""
    user_id = to_uuid(user_key)
    async with session_scope() as session:
        deleted_id = (
            await session.execute(sa_delete(User).where(User.id == user_id).returning(User.id))
        ).scalar_one_or_none()
    return deleted_id is not None


class ConversationStateStore:
    """État du clarificateur entre deux tours : une ligne par utilisateur, chiffrée."""

    async def load(self, user_key: str) -> dict[str, Any]:
        """État sauvegardé, ou {} s'il n'y en a pas."""
        user_id = to_uuid(user_key)
        async with session_scope() as session:
            state_enc = (
                await session.execute(
                    select(ConversationStateRow.state_enc).where(
                        ConversationStateRow.user_id == user_id
                    )
                )
            ).scalar_one_or_none()
        if state_enc is None:
            return {}
        data = json.loads(decrypt_text(state_enc))
        return {k: v for k, v in data.items() if k in PERSISTED_KEYS or k == "intent"}

    async def save(self, user_key: str, state: Mapping[str, Any]) -> None:
        """Remplace l'état sauvegardé par la liste blanche extraite de `state`."""
        user_id = to_uuid(user_key)
        data = {k: v for k, v in state.items() if k in PERSISTED_KEYS}
        if state.get("awaiting"):
            data["intent"] = state.get("intent", "unknown")
        state_enc = encrypt_text(json.dumps(data, ensure_ascii=False))
        async with session_scope() as session:
            await session.execute(
                pg_insert(ConversationStateRow)
                .values(user_id=user_id, state_enc=state_enc)
                .on_conflict_do_update(
                    index_elements=["user_id"],
                    set_={"state_enc": state_enc, "updated_at": func.now()},
                )
            )

    async def clear(self, user_key: str) -> None:
        """Supprime la ligne de l'utilisateur (sans toucher à `users`)."""
        user_id = to_uuid(user_key)
        async with session_scope() as session:
            await session.execute(
                sa_delete(ConversationStateRow).where(ConversationStateRow.user_id == user_id)
            )
