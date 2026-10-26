"""Tests des stores et de la purge sur un vrai PostgreSQL (testcontainers)."""
import asyncio
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from agent import purge
from agent.db import session_scope
from agent.memoire.crypto import decrypt_text, encrypt, normalize_phone
from agent.models import ExtractionResult, Image, Message, User, VoiceNote
from agent.purge import purge_expired
from agent.stores import (
    EXTRACTION_TTL,
    IMAGE_TTL,
    MESSAGE_TTL,
    VOICE_TTL,
    ExtractionStore,
    MessageStore,
    PgImageStore,
    forget_user,
    get_or_create_user,
)

pytestmark = [
    pytest.mark.asyncio(loop_scope="session"),
    pytest.mark.usefixtures("clean_db"),
]

PNG = b"\x89PNG\r\n-image-secrete-" * 8
PAYLOAD = {"medicaments": [{"nom": "Paracétamol"}], "lignes": 3}
CHILD_MODELS = (Message, Image, ExtractionResult, VoiceNote)


# --- Aides -------------------------------------------------------------------


def phone(n: int) -> str:
    """Numéro fictif au format E.164 (indicatif du Burkina Faso)."""
    return f"+2267{n:07d}"


async def make_user(n: int = 1) -> str:
    return str(await get_or_create_user(phone(n)))


async def scalar(statement):
    async with session_scope() as session:
        return (await session.execute(statement)).scalar_one()


async def count(model) -> int:
    return await scalar(select(func.count()).select_from(model))


async def last_seen(user_id: uuid.UUID) -> datetime:
    return await scalar(select(User.last_seen_at).where(User.id == user_id))


async def expire(model, row_id: str | uuid.UUID) -> None:
    """Met expires_at dans le passé par SQL direct, sans passer par les stores."""
    async with session_scope() as session:
        await session.execute(
            update(model)
            .where(model.id == uuid.UUID(str(row_id)))
            .values(expires_at=func.now() - timedelta(minutes=1))
        )


async def assert_ttl(model, row_id: str | uuid.UUID, ttl: timedelta) -> None:
    """expires_at vaut now() + ttl (horloge de la base), à quelques secondes près."""
    async with session_scope() as session:
        row = (
            await session.execute(
                select(
                    model.expires_at > func.now() + ttl - timedelta(seconds=30),
                    model.expires_at <= func.now() + ttl,
                ).where(model.id == uuid.UUID(str(row_id)))
            )
        ).one()
    assert tuple(row) == (True, True)


async def message_id(inbound_id: str) -> uuid.UUID:
    return await scalar(select(Message.id).where(Message.inbound_id == inbound_id))


async def add_voice_note(user_key: str, msg_id: uuid.UUID) -> uuid.UUID:
    async with session_scope() as session:
        note = VoiceNote(
            user_id=uuid.UUID(user_key),
            message_id=msg_id,
            mime_type="audio/ogg",
            audio_enc=encrypt(b"audio-secret"),
            expires_at=func.now() + VOICE_TTL,
        )
        session.add(note)
        await session.flush()
        return note.id


async def populate(user_key: str, tag: str) -> None:
    """Une ligne dans chaque table enfant, voice_notes comprise."""
    await PgImageStore().put(user_key, PNG, "image/png")
    await ExtractionStore().put(user_key, "ordonnance", PAYLOAD)
    await MessageStore().add(user_key, "in", "voice", "transcription", f"wamid.{tag}")
    await add_voice_note(user_key, await message_id(f"wamid.{tag}"))


# --- get_or_create_user ------------------------------------------------------


async def test_get_or_create_user_is_idempotent():
    first = await get_or_create_user(phone(1))
    second = await get_or_create_user(phone(1))
    assert isinstance(first, uuid.UUID)
    assert first == second
    assert await count(User) == 1


async def test_distinct_phones_give_distinct_users():
    assert await make_user(1) != await make_user(2)
    assert await count(User) == 2


