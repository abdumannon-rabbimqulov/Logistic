"""Chat endpointlari (`/chat/...`).

Kirish: faqat buyurtmaning ikki ishtirokchisi (`access.get_conversation_for`).
Suhbat buyurtma raqami bilan topiladi — mijoz o'z buyurtmasining id sini allaqachon
biladi, alohida "conversation id" ni izlashi shart emas.

Yozish amallari (xabar, media, tahrir, o'chirish) suhbat readonly bo'lsa 409.
O'qilgan belgisi readonly'da ham qo'yiladi — yopilgan chatni ochib o'qish ham
"o'qildi" bo'lishi kerak.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from chat_service import domain, media_urls, queue, service
from chat_service.access import get_conversation_for
from chat_service.auth import Principal, get_principal
from chat_service.config import EDIT_WINDOW_S, MAX_BYTES, MAX_VOICE_SECONDS, PAGE_SIZE_MAX, THUMB_MAX_PX
from chat_service.db import get_db
from chat_service.mime import EXTENSIONS, MimeRejected, resolve_mime, sniff_mime
from chat_service.models import Conversation, Media, Message, utcnow
from chat_service.realtime import get_broadcaster
from chat_service.schemas import ConversationOut, MessageCreate, MessageEdit, ReadRequest
from chat_service.storage import get_storage
from chat_service.thumbs import make_thumbnail

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_writable(conv: Conversation) -> None:
    reason = domain.write_block_reason(conv, _now())
    if reason:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=reason)


async def _broadcast(conv: Conversation, event: dict) -> None:
    await get_broadcaster().publish({conv.sender_user_id, conv.driver_user_id}, event)


# --- Suhbatlar ---------------------------------------------------------------


@router.get("/conversations", response_model=List[ConversationOut], summary="Mening chatlarim")
async def list_conversations(
    db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)
):
    now = _now()
    convs = await service.conversations_for_user(db, principal.user_id)
    return [await service.conversation_out(db, c, principal.user_id, now, with_last=True) for c in convs]


@router.get("/orders/{order_id}", response_model=ConversationOut, summary="Buyurtma chati")
async def get_conversation(
    order_id: int, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)
):
    conv, _ = await get_conversation_for(db, order_id, principal)
    return await service.conversation_out(db, conv, principal.user_id, _now())


@router.get("/orders/{order_id}/messages", summary="Xabarlar (sahifalab)")
async def get_messages(
    order_id: int,
    before_id: Optional[int] = Query(None, ge=1),
    after_id: Optional[int] = Query(None, ge=0),
    limit: int = Query(50, ge=1, le=PAGE_SIZE_MAX),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    conv, _ = await get_conversation_for(db, order_id, principal)
    rows = await service.list_messages(db, conv.id, before_id=before_id, after_id=after_id, limit=limit)
    return {
        "messages": [service.message_out(m, order_id) for m in rows],
        # Sahifa to'lgan bo'lsa — yana bo'lishi mumkin ("eski xabarlarni yuklash").
        "has_more": len(rows) == limit,
    }


@router.get("/orders/{order_id}/sync", summary="Qayta ulanishda o'tkazib yuborilganlar")
async def sync(
    order_id: int,
    after_id: int = Query(0, ge=0),
    since: Optional[datetime] = Query(None, description="Oxirgi sinxronlash vaqti (server_time)"),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    conv, _ = await get_conversation_for(db, order_id, principal)
    new_rows = await service.list_messages(db, conv.id, after_id=after_id, limit=PAGE_SIZE_MAX)
    changed = []
    if since is not None:
        since_utc = domain.as_utc(since)
        changed = await service.changed_since(db, conv.id, since_utc, after_id)  # type: ignore[arg-type]
    server_time = _now()
    return {
        "messages": [service.message_out(m, order_id) for m in new_rows],
        "has_more": len(new_rows) == PAGE_SIZE_MAX,
        "changed": [service.message_out(m, order_id) for m in changed],
        "conversation": await service.conversation_out(db, conv, principal.user_id, server_time),
        "server_time": server_time,
    }


@router.get("/orders/{order_id}/unread", summary="O'qilmaganlar soni (badge)")
async def get_unread(
    order_id: int, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)
):
    conv, _ = await get_conversation_for(db, order_id, principal)
    marks = await service.get_read_marks(db, conv.id)
    count = await service.unread_count(db, conv.id, principal.user_id, marks.get(principal.user_id, 0))
    return {"order_id": order_id, "unread_count": count, "status": domain.effective_status(conv, _now())}


# --- Xabar yuborish / tahrirlash / o'chirish --------------------------------------


@router.post("/orders/{order_id}/messages", status_code=status.HTTP_201_CREATED, summary="Xabar yuborish")
async def send_message(
    order_id: int,
    data: MessageCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    conv, _ = await get_conversation_for(db, order_id, principal)

    if data.client_id:
        existing = await service.find_by_client_id(db, conv.id, principal.user_id, data.client_id)
        if existing is not None:
            response.status_code = status.HTTP_200_OK
            return service.message_out(existing, order_id)

    _ensure_writable(conv)

    reply_to_id = None
    if data.reply_to_id is not None:
        target = await service.get_message(db, conv.id, data.reply_to_id)
        if target is None:
            raise HTTPException(422, detail="Javob berilayotgan xabar topilmadi")
        reply_to_id = target.id

    media: Optional[Media] = None
    if data.media_id:
        media = await db.get(Media, data.media_id)
        if (
            media is None
            or media.conversation_id != conv.id
            or media.uploader_user_id != principal.user_id
        ):
            raise HTTPException(422, detail="Fayl topilmadi")
        if media.kind != data.kind:
            raise HTTPException(
                422,
                detail=f"Fayl turi ({media.kind}) xabar turiga ({data.kind}) mos emas",
            )
        if await service.media_in_use(db, media.id):
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Bu fayl allaqachon yuborilgan")

    now = utcnow()
    msg = Message(
        conversation_id=conv.id,
        sender_user_id=principal.user_id,
        kind=data.kind,
        text=data.text,
        media_id=media.id if media else None,
        duration_s=media.duration_s if media else None,
        lat=data.lat,
        lon=data.lon,
        reply_to_id=reply_to_id,
        client_id=data.client_id,
        created_at=now,
        updated_at=now,
    )
    db.add(msg)
    conv.last_message_at = now
    try:
        await db.flush()
    except IntegrityError:
        # Bir xil client_id bilan parallel ikki so'rov — ikkinchisi birinchisini qaytaradi.
        await db.rollback()
        existing = await service.find_by_client_id(db, conv.id, principal.user_id, data.client_id or "")
        if existing is None:
            raise
        response.status_code = status.HTTP_200_OK
        return service.message_out(existing, order_id)

    # O'z xabari o'qilgan hisoblanadi — aks holda yuboruvchida o'qilmaganlar soni o'sardi.
    await service.advance_read_mark(db, conv.id, principal.user_id, msg.id)
    await db.commit()
    await db.refresh(msg, attribute_names=["media", "reply_to"])

    out = service.message_out(msg, order_id)
    payload = out.model_dump(mode="json")
    await _broadcast(conv, {"type": "message.new", "order_id": order_id, "message": payload})

    recipient = domain.peer_user_id(conv, principal.user_id)
    await queue.publish_event(
        queue.EVENT_CHAT_MESSAGE_CREATED,
        {
            "order_id": order_id,
            "conversation_id": conv.id,
            "message_id": msg.id,
            "kind": msg.kind,
            "preview": domain.preview_text(msg.kind, msg.text),
            "sender_user_id": principal.user_id,
            "sender_role": domain.role_of(conv, principal.user_id),
            # Haydovchining user_id si hali noma'lum bo'lishi mumkin — iste'molchi
            # (core) uni `recipient_driver_id` orqali o'z bazasidan topadi.
            "recipient_user_id": recipient,
            "recipient_driver_id": conv.driver_id if recipient != conv.sender_user_id else None,
            "recipient_online": await get_broadcaster().is_online(recipient),
        },
    )
    return out


@router.patch("/orders/{order_id}/messages/{message_id}", summary="O'z xabarini tahrirlash")
async def edit_message(
    order_id: int,
    message_id: int,
    data: MessageEdit,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    conv, _ = await get_conversation_for(db, order_id, principal)
    _ensure_writable(conv)
    msg = await service.get_message(db, conv.id, message_id)
    if msg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Xabar topilmadi")
    reason = domain.can_edit(msg, principal.user_id, _now(), EDIT_WINDOW_S)
    if reason:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=reason)

    text = data.text.strip()
    if msg.kind == domain.KIND_TEXT and not text:
        raise HTTPException(422, detail="Matn bo'sh bo'lishi mumkin emas")
    if text != (msg.text or ""):
        now = utcnow()
        msg.text = text or None
        msg.edited_at = now
        msg.updated_at = now
        await db.commit()
        await db.refresh(msg, attribute_names=["media", "reply_to"])
        out = service.message_out(msg, order_id)
        await _broadcast(
            conv, {"type": "message.edited", "order_id": order_id, "message": out.model_dump(mode="json")}
        )
        return out
    return service.message_out(msg, order_id)


@router.delete("/orders/{order_id}/messages/{message_id}", summary="O'z xabarini o'chirish")
async def delete_message(
    order_id: int,
    message_id: int,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    conv, _ = await get_conversation_for(db, order_id, principal)
    _ensure_writable(conv)
    msg = await service.get_message(db, conv.id, message_id)
    if msg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Xabar topilmadi")
    reason = domain.can_delete(msg, principal.user_id)
    if reason:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=reason)

    # Ikkala tomondan o'chiriladi (Telegram'dagi "hamma uchun o'chirish"). Matn va
    # fayl haqiqatan yo'q qilinadi — faqat "o'chirilgan xabar" izi qoladi.
    now = utcnow()
    media = msg.media
    msg.text = None
    msg.lat = None
    msg.lon = None
    msg.media_id = None
    msg.deleted_at = now
    msg.updated_at = now
    if media is not None:
        await db.delete(media)
    await db.commit()
    if media is not None:
        storage = get_storage()
        for key in (media.storage_key, media.thumb_key):
            if key:
                try:
                    await storage.delete(key)
                except Exception:
                    logger.exception("Media faylini o'chirib bo'lmadi: %s", key)

    await db.refresh(msg, attribute_names=["media", "reply_to"])
    out = service.message_out(msg, order_id)
    await _broadcast(
        conv, {"type": "message.edited", "order_id": order_id, "message": out.model_dump(mode="json")}
    )
    return out


@router.post("/orders/{order_id}/read", summary="O'qilgan belgisi (✓✓)")
async def mark_read(
    order_id: int,
    data: ReadRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    conv, _ = await get_conversation_for(db, order_id, principal)
    # Hali mavjud bo'lmagan id bilan belgini "kelajakka" surib qo'yib bo'lmasin.
    target = min(data.last_read_message_id, await service.max_message_id(db, conv.id))
    marks = await service.get_read_marks(db, conv.id)
    before = marks.get(principal.user_id, 0)
    value = await service.advance_read_mark(db, conv.id, principal.user_id, target)
    await db.commit()
    if value > before:
        await _broadcast(
            conv,
            {
                "type": "message.read",
                "order_id": order_id,
                "user_id": principal.user_id,
                "last_read_message_id": value,
            },
        )
    unread = await service.unread_count(db, conv.id, principal.user_id, value)
    return {"order_id": order_id, "last_read_message_id": value, "unread_count": unread}


# --- Media ------------------------------------------------------------------------

_READ_CHUNK = 1024 * 1024


async def _read_limited(upload: UploadFile, limit: int) -> bytes:
    """Faylni chegaradan oshmasdan o'qiydi — 2 GB yuborilsa ham xotira to'lmasin."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(_READ_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Fayl juda katta (ruxsat: {limit // (1024 * 1024)} MB gacha)",
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/orders/{order_id}/media", status_code=status.HTTP_201_CREATED, summary="Fayl yuklash")
async def upload_media(
    order_id: int,
    kind: str = Form(...),
    file: UploadFile = File(...),
    duration_s: Optional[float] = Form(None),
    thumb: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Ikki bosqichli yuborish: avval fayl (bu yerda, progress ko'rsatish mumkin),
    keyin `POST /messages` da `media_id`. Fayl turi BAYTLARDAN aniqlanadi."""
    conv, _ = await get_conversation_for(db, order_id, principal)
    _ensure_writable(conv)

    if kind not in domain.MEDIA_KINDS:
        raise HTTPException(422, detail=f"Noma'lum media turi: {kind}")

    data = await _read_limited(file, MAX_BYTES[kind])
    if not data:
        raise HTTPException(422, detail="Fayl bo'sh")
    try:
        mime = resolve_mime(kind, data[:64])
    except MimeRejected as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)) from exc

    if kind == domain.KIND_VOICE:
        if duration_s is None or duration_s <= 0:
            raise HTTPException(422, detail="Ovoz davomiyligi kerak")
        # Yozuvchi 5:00 da to'xtatadi; bir-ikki soniya — taymer/kodlash farqi uchun.
        if duration_s > MAX_VOICE_SECONDS + 2:
            raise HTTPException(
                422, detail="Ovozli xabar 5 daqiqadan oshmasligi kerak"
            )

    media_id = uuid.uuid4().hex
    base_key = f"{conv.id}/{media_id}"
    storage_key = f"{base_key}.{EXTENSIONS.get(mime, 'bin')}"

    thumb_obj = None
    if kind == domain.KIND_PHOTO:
        thumb_obj = await asyncio.to_thread(make_thumbnail, data, THUMB_MAX_PX)
    elif kind == domain.KIND_VIDEO and thumb is not None:
        thumb_bytes = await _read_limited(thumb, 2 * 1024 * 1024)
        if sniff_mime(thumb_bytes[:64]) in {"image/jpeg", "image/png", "image/webp"}:
            thumb_obj = await asyncio.to_thread(make_thumbnail, thumb_bytes, THUMB_MAX_PX)

    storage = get_storage()
    await storage.save(storage_key, data)
    thumb_key = None
    if thumb_obj is not None:
        thumb_key = f"{base_key}_thumb.jpg"
        await storage.save(thumb_key, thumb_obj.data)

    original_name = None
    if kind == domain.KIND_DOCUMENT and file.filename:
        original_name = file.filename.replace("/", "_").replace("\\", "_")[:255]

    media = Media(
        id=media_id,
        conversation_id=conv.id,
        uploader_user_id=principal.user_id,
        kind=kind,
        mime=mime,
        size_bytes=len(data),
        storage_key=storage_key,
        thumb_key=thumb_key,
        width=thumb_obj.width if thumb_obj else None,
        height=thumb_obj.height if thumb_obj else None,
        duration_s=round(duration_s, 1) if duration_s else None,
        original_name=original_name,
    )
    db.add(media)
    await db.commit()
    return service.media_out(media)


@router.get("/media/{media_id}", summary="Faylni olish (imzolangan havola)", include_in_schema=False)
async def get_media(
    media_id: str,
    v: str = Query("orig"),
    exp: int = Query(...),
    sig: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Avtorizatsiyasiz — kirish huquqi imzoda (`media_urls`). `<img>`/`<video>`
    sarlavha yubora olmaydi. FileResponse Range so'rovlarini qo'llaydi — iOS
    Safari video'ni faqat Range bilan o'ynatadi."""
    if not media_urls.verify(media_id, v, exp, sig):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Havola yaroqsiz yoki muddati o'tgan")
    media = await db.get(Media, media_id)
    if media is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Fayl topilmadi")
    key = media.thumb_key if v == "thumb" else media.storage_key
    path = get_storage().local_path(key) if key else None
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Fayl topilmadi")
    mime = "image/jpeg" if v == "thumb" else media.mime
    headers = {
        "Cache-Control": "private, max-age=86400, immutable",
        "X-Content-Type-Options": "nosniff",
    }
    return FileResponse(
        path,
        media_type=mime,
        headers=headers,
        filename=media.original_name if media.kind == domain.KIND_DOCUMENT else None,
        content_disposition_type="inline",
    )

