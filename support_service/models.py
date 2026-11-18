"""Support mikroservizining o'z modellari (alohida `support_db` bazasida).

Asosiy tizim jadvallariga FK YO'Q va bo'lishi ham mumkin emas — bu boshqa baza.
`user_id` / `order_id` — shunchaki tashqi tizimning identifikatorlari (nusxa
ma'lumot). Bu mikroservizlar uchun odatiy: chegara bazalar orasidan o'tadi,
bog'lanish esa ID va hodisalar orqali.

MOLIYAVIY MAYDON YO'Q: bu yerda na narx, na balans, na komissiya saqlanadi —
menejer support bo'limida ham hech qanday pul ma'lumotini ko'rmaydi.

Sxema o'zgarishlari FAQAT `support_service/migrations` (alembic) orqali.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TicketStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class AttachmentKind(str, enum.Enum):
    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"


# Bu holatlardagi murojaatga yangi xabar yozilmaydi. RESOLVED'ni xodim qayta
# ochishi mumkin (`rules.py`), CLOSED esa yakuniy.
CLOSED_STATUSES = frozenset({TicketStatus.RESOLVED, TicketStatus.CLOSED})


def _enum(cls: type[enum.Enum], name: str) -> SQLEnum:
    return SQLEnum(cls, name=name, values_callable=lambda enum_cls: [m.value for m in enum_cls])


class SupportTicket(Base):
    __tablename__ = "support_tickets"
    __table_args__ = (
        # Ro'yxat oxirgi faollik bo'yicha tartiblanadi (`crud.list_tickets`).
        Index("ix_support_tickets_last_message_at", "last_message_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Asosiy tizimdagi foydalanuvchi ID si (Telegram ID bo'lgani uchun BigInteger).
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    # Murojaat yozilgan paytdagi roli va ismi — keyin o'zgarsa ham tarix saqlanadi.
    user_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    user_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[TicketStatus] = mapped_column(
        _enum(TicketStatus, "ticketstatus"), default=TicketStatus.OPEN, nullable=False, index=True
    )
    priority: Mapped[TicketPriority] = mapped_column(
        _enum(TicketPriority, "ticketpriority"), default=TicketPriority.NORMAL, nullable=False
    )

    # Murojaatni o'ziga olgan xodim.
    assigned_to: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    assigned_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # O'qilmaganlar: har tomon oxirgi marta qachon ko'rgani. Xabar shu vaqtdan
    # keyin yozilgan va qarshi tomonniki bo'lsa — o'qilmagan.
    user_last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    staff_last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    messages: Mapped[list["SupportMessage"]] = relationship(
        "SupportMessage",
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="SupportMessage.id",
    )


class SupportMessage(Base):
    __tablename__ = "support_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # `is_system=True` bo'lganda muallif yo'q — xabar RabbitMQ hodisasidan tug'ilgan
    # (masalan "buyurtma holati IN_PROGRESS ga o'zgardi").
    author_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    author_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    author_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Faqat biriktirmali xabarda bo'sh bo'lishi mumkin.
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    ticket: Mapped["SupportTicket"] = relationship("SupportTicket", back_populates="messages")
    attachments: Mapped[list["SupportAttachment"]] = relationship(
        "SupportAttachment",
        back_populates="message",
        cascade="all, delete-orphan",
        order_by="SupportAttachment.id",
        lazy="selectin",
    )


class SupportAttachment(Base):
    __tablename__ = "support_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("support_messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Ombordagi kalit (`storage.Storage`) — fayl tizimidagi yo'l emas.
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # MIME baytlardan aniqlangan (`mime.sniff`), mijoz yuborgan sarlavhadan emas.
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[AttachmentKind] = mapped_column(_enum(AttachmentKind, "attachmentkind"), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    message: Mapped["SupportMessage"] = relationship("SupportMessage", back_populates="attachments")
