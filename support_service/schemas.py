from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from support_service import storage
from support_service.models import (
    AttachmentKind,
    SupportAttachment,
    SupportMessage,
    SupportTicket,
    TicketPriority,
    TicketStatus,
)


class TicketCreate(BaseModel):
    subject: str = Field(..., min_length=3, max_length=200)
    body: str = Field(..., min_length=5, max_length=5000)
    order_id: Optional[int] = Field(
        None, gt=0, description="Murojaat aniq buyurtmaga tegishli bo'lsa (egalik core'da tekshiriladi)"
    )
    priority: TicketPriority = TicketPriority.NORMAL


class MessageCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=5000)


class TicketStatusUpdate(BaseModel):
    status: TicketStatus


class AttachmentResponse(BaseModel):
    id: int
    filename: str
    content_type: str
    kind: AttachmentKind
    size: int
    # Imzolangan, qisqa muddatli havola (`storage.sign_url`).
    url: str


class MessageResponse(BaseModel):
    id: int
    ticket_id: int
    author_user_id: Optional[int] = None
    author_role: Optional[str] = None
    author_name: Optional[str] = None
    is_system: bool
    body: str
    created_at: datetime
    attachments: list[AttachmentResponse] = []


class MessagePreview(BaseModel):
    body: str
    author_role: Optional[str] = None
    author_name: Optional[str] = None
    is_system: bool
    has_attachments: bool = False
    created_at: datetime


class TicketListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    user_role: Optional[str] = None
    user_name: Optional[str] = None
    order_id: Optional[int] = None
    subject: str
    status: TicketStatus
    priority: TicketPriority
    assigned_to: Optional[int] = None
    assigned_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime
    # So'rovchining nuqtai nazaridan: egasi uchun — xodim javoblari,
    # xodim uchun — egasining xabarlari.
    unread_count: int = 0
    last_message: Optional[MessagePreview] = None
    # Shu foydalanuvchi qaysi holatlarga o'tkaza oladi (`rules.py`).
    allowed_statuses: list[TicketStatus] = []


class TicketPage(BaseModel):
    items: list[TicketListItem]
    total: int
    limit: int
    offset: int


class TicketDetail(TicketListItem):
    body: str
    # Oxirgi `messages_limit` ta xabar (o'sish tartibida). Eskilari —
    # `GET /tickets/{id}/messages?before_id=...`.
    messages: list[MessageResponse] = []
    has_more_messages: bool = False


class MessagePage(BaseModel):
    items: list[MessageResponse]
    has_more: bool


class MessageCreated(MessageResponse):
    """Javobdan keyin murojaatning yangilangan holati (masalan OPEN → IN_PROGRESS)."""

    ticket: TicketListItem


class UnreadSummary(BaseModel):
    tickets: int
    messages: int


# ─── Serializatsiya yordamchilari ────────────────────────────────────────────


def file_resource(attachment_id: int) -> str:
    return f"/support/files/{attachment_id}"


def attachment_out(att: SupportAttachment) -> AttachmentResponse:
    return AttachmentResponse(
        id=att.id,
        filename=att.filename,
        content_type=att.content_type,
        kind=att.kind,
        size=att.size,
        url=storage.sign_url(file_resource(att.id)),
    )


def message_out(msg: SupportMessage) -> MessageResponse:
    return MessageResponse(
        id=msg.id,
        ticket_id=msg.ticket_id,
        author_user_id=msg.author_user_id,
        author_role=msg.author_role,
        author_name=msg.author_name,
        is_system=msg.is_system,
        body=msg.body,
        created_at=msg.created_at,
        attachments=[attachment_out(a) for a in msg.attachments],
    )


def preview_out(msg: Optional[SupportMessage]) -> Optional[MessagePreview]:
    if msg is None:
        return None
    return MessagePreview(
        body=msg.body[:200],
        author_role=msg.author_role,
        author_name=msg.author_name,
        is_system=msg.is_system,
        has_attachments=bool(msg.attachments),
        created_at=msg.created_at,
    )


def ticket_out(
    ticket: SupportTicket,
    *,
    unread_count: int = 0,
    last_message: Optional[SupportMessage] = None,
    allowed: Optional[list[TicketStatus]] = None,
) -> TicketListItem:
    item = TicketListItem.model_validate(ticket)
    item.unread_count = unread_count
    item.last_message = preview_out(last_message)
    item.allowed_statuses = allowed or []
    return item