async def test_phone_is_stored_pseudonymised_and_encrypted():
    user_id = await get_or_create_user(phone(1))
    async with session_scope() as session:
        row = (
            await session.execute(
                select(User.phone_hmac, User.phone_enc).where(User.id == user_id)
            )
        ).one()
    assert len(row.phone_hmac) == 64
    assert phone(1) not in row.phone_hmac
    assert phone(1).encode() not in row.phone_enc
    assert decrypt_text(row.phone_enc) == normalize_phone(phone(1))


async def test_last_seen_at_is_refreshed_on_each_call():
    user_id = await get_or_create_user(phone(1))
    first = await last_seen(user_id)
    await asyncio.sleep(0.05)
    await get_or_create_user(phone(1))
    assert await last_seen(user_id) > first


async def test_get_or_create_user_concurrent_calls():
    ids = await asyncio.gather(*(get_or_create_user(phone(i % 3)) for i in range(15)))
    assert len(set(ids)) == 3
    assert await count(User) == 3


async def test_phone_hmac_is_unique_in_database():
    with pytest.raises(IntegrityError):
        async with session_scope() as session:
            session.add(User(phone_hmac="a" * 64, phone_enc=b"x"))
            session.add(User(phone_hmac="a" * 64, phone_enc=b"y"))
            await session.flush()
    assert await count(User) == 0


# --- PgImageStore ------------------------------------------------------------


async def test_image_roundtrip_and_encrypted_at_rest():
    store, user = PgImageStore(), await make_user()
    image_id = await store.put(user, PNG, "image/png")
    assert await store.get(user, image_id) == PNG
    stored = await scalar(
        select(Image.data_enc).where(Image.id == uuid.UUID(image_id))
    )
    assert stored != PNG
    assert PNG[:12] not in stored
    await assert_ttl(Image, image_id, IMAGE_TTL)


async def test_expired_image_is_unreadable():
    store, user = PgImageStore(), await make_user()
    image_id = await store.put(user, PNG, "image/png")
    await expire(Image, image_id)
    assert await store.get(user, image_id) is None


async def test_image_is_isolated_between_users():
    store = PgImageStore()
    alice, bob = await make_user(1), await make_user(2)
    image_id = await store.put(alice, PNG, "image/png")
    assert await store.get(bob, image_id) is None
    await store.delete(bob, image_id)
    assert await store.get(alice, image_id) == PNG


async def test_image_delete_is_idempotent():
    store, user = PgImageStore(), await make_user()
    image_id = await store.put(user, PNG, "image/png")
    await store.delete(user, image_id)
    assert await store.get(user, image_id) is None
    assert await count(Image) == 0
    await store.delete(user, image_id)  # déjà supprimée : sans erreur
    await store.delete(user, str(uuid.uuid4()))  # inconnue : sans erreur


async def test_image_delete_removes_expired_rows():
    store, user = PgImageStore(), await make_user()
    image_id = await store.put(user, PNG, "image/png")
    await expire(Image, image_id)
    await store.delete(user, image_id)
    assert await count(Image) == 0

async def test_image_put_rejects_unknown_mime_type():
    store, user = PgImageStore(), await make_user()
    with pytest.raises(ValueError):
        await store.put(user, PNG, "application/pdf")
    assert await count(Image) == 0


async def test_image_put_for_unknown_user_violates_foreign_key():
    with pytest.raises(IntegrityError):
        await PgImageStore().put(str(uuid.uuid4()), PNG, "image/png")


# --- ExtractionStore ---------------------------------------------------------


async def test_extraction_roundtrip_and_encrypted_at_rest():
    store, user = ExtractionStore(), await make_user()
    result_id = await store.put(user, "ordonnance", PAYLOAD)
    assert await store.get(user, result_id) == PAYLOAD
    stored = await scalar(
        select(ExtractionResult.payload_enc).where(
            ExtractionResult.id == uuid.UUID(result_id)
        )
    )
    assert b"Parac" not in stored
    image_type = await scalar(
        select(ExtractionResult.image_type).where(
            ExtractionResult.id == uuid.UUID(result_id)
        )
    )
    assert image_type == "ordonnance"
    await assert_ttl(ExtractionResult, result_id, EXTRACTION_TTL)


