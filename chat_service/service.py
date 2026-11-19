"""Baza amallari va javob shakllari (router yupqa qolishi uchun shu yerda)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from chat_service import domain, media_urls
from chat_service.models import Conversation, Media, Message, ReadMark
from chat_service.schemas import ConversationOut, MediaOut, MessageOut, ReplyOut


# --- Serializatsiya -----------------------------------------------------------


def media_out(media: Media) -> MediaOut:
    return MediaOut(
        id=media.id,
        kind=media.kind,
        mime=media.mime,
        size_bytes=media.size_bytes,
        url=media_urls.signed_url(media.id, "orig"),
        thumb_url=media_urls.signed_url(media.id, "thumb") if media.thumb_key else None,
        width=media.width,
        height=media.height,
        duration_s=media.duration_s,
        name=media.original_name,
    )


def message_out(msg: Message, order_id: int) -> MessageOut:
    deleted = msg.deleted_at is not None
    reply: Optional[ReplyOut] = None
    if msg.reply_to is not None:
        r = msg.reply_to
        reply = ReplyOut(
            id=r.id,
            sender_user_id=r.sender_user_id,
            kind=r.kind,
            preview="" if r.deleted_at else domain.preview_text(r.kind, r.text, limit=80),
            deleted=r.deleted_at is not None,
        )
    return MessageOut(
        id=msg.id,
        order_id=order_id,
        sender_user_id=msg.sender_user_id,
        kind=msg.kind,
        text=None if deleted else msg.text,
        media=None if deleted or msg.media is None else media_out(msg.media),
        duration_s=None if deleted else msg.duration_s,
        lat=None if deleted else msg.lat,
        lon=None if deleted else msg.lon,
        reply_to=None if deleted else reply,
        client_id=msg.client_id,
        created_at=domain.as_utc(msg.created_at),  # type: ignore[arg-type]
        edited_at=domain.as_utc(msg.edited_at),
        deleted_at=domain.as_utc(msg.deleted_at),
    )


# --- O'qilgan belgilari --------------------------------------------------------


async def get_read_marks(db: AsyncSession, conv_id: int) -> dict[int, int]:
    rows = await db.execute(
        select(ReadMark.user_id, ReadMark.last_read_message_id).where(ReadMark.conversation_id == conv_id)
    )
    return {int(uid): int(last) for uid, last in rows.all()}


async def advance_read_mark(db: AsyncSession, conv_id: int, user_id: int, message_id: int) -> int:
    """Belgini faqat OLDINGA suradi (eski so'rov kechikib kelsa orqaga qaytmasin).
    Natijadagi qiymatni qaytaradi; o'zgarmagan bo'lsa ham joriy qiymat."""
    mark = await db.get(ReadMark, (conv_id, user_id))
    if mark is None:
        mark = ReadMark(conversation_id=conv_id, user_id=user_id, last_read_message_id=message_id)
        db.add(mark)
    elif message_id > mark.last_read_message_id:
        mark.last_read_message_id = message_id
    return mark.last_read_message_id


async def max_message_id(db: AsyncSession, conv_id: int) -> int:
    value = await db.scalar(select(func.max(Message.id)).where(Message.conversation_id == conv_id))
    return int(value or 0)


async def unread_count(db: AsyncSession, conv_id: int, user_id: int, last_read: int) -> int:
    value = await db.scalar(
        select(func.count(Message.id)).where(
            Message.conversation_id == conv_id,
            Message.sender_user_id != user_id,
            Message.id > last_read,
            Message.deleted_at.is_(None),
        )
    )
    return int(value or 0)


async def conversation_out(
    db: AsyncSession, conv: Conversation, user_id: int, now: datetime, *, with_last: bool = False
) -> ConversationOut:
    marks = await get_read_marks(db, conv.id)
    peer = domain.peer_user_id(conv, user_id)
    my_last = marks.get(user_id, 0)
    last_message = None
    if with_last:
        msg = await db.scalar(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.id.desc())
            .limit(1)
        )
        if msg is not None:
            last_message = message_out(msg, conv.order_id)
    return ConversationOut(
        id=conv.id,
        order_id=conv.order_id,
        status=domain.effective_status(conv, now),  # type: ignore[arg-type]
        write_blocked_reason=domain.write_block_reason(conv, now),
        readonly_at=domain.as_utc(conv.readonly_at),
        order_status=conv.order_status,
        my_role=domain.role_of(conv, user_id) or domain.ROLE_SENDER,  # type: ignore[arg-type]
        peer_user_id=peer,
        my_last_read_id=my_last,
        peer_last_read_id=marks.get(peer, 0) if peer is not None else 0,
        unread_count=await unread_count(db, conv.id, user_id, my_last),
        last_message_at=domain.as_utc(conv.last_message_at),
        last_message=last_message,
    )


# --- Xabarlar ---------------------------------------------------------------


async def list_messages(
    db: AsyncSession,
    conv_id: int,
    *,
    before_id: Optional[int] = None,
    after_id: Optional[int] = None,
    limit: int = 50,
) -> Sequence[Message]:
    """Doim o'sish tartibida qaytaradi.

    * `after_id` — undan keyingilar (qayta ulanish, eng eskisidan boshlab);
    * `before_id` — undan oldingi sahifa (yuqoriga aylantirganda eski xabarlar);
    * ikkalasi yo'q — eng oxirgi sahifa.
    """
    stmt = select(Message).where(Message.conversation_id == conv_id)
    if after_id is not None:
        stmt = stmt.where(Message.id > after_id).order_by(Message.id.asc()).limit(limit)
        return list((await db.execute(stmt)).scalars().unique().all())
    if before_id is not None:
        stmt = stmt.where(Message.id < before_id)
    stmt = stmt.order_by(Message.id.desc()).limit(limit)
    rows = list((await db.execute(stmt)).scalars().unique().all())
    rows.reverse()
    return rows


async def changed_since(
    db: AsyncSession, conv_id: int, since: datetime, up_to_id: int, limit: int = 200
) -> Sequence[Message]:
    """`up_to_id` gacha bo'lgan (mijozda bor) xabarlardan `since` dan keyin
    tahrirlangan yoki o'chirilganlari."""
    stmt = (
        select(Message)
        .where(
            Message.conversation_id == conv_id,
            Message.id <= up_to_id,
            Message.updated_at > since,
            or_(Message.edited_at.is_not(None), Message.deleted_at.is_not(None)),
        )
        .order_by(Message.id.asc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().unique().all())


async def get_message(db: AsyncSession, conv_id: int, message_id: int) -> Optional[Message]:
    msg = await db.get(Message, message_id)
    if msg is None or msg.conversation_id != conv_id:
        return None
    return msg


async def find_by_client_id(
    db: AsyncSession, conv_id: int, user_id: int, client_id: str
) -> Optional[Message]:
    return await db.scalar(
        select(Message).where(
            Message.conversation_id == conv_id,
            Message.sender_user_id == user_id,
            Message.client_id == client_id,
        )
    )


async def media_in_use(db: AsyncSession, media_id: str) -> bool:
    return (await db.scalar(select(Message.id).where(Message.media_id == media_id))) is not None


async def conversations_for_user(db: AsyncSession, user_id: int) -> Sequence[Conversation]:
    stmt = (
        select(Conversation)
        .where(or_(Conversation.sender_user_id == user_id, Conversation.driver_user_id == user_id))
        .order_by(Conversation.last_message_at.desc().nulls_last(), Conversation.id.desc())
        .limit(100)
    )
    return list((await db.execute(stmt)).scalars().all())
