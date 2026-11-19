"""Yordam (Support) xizmati endpointlari.

Har foydalanuvchiga BITTA chat (`models.SupportTicket`, `user_id` yagona) — barcha
savollar shu yerda. Chat birinchi xabar bilan yaratiladi va hech qachon yopilmaydi;
holat (yangi / ishlanmoqda / hal qilindi) faqat xodimlarning ish navbati uchun.

Foydalanuvchi uchun (o'z chati):
    GET  /support/conversation              — chat (+ oxirgi xabarlar) yoki null; o'qildi
    GET  /support/conversation/messages     — eski xabarlar (`before_id`)
    POST /support/conversation/messages     — matn (`order_id` ixtiyoriy)
    POST /support/conversation/attachments  — rasm/video/hujjat
    POST /support/conversation/read
    WS   /support/ws                        — hodisalar + matn yuborish (`message.send`)

Xodim uchun (barcha chatlar) — `/support/tickets/...`: ro'yxat, ochish, javob,
holat, o'ziga olish. Egasi ham o'z chatini shu yo'llar bilan ocha oladi (eski
ilova versiyalari uchun); `POST /support/tickets` endi yangi murojaat ochmaydi —
mavzu va matnni chatga xabar qilib qo'shadi.

Yozish chat qatorini `SELECT ... FOR UPDATE` bilan qulflab bajariladi (poyga yo'q).
Menejer bu yerda ham hech qanday moliyaviy ma'lumot ko'rmaydi: bu bazada narx,
balans yoki komissiya umuman saqlanmaydi (`support_service/models.py`).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Literal, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from support_service import core_client, crud, kv, mime, queue, ratelimit, realtime, rules, schemas, storage
from support_service.auth import Principal, authenticate_token, get_principal, require_staff
from support_service.config import (
    MAX_DOCUMENT_BYTES,
    MAX_IMAGE_BYTES,
    MAX_VIDEO_BYTES,
    USER_STATUS_CACHE_SECONDS,
)
from support_service.db import async_session, get_db
from support_service.models import (
    AttachmentKind,
    SupportAttachment,
    SupportMessage,
    SupportTicket,
    TicketStatus,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/support", tags=["Yordam xizmati"])

_MAX_BYTES_BY_KIND = {
    AttachmentKind.IMAGE: MAX_IMAGE_BYTES,
    AttachmentKind.VIDEO: MAX_VIDEO_BYTES,
    AttachmentKind.DOCUMENT: MAX_DOCUMENT_BYTES,
}
_MAX_UPLOAD_BYTES = max(_MAX_BYTES_BY_KIND.values())


# ─── Yordamchilar ────────────────────────────────────────────────────────────


def _not_found() -> HTTPException:
    # Topilmagan va begona chat uchun bir xil 404: 403 qaytarilsa, begona odam
    # ID larni sinab ko'rib qaysi chat mavjudligini aniqlab olardi.
    return HTTPException(status.HTTP_404_NOT_FOUND, detail="Chat topilmadi")


def _check_access(ticket: Optional[SupportTicket], principal: Principal) -> SupportTicket:
    if ticket is None:
        raise _not_found()
    if not principal.is_staff and ticket.user_id != principal.user_id:
        raise _not_found()
    return ticket


async def _load_ticket(
    db: AsyncSession, ticket_id: int, principal: Principal, *, for_update: bool = False
) -> SupportTicket:
    ticket = await crud.get_ticket(db, ticket_id, for_update=for_update)
    return _check_access(ticket, principal)


def _as_staff(ticket: SupportTicket, principal: Principal) -> bool:
    """O'qilmaganlar qaysi tomondan hisoblanadi: xodim o'z chatida — egasi sifatida."""
    return principal.is_staff and ticket.user_id != principal.user_id


def _allowed(ticket: SupportTicket, principal: Principal) -> list[TicketStatus]:
    return sorted(
        rules.allowed_transitions(ticket.status, is_staff=_as_staff(ticket, principal)),
        key=lambda s: list(TicketStatus).index(s),
    )


async def _summary(
    db: AsyncSession, ticket: SupportTicket, principal: Principal
) -> schemas.TicketListItem:
    staff = _as_staff(ticket, principal)
    unread = await crud.unread_counts(db, [ticket.id], staff=staff)
    last = await crud.last_messages(db, [ticket.id])
    return schemas.ticket_out(
        ticket,
        unread_count=unread.get(ticket.id, 0),
        last_message=last.get(ticket.id),
        allowed=_allowed(ticket, principal),
    )


def _public_ticket(ticket: SupportTicket, last: Optional[SupportMessage] = None) -> dict:
    """WS uchun: ko'ruvchiga bog'liq maydonlarsiz (unread/allowed) qisqa ko'rinish."""
    return schemas.ticket_out(ticket, last_message=last).model_dump(
        mode="json", exclude={"unread_count", "allowed_statuses"}
    )