async def test_expired_extraction_is_unreadable():
    store, user = ExtractionStore(), await make_user()
    result_id = await store.put(user, "ordonnance", PAYLOAD)
    await expire(ExtractionResult, result_id)
    assert await store.get(user, result_id) is None


async def test_extraction_is_isolated_between_users():
    store = ExtractionStore()
    alice, bob = await make_user(1), await make_user(2)
    result_id = await store.put(alice, "ordonnance", PAYLOAD)
    assert await store.get(bob, result_id) is None
    assert await store.get(alice, result_id) == PAYLOAD


async def test_unknown_extraction_returns_none():
    user = await make_user()
    assert await ExtractionStore().get(user, str(uuid.uuid4())) is None


# --- MessageStore ------------------------------------------------------------


async def test_recent_returns_messages_oldest_first():
    store, user = MessageStore(), await make_user()
    for direction, text in [("in", "un"), ("out", "deux"), ("in", "trois")]:
        assert await store.add(user, direction, "text", text) is True
        await asyncio.sleep(0.005)
    records = await store.recent(user)
    assert [r.text for r in records] == ["un", "deux", "trois"]
    assert [r.direction for r in records] == ["in", "out", "in"]
    assert all(r.msg_type == "text" for r in records)


async def test_recent_limit_keeps_the_latest_messages():
    store, user = MessageStore(), await make_user()
    for i in range(5):
        await store.add(user, "in", "text", f"m{i}")
        await asyncio.sleep(0.005)
    records = await store.recent(user, limit=3)
    assert [r.text for r in records] == ["m2", "m3", "m4"]


async def test_inbound_id_deduplication():
    store, user = MessageStore(), await make_user()
    assert await store.add(user, "in", "text", "salut", inbound_id="wamid.ABC") is True
    assert await store.add(user, "in", "text", "salut", inbound_id="wamid.ABC") is False
    assert await count(Message) == 1


async def test_inbound_id_deduplication_under_concurrency():
    store, user = MessageStore(), await make_user()
    results = await asyncio.gather(
        *(store.add(user, "in", "text", "salut", "wamid.RACE") for _ in range(10))
    )
    assert results.count(True) == 1
    assert await count(Message) == 1


async def test_messages_without_inbound_id_are_never_deduplicated():
    store, user = MessageStore(), await make_user()
    assert await store.add(user, "out", "text", "a") is True
    assert await store.add(user, "out", "text", "b") is True
    assert await count(Message) == 2


async def test_message_text_is_encrypted_at_rest():
    store, user = MessageStore(), await make_user()
    await store.add(user, "in", "text", "mon secret", "wamid.S")
    stored = await scalar(select(Message.content_enc))
    assert b"secret" not in stored


async def test_message_without_text():
    store, user = MessageStore(), await make_user()
    assert await store.add(user, "in", "image", None, "wamid.IMG") is True
    [record] = await store.recent(user)
    assert record.text is None
    assert record.msg_type == "image"


async def test_message_ttl_is_seven_days():
    await MessageStore().add(await make_user(), "in", "text", "x", "wamid.TTL")
    await assert_ttl(Message, await message_id("wamid.TTL"), MESSAGE_TTL)


async def test_expired_messages_are_not_returned():
    store, user = MessageStore(), await make_user()
    await store.add(user, "in", "text", "vieux", "wamid.OLD")
    await expire(Message, await message_id("wamid.OLD"))
    assert await store.recent(user) == []


async def test_messages_are_isolated_between_users():
    store = MessageStore()
    alice, bob = await make_user(1), await make_user(2)
    await store.add(alice, "in", "text", "pour alice", "wamid.A")
    assert await store.recent(bob) == []
    assert [r.text for r in await store.recent(alice)] == ["pour alice"]


