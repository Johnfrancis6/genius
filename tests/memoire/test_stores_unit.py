"""Tests sans base : les entrées invalides lèvent ValueError avant tout accès DB.

Si une régression ouvrait une session avant de valider, ces tests échoueraient
(erreur de connexion ou de réglages au lieu de ValueError).
"""

import uuid

import pytest

from agent.stores import (
    ExtractionStore,
    MessageStore,
    PgImageStore,
    forget_user,
    to_uuid,
)

BAD_KEY = "pas-un-uuid"
GOOD_KEY = str(uuid.uuid4())
GOOD_ID = str(uuid.uuid4())

CALLS = {
    "image.put/user_key": lambda: PgImageStore().put(BAD_KEY, b"x", "image/png"),
    "image.put/mime_type": lambda: PgImageStore().put(GOOD_KEY, b"x", "text/html"),
    "image.get/user_key": lambda: PgImageStore().get(BAD_KEY, GOOD_ID),
    "image.get/image_id": lambda: PgImageStore().get(GOOD_KEY, BAD_KEY),
    "image.delete/user_key": lambda: PgImageStore().delete(BAD_KEY, GOOD_ID),
    "image.delete/image_id": lambda: PgImageStore().delete(GOOD_KEY, BAD_KEY),
    "extraction.put/user_key": lambda: ExtractionStore().put(BAD_KEY, "x", {}),
    "extraction.get/user_key": lambda: ExtractionStore().get(BAD_KEY, GOOD_ID),
    "extraction.get/result_id": lambda: ExtractionStore().get(GOOD_KEY, BAD_KEY),
    "message.add/user_key": lambda: MessageStore().add(BAD_KEY, "in", "text", "x"),
    "message.recent/user_key": lambda: MessageStore().recent(BAD_KEY),
    "forget_user/user_key": lambda: forget_user(BAD_KEY),
}


def test_to_uuid_accepts_str_of_uuid():
    user_id = uuid.uuid4()
    assert to_uuid(str(user_id)) == user_id


@pytest.mark.parametrize("bad", ["", "abc", BAD_KEY, "ab" * 32, "g" * 32])
def test_to_uuid_rejects_invalid_values(bad):
    with pytest.raises(ValueError):
        to_uuid(bad)


@pytest.mark.asyncio
@pytest.mark.parametrize("call", CALLS.values(), ids=CALLS.keys())
async def test_invalid_inputs_raise_value_error_before_any_db_access(call):
    with pytest.raises(ValueError):
        await call()