async def _detail(
    db: AsyncSession, ticket: SupportTicket, principal: Principal, *, messages_limit: int
) -> schemas.TicketDetail:
    summary = await _summary(db, ticket, principal)
    messages, has_more = await crud.list_messages(db, ticket.id, limit=messages_limit)
    return schemas.TicketDetail(
        **summary.model_dump(),
        body=ticket.body,
        messages=[schemas.message_out(m) for m in messages],
        has_more_messages=has_more,
    )


async def _check_order(principal: Principal, order_id: Optional[int]) -> None:
    """Xabar bog'lanayotgan buyurtma foydalanuvchiniki ekanini core'da tekshiradi.

    Aks holda begona buyurtmani chatga bog'lab, uning holat hodisalarini ko'rish mumkin bo'lardi.
    """
    if order_id is None or principal.is_staff:
        return
    try:
        allowed = await core_client.user_can_access_order(principal.token, order_id)
    except core_client.CoreUnavailable as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Buyurtmani tekshirib bo'lmadi — birozdan keyin urinib ko'ring.",
        ) from exc
    except core_client.CoreUnauthorized as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Qayta kiring") from exc
    if not allowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Buyurtma topilmadi yoki sizga tegishli emas")


# Bir xil `client_id` bilan qayta kelgan xabar shu muddat ichida takror yozilmaydi.
CLIENT_ID_TTL_SECONDS = 600


def _client_key(principal: Principal, client_id: str) -> str:
    return f"support:cid:{principal.user_id}:{client_id}"


async def _already_posted(
    db: AsyncSession, principal: Principal, client_id: Optional[str]
) -> Optional[schemas.MessageCreated]:
    """Shu `client_id` bilan xabar allaqachon yozilganmi (WS javobi yetmay, REST bilan qayta)."""
    if not client_id:
        return None
    message_id = await kv.get_kv().get(_client_key(principal, client_id))
    if not message_id:
        return None
    message = await db.get(SupportMessage, int(message_id))
    if message is None or message.author_user_id != principal.user_id:
        return None
    ticket = await crud.get_ticket(db, message.ticket_id)
    summary = await _summary(db, ticket, principal)
    return schemas.MessageCreated(**schemas.message_out(message).model_dump(), ticket=summary)


async def _post_message(
    db: AsyncSession,
    principal: Principal,
    *,
    ticket_id: Optional[int],
    body: str,
    order_id: Optional[int] = None,
    attachment: Optional[SupportAttachment] = None,
    client_id: Optional[str] = None,
) -> schemas.MessageCreated:
    """Xabar yozishning yagona yo'li (REST, biriktirma va WS uchun).

    `ticket_id=None` — o'z chati (birinchi xabarda yaratiladi). Rate limit chaqiruvchida.
    `client_id` — takroriy yuborishdan himoya (`_already_posted`).
    """
    duplicate = await _already_posted(db, principal, client_id)
    if duplicate is not None:
        return duplicate
    await _check_order(principal, order_id)
    created = False
    if ticket_id is None:
        ticket, created = await crud.ensure_conversation(
            db, user_id=principal.user_id, user_role=principal.role, user_name=principal.name
        )
    else:
        ticket = await _load_ticket(db, ticket_id, principal, for_update=True)
    old_status = ticket.status
    message = await crud.add_message(
        db,
        ticket,
        body,
        author_user_id=principal.user_id,
        author_role=principal.role,
        author_name=principal.name,
        is_staff=_as_staff(ticket, principal),
        attachments=[attachment] if attachment is not None else (),
        order_id=order_id,
    )
    if client_id:
        await kv.get_kv().set(_client_key(principal, client_id), str(message.id), CLIENT_ID_TTL_SECONDS)
    return await _after_message(db, ticket, message, principal, created=created, old_status=old_status)


