"""Chat mikroservizining jadvallari (alohida `chat_db` bazasida).

Asosiy tizim jadvallariga FK YO'Q: `order_id`, `*_user_id`, `driver_id` — tashqi
tizimning identifikatorlari (nusxa). Ular `order.*` hodisalaridan to'ldiriladi
(`chat_service/events.py`).

Go'ga ko'chirishni yengillatish uchun ataylab oddiy turlar: enum o'rniga `String`
(qiymatlar `domain.py` dagi konstantalar), JSON ustun yo'q, vaqtlar UTC.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Postgres'da BIGSERIAL, SQLite'da (testlar) INTEGER PRIMARY KEY — SQLite faqat
# aynan `INTEGER` turidagi kalitni avtomatik oshiradi.
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)

    # Yuk egasi — asosiy tizimdagi `orders.customer_id` (= users.id = JWT `sub`).
    sender_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    # Haydovchi: `drivers.id` (hodisada doim bor) va `users.id` (hodisada bo'lsa yoki
    # haydovchi birinchi kirganda core orqali tasdiqlangach to'ldiriladi).
    driver_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    driver_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)

    # open | readonly (domain.ConversationStatus). `readonly_at` kelgach `open` ham
    # amalda readonly hisoblanadi — cron kerak emas, holat o'qilganda hisoblanadi.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    order_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    readonly_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Oxirgi qo'llangan buyurtma hodisasining vaqti: navbatdan kechikib kelgan eski
    # hodisa (masalan COMPLETED dan keyin ACCEPTED) chatni qayta ochib yubormasin.
    last_event_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    last_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class Media(Base):
    __tablename__ = "media"

    # Taxmin qilib bo'lmaydigan id (uuid4 hex): imzosiz URL bo'lmasa ham ketma-ket
    # id'larni sinab chiqib bo'lmasin.
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uploader_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    mime: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    thumb_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_s: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    original_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_id_id", "conversation_id", "id"),
        # Mijoz qayta yuborganda (tarmoq uzilib, javob kelmay qolsa) dublikat bo'lmasin.
        UniqueConstraint("conversation_id", "sender_user_id", "client_id", name="uq_messages_client_id"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    sender_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # text | photo | video | voice | document | location (domain.MessageKind)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # Matnli xabarda — matn, mediada — izoh (caption).
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    media_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("media.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    duration_s: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reply_to_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    client_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    edited_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Qayta ulanishdagi sinxronlash uchun: tahrir/o'chirish ham shu vaqtni yangilaydi.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    media: Mapped[Optional[Media]] = relationship(Media, lazy="joined")
    reply_to: Mapped[Optional["Message"]] = relationship(
        "Message", remote_side="Message.id", lazy="joined", join_depth=1
    )


class ReadMark(Base):
    """Har ishtirokchi uchun "shu id gacha o'qidim" belgisi (monoton o'sadi)."""

    __tablename__ = "read_marks"

    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    last_read_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
