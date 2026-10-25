import hashlib
import hmac
import re
from functools import lru_cache

from cryptography.fernet import Fernet, MultiFernet

from agent.settings import get_setting


def build_fernet(keys_csv: str) -> MultiFernet:
    """Découpe sur la virgule (espaces ignorés). 1re clé = chiffrement, toutes = déchiffrement.
    Lève ValueError si une clé est invalide ou si la liste est vide."""
    keys = [key.strip() for key in keys_csv.split(",") if key.strip()]

    if not keys:
        raise ValueError("Aucune clé fournie")
    try:
        return MultiFernet([Fernet(k) for k in keys])
    except ValueError as e:
        raise ValueError("Clé(s) invalide(s)") from e


@lru_cache(maxsize=1)
def get_fernet() -> MultiFernet:
    """Version en cache, alimentée par settings.FERNET_KEYS."""
    return build_fernet(get_setting().FERNET_KEYS)


def encrypt(data: bytes) -> bytes:
    return get_fernet().encrypt(data)


def decrypt(token: bytes) -> bytes:
    return get_fernet().decrypt(token)


def encrypt_text(text: str) -> bytes:
    return encrypt(text.encode("utf-8"))


def decrypt_text(token: bytes) -> str:
    return decrypt(token).decode("utf-8")


def normalize_phone(raw: str | None) -> str:
    """Retourne le numéro en E.164 : '+' suivi de chiffres uniquement."""
    if raw is None:
        raise ValueError("Numéro de téléphone non fourni")
    number = re.sub(r"\D", "", raw)
    if number.startswith("00"):
        number = number[2:]
    if not number:
        raise ValueError("Numéro de téléphone vide")
    if len(number) > 15:
        raise ValueError("Numéro de téléphone de plus de 15 chiffres")
    return f"+{number}"


def phone_hmac(phone: str, key: str | None = None) -> str:
    """HMAC-SHA256 hexadécimal (64 caractères) du numéro normalisé en E.164."""
    normalized_phone = normalize_phone(phone)
    if key is None:
        key = get_setting().PSEUDONYM_HMAC_KEY
    return hmac.new(
        key.encode("utf-8"),
        normalized_phone.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()