async def _after_message(
    db: AsyncSession,
    ticket: SupportTicket,
    message: SupportMessage,
    principal: Principal,
    *,
    created: bool = False,
    old_status: Optional[TicketStatus] = None,
) -> schemas.MessageCreated:
    """Xabar yozilgandan keyingi umumiy qadamlar: hodisalar va javob tanasi."""
    message_json = schemas.message_out(message)
    public = _public_ticket(ticket, message)
    if created:
        # Xodimlar ro'yxatida yangi chat paydo bo'lsin.
        await realtime.publish("ticket.created", {"ticket": public}, user_id=ticket.user_id)
    await realtime.publish(
        "message.created",
        {"ticket_id": ticket.id, "message": message_json.model_dump(mode="json"), "ticket": public},
        user_id=ticket.user_id,
    )

    if created:
        # Hodisa: `notification_service` xodimlarga "yangi chat" va egasiga "qabul qilindi"
        # xabarini yuboradi. Birinchi xabar uchun "javob" hodisasi alohida yuborilmaydi.
        await queue.publish_event(
            queue.EVENT_SUPPORT_TICKET_CREATED,
            {
                "ticket_id": ticket.id,
                "user_id": ticket.user_id,
                "user_role": ticket.user_role,
                "user_name": ticket.user_name,
                "order_id": message.order_id,
                "subject": ticket.subject,
                "body": message.body or ("📎 Biriktirma" if message.attachments else ""),
                "priority": ticket.priority.value,
            },
        )
    else:
        await queue.publish_event(
            queue.EVENT_SUPPORT_TICKET_REPLIED,
            {
                "ticket_id": ticket.id,
                # Chat EGASI — javobni kimga yetkazishni iste'molchi shundan biladi
                # (`notification_service/handlers/support.py`). Muallif bilan aralashmasin.
                "ticket_user_id": ticket.user_id,
                "ticket_user_name": ticket.user_name,
                "assigned_to": ticket.assigned_to,
                "subject": ticket.subject,
                "message_id": message.id,
                "author_user_id": message.author_user_id,
                "author_role": message.author_role,
                "author_name": message.author_name,
                "message": message.body,
                "attachments": len(message.attachments),
                "order_id": message.order_id or ticket.order_id,
                # Egasi "hal qilingan" chatga yozdi — chat qayta ochildi.
                "reopened": old_status is not None and old_status != ticket.status
                and ticket.status == TicketStatus.OPEN,
            },
        )
    summary = await _summary(db, ticket, principal)
    return schemas.MessageCreated(**message_json.model_dump(), ticket=summary)


_UNSAFE_NAME = re.compile(r"[^\w.\- ()\[\]]+", re.UNICODE)


def _safe_filename(raw: Optional[str], ext: str) -> str:
    name = os.path.basename((raw or "").replace("\\", "/")).strip()
    name = _UNSAFE_NAME.sub("_", name)[:200].strip("._ ")
    stem = os.path.splitext(name)[0] or "fayl"
    # Kengaytma DOIM aniqlangan turdan: `virus.exe` → `virus.pdf` emas, baribir
    # `.pdf` bilan saqlanadi, chunki ichi PDF ekani tekshirilgan.
    return f"{stem}{ext}"


