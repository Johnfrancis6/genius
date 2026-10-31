import hashlib
import hmac as hmac_module
import re

import pytest
from cryptography.fernet import Fernet, InvalidToken

from agent.memoire import crypto
from agent.settings import get_setting

NUMERO = "22670123456"
NUMERO_E164 = "+22670123456"


# ---------- Fixtures ----------


@pytest.fixture
def key_a() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def key_b() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def fernet_a(monkeypatch, key_a):
    """encrypt/decrypt utilisent la clé A sans passer par les réglages."""
    monkeypatch.setattr(crypto, "get_fernet", lambda: crypto.build_fernet(key_a))


@pytest.fixture
def env(monkeypatch, key_a):
    """Variables d'environnement minimales + caches vidés avant et après."""
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/db")
    monkeypatch.setenv("FERNET_KEYS", key_a)
    monkeypatch.setenv("PSEUDONYM_HMAC_KEY", "cle-hmac-de-test")
    get_setting.cache_clear()
    crypto.get_fernet.cache_clear()
    yield
    get_setting.cache_clear()
    crypto.get_fernet.cache_clear()


# ---------- build_fernet ----------


@pytest.mark.parametrize("keys_csv", ["", " ", ",", " , "])
def test_build_fernet_empty_raises(keys_csv):
    with pytest.raises(ValueError):
        crypto.build_fernet(keys_csv)


def test_build_fernet_invalid_key_raises():
    with pytest.raises(ValueError) as exc:
        crypto.build_fernet("pas-une-cle")
    assert "pas-une-cle" not in str(exc.value)  # la clé ne fuit pas dans le message


def test_build_fernet_one_invalid_among_valid_raises(key_a):
    with pytest.raises(ValueError):
        crypto.build_fernet(f"{key_a},pas-une-cle")


def test_build_fernet_strips_spaces_and_uses_first_key_to_encrypt(key_a, key_b):
    cipher = crypto.build_fernet(f" {key_a} , {key_b} ")
    token = cipher.encrypt(b"secret")
    assert Fernet(key_a).decrypt(token) == b"secret"  # 1re clé = chiffrement
    with pytest.raises(InvalidToken):
        Fernet(key_b).decrypt(token)


# ---------- get_fernet ----------


def test_get_fernet_uses_settings(env, key_a):
    token = Fernet(key_a).encrypt(b"x")
    assert crypto.get_fernet().decrypt(token) == b"x"


def test_get_fernet_is_cached(env):
    assert crypto.get_fernet() is crypto.get_fernet()


# ---------- encrypt / decrypt ----------


def test_roundtrip_bytes(fernet_a):
    data = b"\x00\x01 donnees binaires \xff"
    assert crypto.decrypt(crypto.encrypt(data)) == data


def test_roundtrip_text_with_accents(fernet_a):
    text = "ordonnance à renouveler, é ç ü ñ œ"
    assert crypto.decrypt_text(crypto.encrypt_text(text)) == text


def test_encrypt_text_returns_bytes_and_hides_plaintext(fernet_a):
    token = crypto.encrypt_text("Paracétamol")
    assert isinstance(token, bytes)
    assert b"Parac" not in token


def test_two_encryptions_of_same_text_differ(fernet_a):
    assert crypto.encrypt(b"meme texte") != crypto.encrypt(b"meme texte")


def test_tampered_token_raises(fernet_a):
    token = crypto.encrypt(b"secret")
    i = len(token) // 2
    replacement = b"A" if token[i : i + 1] != b"A" else b"B"
    tampered = token[:i] + replacement + token[i + 1 :]
    with pytest.raises(InvalidToken):
        crypto.decrypt(tampered)


def test_garbage_token_raises(fernet_a):
    with pytest.raises(InvalidToken):
        crypto.decrypt(b"pas-un-jeton")


def test_wrong_key_raises(key_a, key_b):
    token = crypto.build_fernet(key_a).encrypt(b"x")
    with pytest.raises(InvalidToken):
        crypto.build_fernet(key_b).decrypt(token)


def test_key_rotation(key_a, key_b):
    old_token = crypto.build_fernet(key_a).encrypt(b"secret")

    rotated = crypto.build_fernet(f"{key_b},{key_a}")  # nouvelle clé en 1re position
    assert rotated.decrypt(old_token) == b"secret"  # l'ancien chiffré reste lisible

    new_token = rotated.encrypt(b"autre")
    assert Fernet(key_b).decrypt(new_token) == b"autre"  # le nouveau utilise la clé B

    with pytest.raises(InvalidToken):  # après retrait de A
        crypto.build_fernet(key_b).decrypt(old_token)


# ---------- normalize_phone ----------


@pytest.mark.parametrize(
    "raw",
    [
        "22670123456",
        "+22670123456",
        "+226 70 12 34 56",
        "226-70-12-34-56",
        "(226) 70 12 34 56",
        "0022670123456",
    ],
)
def test_normalize_phone_e164(raw):
    assert crypto.normalize_phone(raw) == NUMERO_E164


def test_normalize_phone_accepts_15_digits():
    assert crypto.normalize_phone("123456789012345") == "+123456789012345"


@pytest.mark.parametrize("raw", [None, "", "   ", "abc", "+", "00", "1234567890123456"])
def test_normalize_phone_invalid_raises(raw):
    with pytest.raises(ValueError):
        crypto.normalize_phone(raw)


def test_normalize_phone_error_does_not_leak_number():
    with pytest.raises(ValueError) as exc:
        crypto.normalize_phone("1234567890123456")
    assert "1234567890123456" not in str(exc.value)


# ---------- phone_hmac ----------


def test_phone_hmac_stable_across_formats():
    assert crypto.phone_hmac(NUMERO, key="k") == crypto.phone_hmac("+226 70 12 34 56", key="k")


def test_phone_hmac_differs_per_number():
    assert crypto.phone_hmac("22670123456", key="k") != crypto.phone_hmac("22670123457", key="k")


def test_phone_hmac_differs_per_key():
    assert crypto.phone_hmac(NUMERO, key="k1") != crypto.phone_hmac(NUMERO, key="k2")


def test_phone_hmac_is_64_hex_chars():
    assert re.fullmatch(r"[0-9a-f]{64}", crypto.phone_hmac(NUMERO, key="k"))


def test_phone_hmac_does_not_contain_number():
    assert NUMERO not in crypto.phone_hmac(NUMERO, key="k")


def test_phone_hmac_matches_reference_implementation():
    """Garde-fou : si ce test casse, tous les hash en base deviennent introuvables."""
    expected = hmac_module.new(b"k", NUMERO_E164.encode(), hashlib.sha256).hexdigest()
    assert crypto.phone_hmac(NUMERO, key="k") == expected


def test_phone_hmac_invalid_phone_raises():
    with pytest.raises(ValueError):
        crypto.phone_hmac("abc", key="k")


def test_phone_hmac_default_key_comes_from_settings(env):
    assert crypto.phone_hmac(NUMERO) == crypto.phone_hmac(NUMERO, key="cle-hmac-de-test")
