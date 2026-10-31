from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_file_encoding="utf-8")

    PUBLIC_BASE_URL: str | None = None
    ENV: str = "prod"

    WHATSAPP_ACCESS_TOKEN: str | None = None
    WHATSAPP_PHONE_NUMBER_ID: str | None = None
    WHATSAPP_BUSINESS_ACCOUNT_ID: str | None = None
    META_APP_SECRET: str | None = None
    META_APP_ID: str | None = None
    WEBHOOK_VERIFY_TOKEN: str | None = None
    META_GRAPH_BASE_URL: str = "https://graph.facebook.com"

    # Flow WhatsApp (pièce d'identité) : facultatif, vide = pas de FlowButton
    WHATSAPP_FLOW_ID: str | None = None
    WHATSAPP_FLOW_BROUILLON: bool = True
    # LLMs
    GROQ_API_KEY: str
    GROQ_MODEL_TEXT: str = "openai/gpt-oss-120b"
    GROQ_MODEL_VISION: str = "qwen/qwen3.8-27b"
    STT_MODEL_NAME: str = "whisper-large-v3-turbo"
    STT_LANGUE: str | None = None

    # Cloudflare (voix)
    CLOUDFLARE_ACCOUNT_ID: str | None = None
    CLOUDFLARE_API_TOKEN: str | None = None

    # Synthèse vocale
    TTS_PROVIDERS: str = "edge,cloudflare"
    TTS_VOICE: str = "fr-FR-VivienneMultilingualNeural"  # Edge TTS
    TTS_LANG: str = "fr"  # Cloudflare MeloTTS
    TTS_MODEL_NAME: str = "eleven_flash_v2_5"  # ElevenLabs

    # Base de données et chiffrement (obligatoires)
    DATABASE_URL: str
    FERNET_KEYS: str
    PSEUDONYM_HMAC_KEY: str

    # Vector DB
    PINECONE_API_KEY: str | None = None
    PINECONE_INDEX: str | None = None

    SENTRY_DSN: str | None = None

    # Optionnelles
    GOOGLE_PLACES_API_KEY: str | None = None
    OPEN_METEO_API_KEY: str | None = None

    # Urgences
    EMERGENCY_NUMBERS: list[str] = []

    # RAG
    top_k: int = 3


@lru_cache
def get_setting() -> Settings:
    return Settings()