async def _post_attachment(
    db: AsyncSession,
    principal: Principal,
    *,
    ticket_id: Optional[int],
    file: UploadFile,
    body: str,
    order_id: Optional[int],
) -> schemas.MessageCreated:
    await ratelimit.check_message(principal.user_id, is_staff=principal.is_staff)
    if ticket_id is not None:
        # Avval kirish huquqi (qulfsiz) — begona chatga fayl yozilmasin.
        await _load_ticket(db, ticket_id, principal)
        await db.commit()  # o'qish tranzaksiyasini yopamiz; qulf fayl saqlangach olinadi

    data = await file.read(_MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Fayl bo'sh")
    sniffed = mime.sniff(data)
    if sniffed is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Bu turdagi fayl qabul qilinmaydi. Rasm (JPG, PNG, WEBP, HEIC), video (MP4, MOV, "
            "WEBM) yoki hujjat (PDF, DOCX, XLSX) yuboring.",
        )
    limit = _MAX_BYTES_BY_KIND[sniffed.kind]
    if len(data) > limit:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Fayl juda katta — ko'pi bilan {limit // (1024 * 1024)} MB.",
        )

    store = storage.get_storage()
    key = storage.new_key("support", sniffed.ext)
    await store.save(key, data)
    try:
        attachment = SupportAttachment(
            storage_key=key,
            filename=_safe_filename(file.filename, sniffed.ext),
            content_type=sniffed.content_type,
            kind=sniffed.kind,
            size=len(data),
        )
        return await _post_message(
            db, principal, ticket_id=ticket_id, body=body.strip(), order_id=order_id, attachment=attachment
        )
    except BaseException:
        await store.delete(key)
        raise


# ─── Foydalanuvchining o'z chati ─────────────────────────────────────────────


@router.get(
    "/conversation",
    response_model=schemas.ConversationResponse,
    summary="O'z yordam chatim (oxirgi xabarlar bilan); o'qildi deb belgilaydi",
)
async def get_conversation(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    messages_limit: int = Query(50, ge=1, le=200),
):
    ticket = await crud.get_conversation(db, principal.user_id)
    if ticket is None:
        return schemas.ConversationResponse(conversation=None)
    await crud.mark_read(db, ticket, staff=False)
    return schemas.ConversationResponse(
        conversation=await _detail(db, ticket, principal, messages_limit=messages_limit)
    )


