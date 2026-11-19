"""Oddiy fixed-window rate-limit (Redis yoki xotira — `kv.py`)."""

from __future__ import annotations

from fastapi import HTTPException, status

from support_service.config import (
    RATE_MESSAGES_PER_MINUTE,
    RATE_STAFF_MESSAGES_PER_MINUTE,
    RATE_TICKETS_PER_HOUR,
)
from support_service.kv import get_kv


async def _check(key: str, limit: int, window: int, detail: str) -> None:
    count, retry_after = await get_kv().hit(key, window)
    if count > limit:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
            headers={"Retry-After": str(retry_after)},
        )


async def check_message(user_id: int, *, is_staff: bool) -> None:
    limit = RATE_STAFF_MESSAGES_PER_MINUTE if is_staff else RATE_MESSAGES_PER_MINUTE
    await _check(
        f"support:rl:msg:{user_id}",
        limit,
        60,
        f"Juda tez yozyapsiz — daqiqasiga ko'pi bilan {limit} ta xabar. Birozdan keyin urinib ko'ring.",
    )


async def check_ticket(user_id: int) -> None:
    await _check(
        f"support:rl:ticket:{user_id}",
        RATE_TICKETS_PER_HOUR,
        3600,
        f"Bir soatda ko'pi bilan {RATE_TICKETS_PER_HOUR} ta murojaat ochish mumkin. "
        "Mavjud murojaatingizga yozing yoki keyinroq urinib ko'ring.",
    )
