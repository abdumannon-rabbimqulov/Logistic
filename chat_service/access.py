"""Suhbatga kirish huquqi.

Faqat ikki ishtirokchi: yuk egasi (`sender_user_id`) va biriktirilgan haydovchi
(`driver_user_id`). Begona yoki mavjud bo'lmagan suhbat uchun BIR XIL 404 —
403 qaytarilsa, buyurtma raqamlarini sinab qaysi buyurtmada chat borligini
aniqlash mumkin bo'lardi (support'dagi qoida).

Haydovchining `user_id` si: core hodisalarida hozircha faqat `driver_id`
(`drivers.id`) bor. `driver_user_id` noma'lum bo'lsa va kirayotgan odam haydovchi
rolida bo'lsa, uning O'Z tokeni bilan core'dan `GET /drivers/me` so'raymiz: javobdagi
`id` suhbatdagi `driver_id` ga teng bo'lsa — bu o'sha haydovchi, `user_id` si
saqlanadi. Bu bir martalik (keyin bazadan o'qiladi) va core'da yangi endpoint talab
qilmaydi. Core payload'ga `driver_user_id` qo'shsa, bu yo'l umuman ishlamaydi.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chat_service import domain
from chat_service.auth import Principal
from chat_service.config import CORE_API_URL
from chat_service.models import Conversation

logger = logging.getLogger(__name__)

NOT_FOUND = "Chat topilmadi"


async def fetch_core_driver_id(token: str) -> Optional[int]:
    """Core'dan joriy foydalanuvchining `drivers.id` si. Xato/haydovchi emas — `None`."""
    if not CORE_API_URL or not token:
        return None
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{CORE_API_URL}/drivers/me", headers={"Authorization": f"Bearer {token}"}
            )
        if resp.status_code != 200:
            return None
        return int(resp.json().get("id"))
    except Exception:
        logger.warning("Core'dan haydovchi profilini olib bo'lmadi", exc_info=True)
        return None


# Testlar almashtiradi.
core_driver_lookup = fetch_core_driver_id


async def get_conversation_for(
    db: AsyncSession, order_id: int, principal: Principal
) -> tuple[Conversation, str]:
    """Suhbat va foydalanuvchining roli (`sender`/`driver`). Aks holda 404."""
    conv = (
        await db.execute(select(Conversation).where(Conversation.order_id == order_id))
    ).scalar_one_or_none()
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)

    role = domain.role_of(conv, principal.user_id)
    if role is None and await _try_bind_driver(db, conv, principal):
        role = domain.ROLE_DRIVER
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    return conv, role


async def _try_bind_driver(db: AsyncSession, conv: Conversation, principal: Principal) -> bool:
    if conv.driver_user_id is not None or conv.driver_id is None:
        return False
    if principal.role != "driver" or principal.user_id == conv.sender_user_id:
        return False
    driver_id = await core_driver_lookup(principal.token)
    if driver_id is None or driver_id != conv.driver_id:
        return False
    conv.driver_user_id = principal.user_id
    await db.commit()
    logger.info("Chat #%s: haydovchi user_id=%s core orqali tasdiqlandi", conv.id, principal.user_id)
    return True