@router.get(
    "/conversation/messages",
    response_model=schemas.MessagePage,
    summary="O'z chatimdagi eski xabarlar (`before_id` dan oldingilari)",
)
async def list_conversation_messages(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    before_id: Optional[int] = Query(None, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    ticket = await crud.get_conversation(db, principal.user_id)
    if ticket is None:
        return schemas.MessagePage(items=[], has_more=False)
    messages, has_more = await crud.list_messages(db, ticket.id, before_id=before_id, limit=limit)
    return schemas.MessagePage(items=[schemas.message_out(m) for m in messages], has_more=has_more)


@router.post(
    "/conversation/messages",
    response_model=schemas.MessageCreated,
    status_code=status.HTTP_201_CREATED,
    summary="O'z chatimga yozish (birinchi xabar chatni yaratadi)",
)
async def post_conversation_message(
    data: schemas.MessageCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    await ratelimit.check_message(principal.user_id, is_staff=principal.is_staff)
    return await _post_message(
        db, principal, ticket_id=None, body=data.body, order_id=data.order_id, client_id=data.client_id
    )


@router.post(
    "/conversation/attachments",
    response_model=schemas.MessageCreated,
    status_code=status.HTTP_201_CREATED,
    summary="O'z chatimga rasm/video/hujjat yuborish (ixtiyoriy izoh bilan)",
)
async def post_conversation_attachment(
    file: UploadFile = File(...),
    body: str = Form("", max_length=5000),
    order_id: Optional[int] = Form(None, gt=0),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    return await _post_attachment(db, principal, ticket_id=None, file=file, body=body, order_id=order_id)


@router.post(
    "/conversation/read",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="O'z chatimni o'qildi deb belgilash (ochiq chatga WS orqali javob kelganda)",
)
async def mark_conversation_read(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    ticket = await crud.get_conversation(db, principal.user_id)
    if ticket is not None:
        await crud.mark_read(db, ticket, staff=False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─── Chatlar (xodim; egasi — o'zinikini) ─────────────────────────────────────


@router.post(
    "/tickets",
    response_model=schemas.TicketDetail,
    status_code=status.HTTP_201_CREATED,
    summary="[Eski] Murojaat — endi o'z chatimga xabar sifatida qo'shiladi",
)
async def create_ticket(
    data: schemas.TicketCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    await ratelimit.check_ticket(principal.user_id)
    created = await _post_message(
        db,
        principal,
        ticket_id=None,
        body=f"📌 {data.subject.strip()}\n{data.body.strip()}",
        order_id=data.order_id,
    )
    ticket = await crud.get_ticket(db, created.ticket_id)
    return await _detail(db, ticket, principal, messages_limit=50)


@router.get(
    "/tickets",
    response_model=schemas.TicketPage,
    summary="Chatlar ro'yxati (xodim uchun — hammasi; egasi uchun — o'zinikini)",
)
async def list_tickets(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    ticket_status: Optional[TicketStatus] = Query(None, alias="status"),
    order_id: Optional[int] = Query(None),
    mine: bool = Query(False, description="Xodim uchun: faqat o'z chatim"),
    assigned: Optional[Literal["me", "none"]] = Query(
        None, description="Xodim uchun: `me` — menga biriktirilgan, `none` — hech kimga"
    ),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    # Oddiy foydalanuvchi uchun filtr majburiy — faqat o'z chatini ko'radi.
    own_only = mine or not principal.is_staff
    items, total = await crud.list_tickets(
        db,
        user_id=principal.user_id if own_only else None,
        status=ticket_status,
        order_id=order_id,
        assigned_to=principal.user_id if (assigned == "me" and principal.is_staff) else None,
        unassigned=assigned == "none" and principal.is_staff,
        limit=limit,
        offset=offset,
    )

    ids = [t.id for t in items]
    own_ids = [t.id for t in items if not _as_staff(t, principal)]
    other_ids = [t.id for t in items if _as_staff(t, principal)]
    unread = await crud.unread_counts(db, own_ids, staff=False)
    unread.update(await crud.unread_counts(db, other_ids, staff=True))
    last = await crud.last_messages(db, ids)

    return schemas.TicketPage(
        items=[
            schemas.ticket_out(
                t,
                unread_count=unread.get(t.id, 0),
                last_message=last.get(t.id),
                allowed=_allowed(t, principal),
            )
            for t in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/unread",
    response_model=schemas.UnreadSummary,
    summary="O'qilmaganlar soni (qo'ng'iroq belgisi uchun)",
)
async def unread_summary(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    as_staff: bool = Query(False, description="Xodim uchun: ish navbatidagi o'qilmaganlar"),
):
    staff = as_staff and principal.is_staff
    tickets, messages = await crud.unread_summary(
        db, user_id=None if staff else principal.user_id, staff=staff
    )
    return schemas.UnreadSummary(tickets=tickets, messages=messages)


@router.get(
    "/tickets/{ticket_id}",
    response_model=schemas.TicketDetail,
    summary="Chat (oxirgi xabarlar bilan); o'qildi deb belgilaydi",
)
async def get_ticket(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    messages_limit: int = Query(50, ge=1, le=200),
):
    ticket = await _load_ticket(db, ticket_id, principal)
    await crud.mark_read(db, ticket, staff=_as_staff(ticket, principal))
    return await _detail(db, ticket, principal, messages_limit=messages_limit)


@router.get(
    "/tickets/{ticket_id}/messages",
    response_model=schemas.MessagePage,
    summary="Eski xabarlar (sahifalab, `before_id` dan oldingilari)",
)
async def list_messages(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    before_id: Optional[int] = Query(None, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    await _load_ticket(db, ticket_id, principal)
    messages, has_more = await crud.list_messages(db, ticket_id, before_id=before_id, limit=limit)
    return schemas.MessagePage(items=[schemas.message_out(m) for m in messages], has_more=has_more)


@router.post(
    "/tickets/{ticket_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="O'qildi deb belgilash (ochiq chatga WS orqali xabar kelganda)",
)
async def mark_read(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    ticket = await _load_ticket(db, ticket_id, principal)
    await crud.mark_read(db, ticket, staff=_as_staff(ticket, principal))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/tickets/{ticket_id}/messages",
    response_model=schemas.MessageCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Chatga yozish",
)
async def add_message(
    ticket_id: int,
    data: schemas.MessageCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    await ratelimit.check_message(principal.user_id, is_staff=principal.is_staff)
    return await _post_message(
        db, principal, ticket_id=ticket_id, body=data.body, order_id=data.order_id, client_id=data.client_id
    )


@router.post(
    "/tickets/{ticket_id}/attachments",
    response_model=schemas.MessageCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Rasm/video/hujjat yuborish (ixtiyoriy izoh bilan)",
)
async def upload_attachment(
    ticket_id: int,
    file: UploadFile = File(...),
    body: str = Form("", max_length=5000),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    return await _post_attachment(db, principal, ticket_id=ticket_id, file=file, body=body, order_id=None)


@router.patch(
    "/tickets/{ticket_id}/status",
    response_model=schemas.TicketListItem,
    summary="Chat holatini o'zgartirish (faqat xodim)",
)
async def update_status(
    ticket_id: int,
    data: schemas.TicketStatusUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    ticket = await _load_ticket(db, ticket_id, principal, for_update=True)
    old_status = ticket.status

    if data.status == old_status:
        # Bir xil holatni qayta tanlash — no-op, hodisa ham yo'q. `commit` (rollback
        # emas): qulfni bo'shatadi, lekin yuklangan obyektni eskirgan qilmaydi.
        await db.commit()
        return await _summary(db, ticket, principal)

    if not rules.can_transition(old_status, data.status, is_staff=_as_staff(ticket, principal)):
        if not _as_staff(ticket, principal):
            detail = "Chat holatini faqat yordam xizmati o'zgartiradi."
        else:
            detail = "Bu holatga o'tkazib bo'lmaydi."
        raise HTTPException(status.HTTP_409_CONFLICT, detail=detail)

    ticket = await crud.set_status(db, ticket, data.status)

    await realtime.publish("ticket.updated", {"ticket": _public_ticket(ticket)}, user_id=ticket.user_id)
    await queue.publish_event(
        queue.EVENT_SUPPORT_TICKET_STATUS_CHANGED,
        {
            "ticket_id": ticket.id,
            "ticket_user_id": ticket.user_id,
            "old_status": old_status.value,
            "new_status": ticket.status.value,
            "subject": ticket.subject,
            "order_id": ticket.order_id,
            "changed_by_user_id": principal.user_id,
            "changed_by_role": principal.role,
        },
    )
    return await _summary(db, ticket, principal)


@router.post(
    "/tickets/{ticket_id}/assign",
    response_model=schemas.TicketListItem,
    summary="Chatni o'zimga olish (xodim)",
)
async def assign_to_me(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_staff),
):
    ticket = await _load_ticket(db, ticket_id, principal, for_update=True)
    ticket = await crud.assign(db, ticket, staff_id=principal.user_id, staff_name=principal.name)
    await realtime.publish("ticket.updated", {"ticket": _public_ticket(ticket)}, user_id=None)
    return await _summary(db, ticket, principal)


@router.delete(
    "/tickets/{ticket_id}/assign",
    response_model=schemas.TicketListItem,
    summary="Chatni bo'shatish (xodim)",
)
async def unassign(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_staff),
):
    ticket = await _load_ticket(db, ticket_id, principal, for_update=True)
    ticket = await crud.assign(db, ticket, staff_id=None, staff_name=None)
    await realtime.publish("ticket.updated", {"ticket": _public_ticket(ticket)}, user_id=None)
    return await _summary(db, ticket, principal)


# ─── Fayllar ─────────────────────────────────────────────────────────────────


@router.get("/files/{attachment_id}", summary="Biriktirma (imzolangan havola orqali)")
async def get_file(
    attachment_id: int,
    exp: int = Query(...),
    sig: str = Query(..., max_length=64),
    db: AsyncSession = Depends(get_db),
):
    if not storage.verify_signature(schemas.file_resource(attachment_id), exp, sig):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Havola yaroqsiz yoki muddati o'tgan")
    attachment = await db.get(SupportAttachment, attachment_id)
    path = storage.get_storage().local_path(attachment.storage_key) if attachment else None
    if attachment is None or path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Fayl topilmadi")

    inline = attachment.kind in (AttachmentKind.IMAGE, AttachmentKind.VIDEO)
    return FileResponse(
        path,
        media_type=attachment.content_type,
        filename=attachment.filename,
        content_disposition_type="inline" if inline else "attachment",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": f"private, max-age={max(0, exp - int(time.time()))}",
        },
    )


# ─── Real vaqt ───────────────────────────────────────────────────────────────

WS_HEARTBEAT_SECONDS = 25.0


async def _ws_send_message(principal: Principal, raw: dict[str, Any]) -> dict[str, Any]:
    """WS orqali kelgan `message.send` ni bajaradi; mijozga qaytariladigan javob.

    `{"type": "message.send", "client_id": "...", "body": "...", "order_id": 12?, "ticket_id": 5?}`
    → `message.ack` (yozilgan xabar + chat) yoki `message.error` (`status`, `detail`).
    `ticket_id` faqat xodim uchun (boshqa chatga javob); egasi — o'z chatiga.
    Yozish REST bilan BIR XIL yo'ldan (`_post_message`): qoidalar, rate limit, hodisalar.
    """
    client_id = str(raw.get("client_id") or "")[:64]
    try:
        data = schemas.MessageCreate(
            body=raw.get("body") or "", order_id=raw.get("order_id"), client_id=client_id or None
        )
        ticket_id = raw.get("ticket_id")
        ticket_id = int(ticket_id) if ticket_id is not None else None
    except (ValidationError, TypeError, ValueError):
        return {"type": "message.error", "client_id": client_id, "status": 422, "detail": "Xabar noto'g'ri"}

    try:
        await ratelimit.check_message(principal.user_id, is_staff=principal.is_staff)
        async with async_session() as db:
            created = await _post_message(
                db,
                principal,
                ticket_id=ticket_id,
                body=data.body,
                order_id=data.order_id,
                client_id=data.client_id,
            )
    except HTTPException as exc:
        return {
            "type": "message.error",
            "client_id": client_id,
            "status": exc.status_code,
            "detail": exc.detail,
        }
    except Exception:  # noqa: BLE001 — ulanish uzilmasin, mijoz REST bilan qayta urinadi
        logger.exception("WS orqali xabar yozilmadi (user %s)", principal.user_id)
        return {"type": "message.error", "client_id": client_id, "status": 500, "detail": "Xabar yuborilmadi"}
    return {"type": "message.ack", "client_id": client_id, "message": created.model_dump(mode="json")}


@router.websocket("/ws")
async def support_ws(websocket: WebSocket, token: Optional[str] = Query(None)):
    """Chat WebSocket'i: hodisalar (yangi xabar, holat) va matnli xabar yuborish.

    Mijozdan: `"ping"` yoki JSON `{"type": "message.send", ...}` (`_ws_send_message`).
    Serverdan: `hello`, `ping`, `message.created`, `ticket.created`, `ticket.updated`,
    `message.ack`, `message.error`.

    Brauzer WS'ga sarlavha qo'sha olmaydi, shuning uchun token `?token=` da.
    Yopilish kodlari: 4401 — token yaroqsiz/muddati o'tgan (mijoz tokenni yangilab
    qayta ulanadi), 4403 — akkaunt bloklangan.
    """
    await websocket.accept()
    try:
        principal = await authenticate_token(token)
    except HTTPException as exc:
        await websocket.close(code=4403 if exc.status_code == 403 else 4401)
        return

    channels = [realtime.user_channel(principal.user_id)]
    if principal.is_staff:
        channels.append(realtime.STAFF_CHANNEL)
    subscription = await realtime.get_broker().subscribe(channels)
    # Ikki vazifa (hodisalar va yuborish javoblari) bir socket'ga yozadi — navbat bilan.
    send_lock = asyncio.Lock()

    async def send(payload: dict[str, Any]) -> None:
        async with send_lock:
            await websocket.send_json(payload)

    async def _read_client() -> None:
        while True:
            text = await websocket.receive_text()
            if text == "ping":
                continue
            try:
                raw = json.loads(text)
            except ValueError:
                continue
            if isinstance(raw, dict) and raw.get("type") == "message.send":
                await send(await _ws_send_message(principal, raw))

    reader = asyncio.create_task(_read_client())
    last_check = time.monotonic()
    try:
        await send({"type": "hello", "user_id": principal.user_id})
        while not reader.done():
            event = await subscription.get(timeout=WS_HEARTBEAT_SECONDS)
            if reader.done():
                break
            await send(event if event is not None else {"type": "ping"})

            if time.monotonic() - last_check >= USER_STATUS_CACHE_SECONDS:
                last_check = time.monotonic()
                try:
                    principal = await authenticate_token(token)
                except HTTPException as exc:
                    await websocket.close(code=4403 if exc.status_code == 403 else 4401)
                    return
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)
        await subscription.close()
