"""Xodimlarga (admin + menejer) yuboriladigan xabarlar uchun qabul qiluvchilar."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.config import ADMIN_IDS
from users.models import User, UserRole


async def staff_ids(db: AsyncSession) -> set[int]:
    """Adminlar (`ADMIN` env) + faol menejerlarning Telegram id'lari."""
    result = await db.execute(
        select(User.id).where(User.role == UserRole.MANAGER, User.is_active.is_(True))
    )
    return set(ADMIN_IDS) | {int(uid) for uid in result.scalars().all()}
