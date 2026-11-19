from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from chat_service.config import MAX_TEXT_LEN

MessageKindLiteral = Literal["text", "photo", "video", "voice", "document", "location"]


class MediaOut(BaseModel):
    id: str
    kind: str
    mime: str
    size_bytes: int
    url: str
    thumb_url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration_s: Optional[float] = None
    name: Optional[str] = None


class ReplyOut(BaseModel):
    id: int
    sender_user_id: int
    kind: str
    preview: str
    deleted: bool


class MessageOut(BaseModel):
    id: int
    order_id: int
    sender_user_id: int
    kind: str
    text: Optional[str] = None
    media: Optional[MediaOut] = None
    duration_s: Optional[float] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    reply_to: Optional[ReplyOut] = None
    client_id: Optional[str] = None
    created_at: datetime
    edited_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None


class MessageCreate(BaseModel):
    kind: MessageKindLiteral = "text"
    text: Optional[str] = Field(None, max_length=MAX_TEXT_LEN)
    media_id: Optional[str] = Field(None, max_length=32)
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lon: Optional[float] = Field(None, ge=-180, le=180)
    reply_to_id: Optional[int] = None
    # Mijozdagi vaqtinchalik id: qayta yuborishda dublikat yaratmaslik va optimistik
    # xabarni server javobi bilan almashtirish uchun.
    client_id: Optional[str] = Field(None, max_length=64)

    @model_validator(mode="after")
    def _check_shape(self) -> "MessageCreate":
        text = (self.text or "").strip()
        self.text = text or None
        if self.kind == "text":
            if not text:
                raise ValueError("Matn bo'sh bo'lishi mumkin emas")
            if self.media_id or self.lat is not None:
                raise ValueError("Matnli xabarda media yoki joylashuv bo'lmaydi")
        elif self.kind == "location":
            if self.lat is None or self.lon is None:
                raise ValueError("Joylashuv uchun lat va lon kerak")
            if self.media_id:
                raise ValueError("Joylashuv xabarida media bo'lmaydi")
            self.text = None
        else:
            if not self.media_id:
                raise ValueError("Media xabari uchun avval faylni yuklang (media_id)")
            if self.kind == "voice":
                self.text = None  # ovozli xabarga izoh yo'q (Telegram'dagi kabi)
        return self


class MessageEdit(BaseModel):
    text: str = Field(..., max_length=MAX_TEXT_LEN)


class ReadRequest(BaseModel):
    last_read_message_id: int = Field(..., ge=0)


class ConversationOut(BaseModel):
    id: int
    order_id: int
    status: Literal["open", "readonly"]
    # Yozib bo'lmasa — sabab (readonly yoki haydovchi yo'q); bo'lsa null.
    write_blocked_reason: Optional[str] = None
    readonly_at: Optional[datetime] = None
    order_status: Optional[str] = None
    my_role: Literal["sender", "driver"]
    peer_user_id: Optional[int] = None
    my_last_read_id: int = 0
    peer_last_read_id: int = 0
    unread_count: int = 0
    last_message_at: Optional[datetime] = None
    last_message: Optional[MessageOut] = None


class UnreadOut(BaseModel):
    order_id: int
    unread_count: int


class SyncOut(BaseModel):
    """Qayta ulanishda: `after_id` dan keyingi yangi xabarlar + `since` dan beri
    tahrirlangan/o'chirilgan eski xabarlar + suhbatning joriy holati."""

    messages: list[MessageOut]
    changed: list[MessageOut]
    conversation: ConversationOut
    server_time: datetime
