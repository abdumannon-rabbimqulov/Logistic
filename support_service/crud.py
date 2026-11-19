from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional, Sequence

from sqlalchemy import and_, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from support_service.models import (
    CHAT_SUBJECT,
    DONE_STATUSES,
    SupportAttachment,
    SupportMessage,
    SupportTicket,
    TicketStatus,
)

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


async def get_conversation(
    db: AsyncSession, user_id: int, *, for_update: bool = False
) -> Optional[SupportTicket]:
    """Foydalanuvchining yagona chati (hali yozmagan bo'lsa — None)."""
    stmt = select(SupportTicket).where(SupportTicket.user_id == user_id)
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one_or_none()


async def ensure_conversation(
    db: AsyncSession,
    *,
    user_id: int,
    user_role: Optional[str],
    user_name: Optional[str],
) -> tuple[SupportTicket, bool]:
    """Chatni qulf bilan qaytaradi; yo'q bo'lsa yaratadi. (chat, yangi_yaratildimi).

    `INSERT ... ON CONFLICT DO NOTHING` — bir vaqtda kelgan ikki birinchi xabar
    ikkita chat yaratmaydi (`user_id` yagona), ikkinchisi mavjudini oladi.
    """
    inserted = await db.execute(
        pg_insert(SupportTicket)
        .values(
            user_id=user_id,
            user_role=user_role,
            user_name=user_name,
            subject=CHAT_SUBJECT,
            body="",
            status=TicketStatus.OPEN,
            # Egasi o'z chatini "o'qigan" — undan oldingi hech narsa o'qilmagan emas.
            user_last_read_at=func.now(),
        )
        .on_conflict_do_nothing(index_elements=[SupportTicket.user_id])
        .returning(SupportTicket.id)
    )
    created = inserted.scalar_one_or_none() is not None
    ticket = await get_conversation(db, user_id, for_update=True)
    assert ticket is not None
    # Ism/rol o'zgargan bo'lsa — xodim ro'yxatida dolzarb ko'rinsin.
    if user_name and ticket.user_name != user_name:
        ticket.user_name = user_name
    if user_role and ticket.user_role != user_role:
        ticket.user_role = user_role
    return ticket, created


async def get_ticket(
    db: AsyncSession, ticket_id: int, *, for_update: bool = False
) -> Optional[SupportTicket]:
    """`for_update=True` — qatorni tranzaksiya oxirigacha qulflaydi (`SELECT ... FOR UPDATE`).

    Javob yozish va holat o'zgartirish shu qulf ostida bajariladi: aks holda
    "ochiqmi?" tekshiruvi bilan INSERT orasida boshqa so'rov murojaatni yopib
    ulgurardi va yopilgan murojaatga xabar tushib qolardi.
    """
    stmt = select(SupportTicket).where(SupportTicket.id == ticket_id)
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def _ticket_filters(
    *,
    user_id: Optional[int],
    status: Optional[TicketStatus],
    order_id: Optional[int],
    assigned_to: Optional[int],
    unassigned: bool,
) -> list:
    filters = []
    if user_id is not None:
        filters.append(SupportTicket.user_id == user_id)
    if status is not None:
        filters.append(SupportTicket.status == status)
    if order_id is not None:
        filters.append(SupportTicket.order_id == order_id)
    if assigned_to is not None:
        filters.append(SupportTicket.assigned_to == assigned_to)
    if unassigned:
        filters.append(SupportTicket.assigned_to.is_(None))
    return filters