async def test_message_with_invalid_direction_is_rejected_by_the_database():
    with pytest.raises(IntegrityError):
        await MessageStore().add(await make_user(), "sideways", "text", "x")


async def test_message_for_unknown_user_violates_foreign_key():
    with pytest.raises(IntegrityError):
        await MessageStore().add(str(uuid.uuid4()), "in", "text", "x", "wamid.X")


# --- forget_user et cascades -------------------------------------------------


async def test_forget_user_cascades_to_all_children():
    alice, bob = await make_user(1), await make_user(2)
    await populate(alice, "a")
    await populate(bob, "b")
    assert await forget_user(alice) is True
    assert await count(User) == 1
    for model in CHILD_MODELS:
        assert await count(model) == 1, model.__tablename__  # ceux de bob


async def test_forget_user_unknown_or_repeated_returns_false():
    user = await make_user()
    assert await forget_user(user) is True
    assert await forget_user(user) is False
    assert await forget_user(str(uuid.uuid4())) is False


async def test_user_can_come_back_after_forget():
    old = await get_or_create_user(phone(1))
    assert await forget_user(str(old)) is True
    new = await get_or_create_user(phone(1))
    assert new != old
    assert await count(User) == 1


async def test_deleting_a_message_cascades_to_its_voice_note():
    await populate(await make_user(), "a")
    assert await count(VoiceNote) == 1
    async with session_scope() as session:
        await session.execute(sa_delete(Message))
    assert await count(VoiceNote) == 0


# --- Purge -------------------------------------------------------------------


async def test_purge_expired_deletes_only_expired_rows():
    user = await make_user()
    images, extractions, messages = PgImageStore(), ExtractionStore(), MessageStore()

    live_image = await images.put(user, PNG, "image/png")
    old_image = await images.put(user, PNG, "image/png")
    await expire(Image, old_image)

    await extractions.put(user, "ordonnance", PAYLOAD)
    old_extraction = await extractions.put(user, "ordonnance", PAYLOAD)
    await expire(ExtractionResult, old_extraction)

    for tag in ("a", "b", "c"):
        await messages.add(user, "in", "text", tag, f"wamid.{tag}")
    msg = {tag: await message_id(f"wamid.{tag}") for tag in "abc"}
    await expire(Message, msg["c"])
    await add_voice_note(user, msg["a"])
    old_note = await add_voice_note(user, msg["b"])
    await expire(VoiceNote, old_note)

    assert await purge_expired() == {
        "messages": 1,
        "images": 1,
        "extraction_results": 1,
        "voice_notes": 1,
    }
    assert await count(Message) == 2
    assert await count(Image) == 1
    assert await count(ExtractionResult) == 1
    assert await count(VoiceNote) == 1
    assert await images.get(user, live_image) == PNG
    assert await images.get(user, old_image) is None

    # Deuxième passage : plus rien à supprimer.
    assert set((await purge_expired()).values()) == {0}


async def test_purging_an_expired_message_removes_its_voice_note():
    user = await make_user()
    await MessageStore().add(user, "in", "voice", "t", "wamid.V")
    msg_id = await message_id("wamid.V")
    await add_voice_note(user, msg_id)  # la note elle-même n'est pas expirée
    await expire(Message, msg_id)
    counts = await purge_expired()
    assert counts["messages"] == 1
    assert counts["voice_notes"] == 0  # déjà partie par la cascade
    assert await count(VoiceNote) == 0


async def test_purge_loop_survives_errors_and_propagates_cancellation(monkeypatch):
    calls = 0

    async def flaky() -> dict[str, int]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")
        return {}

    monkeypatch.setattr(purge, "purge_expired", flaky)
    task = asyncio.create_task(purge.purge_loop(interval=0.01))
    for _ in range(200):
        if calls >= 3:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls >= 3  # l'exception du premier tour n'a pas arrêté la boucle