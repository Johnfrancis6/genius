import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    LargeBinary,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    phone_hmac: Mapped[str] = mapped_column(String(64), unique=True)
    phone_enc: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("direction IN ('in', 'out')", name="direction_valid"),
        Index("ix_messages_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    inbound_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    direction: Mapped[str] = mapped_column(String(8))
    msg_type: Mapped[str] = mapped_column(String(16))
    content_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ConversationStateRow(Base):
    __tablename__ = "conversation_states"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    state_enc: Mapped[bytes] = mapped_column(LargeBinary)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Image(Base):
    __tablename__ = "images"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    data_enc: Mapped[bytes] = mapped_column(LargeBinary)
    mime_type: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ExtractionResult(Base):
    __tablename__ = "extraction_results"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    image_type: Mapped[str] = mapped_column(String(32))
    payload_enc: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class VoiceNote(Base):
    __tablename__ = "voice_notes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), unique=True
    )
    mime_type: Mapped[str] = mapped_column(String(64))
    duration_ms: Mapped[int | None]
    audio_enc: Mapped[bytes] = mapped_column(LargeBinary)
    language: Mapped[str] = mapped_column(String(8), default="fr", server_default="fr")
    stt_model: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Quarter(Base):
    __tablename__ = "quarters"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    osm_ref: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    name_norm: Mapped[str] = mapped_column(String(128), index=True)
    place_type: Mapped[str] = mapped_column(String(16))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)


class OsmPlace(Base):
    __tablename__ = "osm_places"
    __table_args__ = (CheckConstraint("kind IN ('pharmacy', 'health_center')", name="kind_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    osm_ref: Mapped[str] = mapped_column(String(32), unique=True)
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str | None] = mapped_column(String(255))
    osm_tag: Mapped[str] = mapped_column(String(32))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    quartier_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("quarters.id", ondelete="SET NULL"), index=True
    )
    duplicate_of: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("osm_places.id", ondelete="SET NULL")
    )
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConfirmedPlace(Base):
    __tablename__ = "confirmed_places"

    osm_ref: Mapped[str] = mapped_column(String(32), primary_key=True)
    phone: Mapped[str | None] = mapped_column(String(32))
    hours_text: Mapped[str | None] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class OnCallPharmacy(Base):
    __tablename__ = "on_call_pharmacies"
    __table_args__ = (CheckConstraint("end_at > start_at", name="period_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    osm_ref: Mapped[str] = mapped_column(String(32), index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(64))


class DemoStock(Base):
    """Stock simulé pour la démo. Sans FK vers osm_places : supprimable d'un bloc."""

    __tablename__ = "demo_stock"
    __table_args__ = (UniqueConstraint("osm_ref", "produit_norm"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    osm_ref: Mapped[str] = mapped_column(String(32), index=True)
    produit_norm: Mapped[str] = mapped_column(String(100))
    disponible: Mapped[bool] = mapped_column()
    mis_a_jour_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DemoAgent(Base):
    """Agent de santé fictif de la démo. Numéros NUM-TEST-n uniquement."""

    __tablename__ = "demo_agents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    nom: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(40))
    situations: Mapped[list[str]] = mapped_column(ARRAY(String(20)))
    telephone: Mapped[str] = mapped_column(String(30))
    horaires: Mapped[str] = mapped_column(String(100))
    actif: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