async def list_tickets(
    db: AsyncSession,
    *,
    user_id: Optional[int] = None,
    status: Optional[TicketStatus] = None,
    order_id: Optional[int] = None,
    assigned_to: Optional[int] = None,
    unassigned: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[SupportTicket], int]:
    """`user_id=None` — hamma murojaatlar (faqat xodimlar uchun, router tekshiradi).

    Tartib — oxirgi faollik bo'yicha: yangi javob kelgan murojaat tepaga chiqadi.
    """
    filters = _ticket_filters(
        user_id=user_id,
        status=status,
        order_id=order_id,
        assigned_to=assigned_to,
        unassigned=unassigned,
    )
    total = await db.scalar(select(func.count(SupportTicket.id)).where(*filters))
    result = await db.execute(
        select(SupportTicket)
        .where(*filters)
        .order_by(SupportTicket.last_message_at.desc(), SupportTicket.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), int(total or 0)


def _unread_condition(*, staff: bool):
    """Qarshi tomonning, oxirgi o'qishdan keyingi, tizimniki bo'lmagan xabarlari."""
    if staff:
        return and_(
            SupportMessage.author_user_id == SupportTicket.user_id,
            SupportMessage.created_at > func.coalesce(SupportTicket.staff_last_read_at, _EPOCH),
        )
    return and_(
        SupportMessage.author_user_id.is_distinct_from(SupportTicket.user_id),
        SupportMessage.created_at > func.coalesce(SupportTicket.user_last_read_at, _EPOCH),
    )


async def unread_counts(
    db: AsyncSession, ticket_ids: Iterable[int], *, staff: bool
) -> dict[int, int]:
    ids = list(ticket_ids)
    if not ids:
        return {}
    result = await db.execute(
        select(SupportMessage.ticket_id, func.count(SupportMessage.id))
        .join(SupportTicket, SupportTicket.id == SupportMessage.ticket_id)
        .where(
            SupportMessage.ticket_id.in_(ids),
            SupportMessage.is_system.is_(False),
            _unread_condition(staff=staff),
        )
        .group_by(SupportMessage.ticket_id)
    )
    # Chatda alohida "asosiy matn" yo'q — birinchi savol ham oddiy xabar, shuning uchun
    # hisob faqat xabarlardan (ilgari ochilmagan murojaatga +1 qo'shilardi).
    return {tid: int(n) for tid, n in result.all()}


async def unread_summary(
    db: AsyncSession, *, user_id: Optional[int], staff: bool
) -> tuple[int, int]:
    """(o'qilmagan xabari bor murojaatlar soni, o'qilmagan xabarlar soni).

    Xodim uchun hal qilingan chatlar hisobga olinmaydi — ular ish navbatida emas
    (foydalanuvchi yana yozsa chat qayta ochiladi va hisobga tushadi).
    """
    if staff:
        scope = [SupportTicket.status.notin_(list(DONE_STATUSES))]
    else:
        scope = [SupportTicket.user_id == user_id]

    msg_rows = await db.execute(
        select(SupportMessage.ticket_id, func.count(SupportMessage.id))
        .join(SupportTicket, SupportTicket.id == SupportMessage.ticket_id)
        .where(*scope, SupportMessage.is_system.is_(False), _unread_condition(staff=staff))
        .group_by(SupportMessage.ticket_id)
    )
    counts = {tid: int(n) for tid, n in msg_rows.all()}
    return len(counts), sum(counts.values())


async def last_messages(db: AsyncSession, ticket_ids: Iterable[int]) -> dict[int, SupportMessage]:
    ids = list(ticket_ids)
    if not ids:
        return {}
    # Vaqt bo'yicha eng oxirgisi (birlashtirilgan eski xabarlarning id'si yangi bo'lishi mumkin).
    result = await db.execute(
        select(SupportMessage)
        .where(SupportMessage.ticket_id.in_(ids))
        .distinct(SupportMessage.ticket_id)
        .order_by(SupportMessage.ticket_id, SupportMessage.created_at.desc(), SupportMessage.id.desc())
    )
    return {m.ticket_id: m for m in result.scalars().all()}


async def list_messages(
    db: AsyncSession,
    ticket_id: int,
    *,
    before_id: Optional[int] = None,
    limit: int = 50,
) -> tuple[list[SupportMessage], bool]:
    """Oxirgi `limit` ta xabar (yoki `before_id` xabaridan oldingilari), vaqt bo'yicha o'sish tartibida.

    Tartib — `(created_at, id)`: chatga birlashtirilgan eski murojaatlarning matni
    yangi id bilan, lekin asl vaqti bilan yozilgan (migratsiya 0003).
    """
    stmt = select(SupportMessage).where(SupportMessage.ticket_id == ticket_id)
    if before_id is not None:
        anchor = (
            select(SupportMessage.created_at)
            .where(SupportMessage.id == before_id, SupportMessage.ticket_id == ticket_id)
            .scalar_subquery()
        )
        stmt = stmt.where(tuple_(SupportMessage.created_at, SupportMessage.id) < tuple_(anchor, before_id))
    result = await db.execute(
        stmt.order_by(SupportMessage.created_at.desc(), SupportMessage.id.desc()).limit(limit + 1)
    )
    rows = list(result.scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    rows.reverse()
    return rows, has_more


async def add_message(
    db: AsyncSession,
    ticket: SupportTicket,
    body: str,
    *,
    author_user_id: Optional[int] = None,
    author_role: Optional[str] = None,
    author_name: Optional[str] = None,
    is_system: bool = False,
    is_staff: bool = False,
    attachments: Sequence[SupportAttachment] = (),
    order_id: Optional[int] = None,
    commit: bool = True,
) -> SupportMessage:
    """Xabar qo'shadi. Chaqiruvchi chatni qulf bilan (`for_update=True`) olgan bo'lishi kerak.

    Egasi "hal qilingan" chatga yozsa — chat qayta ochiladi (OPEN): chat yopilmaydi,
    yangi savol xodimlarning ish navbatiga qaytadi.
    """
    message = SupportMessage(
        ticket_id=ticket.id,
        author_user_id=author_user_id,
        author_role=author_role,
        author_name=author_name,
        is_system=is_system,
        body=body,
        order_id=order_id,
        attachments=list(attachments),
    )
    db.add(message)

    now = func.now()
    ticket.last_message_at = now  # `updated_at` ham onupdate orqali yangilanadi
    if order_id is not None:
        # Shu buyurtmaning holat hodisalari endi shu chatga tizim izohi bo'lib tushadi.
        ticket.order_id = order_id
    if not is_system:
        if is_staff:
            ticket.staff_last_read_at = now
            # Xodim javob yozsa murojaat avtomatik "ishlanmoqda" ga o'tadi va
            # hech kimga biriktirilmagan bo'lsa — shu xodimga.
            if ticket.status == TicketStatus.OPEN:
                ticket.status = TicketStatus.IN_PROGRESS
            if ticket.assigned_to is None:
                ticket.assigned_to = author_user_id
                ticket.assigned_name = author_name
        elif author_user_id == ticket.user_id:
            ticket.user_last_read_at = now
            if ticket.status in DONE_STATUSES:
                ticket.status = TicketStatus.OPEN

    if commit:
        await db.commit()
        await db.refresh(ticket)
        await db.refresh(message, attribute_names=["created_at"])
    return message


async def mark_read(db: AsyncSession, ticket: SupportTicket, *, staff: bool) -> None:
    """O'qildi belgisi. `updated_at` ATAYLAB o'zgartirilmaydi — bu faollik emas."""
    column = "staff_last_read_at" if staff else "user_last_read_at"
    await db.execute(
        update(SupportTicket)
        .where(SupportTicket.id == ticket.id)
        .values({column: func.now(), "updated_at": SupportTicket.updated_at})
        .execution_options(synchronize_session=False)
    )
    await db.commit()


async def set_status(db: AsyncSession, ticket: SupportTicket, new_status: TicketStatus) -> SupportTicket:
    ticket.status = new_status
    await db.commit()
    await db.refresh(ticket)
    return ticket


async def assign(
    db: AsyncSession, ticket: SupportTicket, *, staff_id: Optional[int], staff_name: Optional[str]
) -> SupportTicket:
    ticket.assigned_to = staff_id
    ticket.assigned_name = staff_name if staff_id is not None else None
    await db.commit()
    await db.refresh(ticket)
    return ticket


async def list_open_tickets_for_order(db: AsyncSession, order_id: int) -> Sequence[SupportTicket]:
    """Buyurtma hodisasi kelganda tizim izohi qo'shiladigan chatlar (qulf bilan):
    oxirgi marta shu buyurtma haqida yozilgan chatlar. Tizim izohi chatni qayta ochmaydi."""
    result = await db.execute(
        select(SupportTicket)
        .where(SupportTicket.order_id == order_id)
        .order_by(SupportTicket.id)
        .with_for_update()
    )
    return list(result.scalars().all())

