#!/usr/bin/env python3
"""
Sinov (test) uchun 5 ta haydovchi va 5 ta yuk beruvchi (sender) yaratadi.

Ishlatish (lokal va prod serverda bir xil):
  docker compose exec web python scripts/seed_test_users.py
O'chirish:
  docker compose exec web python scripts/seed_test_users.py --delete

Hisoblar (parol hammasida bir xil: 1111):

  Haydovchilar  +998900000001 … +998900000005   (Telegram ID 999000001 … 999000005)
  Yuboruvchilar +998900000011 … +998900000015   (Telegram ID 999000011 … 999000015)

Skript IDEMPOTENT: qayta ishga tushirilsa dublikat yaratmaydi, mavjud yozuvlarni
kerakli holatga qaytaradi (parol, rol, tasdiqlangan hujjatlar va h.k.).

Telegram ID sifatida ataylab "soxta" diapazon (999000xxx) ishlatiladi — haqiqiy
Telegram akkauntlar bilan to'qnashmasligi uchun. Shu sababli bu hisoblarga faqat
telefon + parol orqali kiriladi (Telegram initData bilan emas).

Parol `1111` — atayin sodda. Parol uzunligi faqat parolni O'ZGARTIRISHDA (8+)
tekshiriladi, login'da emas. Prodda haqiqiy foydalanuvchilar ko'paygach
`--delete` bilan o'chirib tashlang.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from config import registry  # noqa: E402,F401  — barcha modellar (mapper) ro'yxatdan o'tsin
from config.config import async_session  # noqa: E402
from driver.models import Driver, DriverVerificationStatus, TruckType  # noqa: E402
from users.auth import hash_password  # noqa: E402
from users.models import User, UserRole  # noqa: E402
from utils.validation import normalize_phone_number  # noqa: E402

PASSWORD = "1111"
COUNT = 5


@dataclass(frozen=True)
class TestAccount:
    telegram_id: int
    phone: str
    full_name: str
    role: UserRole

    @property
    def number(self) -> int:
        return self.telegram_id % 10


DRIVERS = [
    TestAccount(999_000_000 + n, f"+99890000000{n}", f"Haydovchi {n}", UserRole.DRIVER)
    for n in range(1, COUNT + 1)
]
SENDERS = [
    TestAccount(999_000_010 + n, f"+99890000001{n}", f"Yuboruvchi {n}", UserRole.SENDER)
    for n in range(1, COUNT + 1)
]
ACCOUNTS = DRIVERS + SENDERS


async def _upsert_user(db, acc: TestAccount, password_hash: str) -> User:
    phone = normalize_phone_number(acc.phone)
    # Raqam boshqa (haqiqiy) foydalanuvchida band bo'lsa — to'xtaymiz, ustiga yozmaymiz.
    clash = await db.scalar(
        select(User).where(User.phone_number == phone, User.id != acc.telegram_id)
    )
    if clash:
        raise SystemExit(
            f"❌ {phone} raqami boshqa foydalanuvchida band (id={clash.id}, {clash.full_name})."
        )

    user = await db.get(User, acc.telegram_id)
    if user is None:
        user = User(id=acc.telegram_id)
        db.add(user)

    user.full_name = acc.full_name
    user.username = f"test_{acc.role.value}_{acc.number}"
    user.phone_number = phone
    user.password = password_hash
    user.role = acc.role
    user.language = "uz"
    user.is_active = True
    user.is_banned = False
    return user


async def _upsert_driver(db, acc: TestAccount, truck_type: TruckType) -> None:
    driver = await db.scalar(select(Driver).where(Driver.user_id == acc.telegram_id))
    if driver is None:
        driver = Driver(user_id=acc.telegram_id)
        db.add(driver)

    driver.truck_type_id = truck_type.id
    driver.truck_number = f"01T00{acc.number}TS"
    driver.truck_year = 2020
    driver.current_city = "Toshkent"
    driver.current_region = "Toshkent shahri"
    # Sinovda darhol buyurtma olishi uchun: tasdiqlangan va liniyada.
    driver.docs_verified = True
    driver.verification_status = DriverVerificationStatus.APPROVED
    driver.is_available = True
    driver.is_blocked = False
    driver.block_reason = None


async def seed() -> None:
    password_hash = hash_password(PASSWORD)  # bitta hash — 10 marta bcrypt shart emas

    async with async_session() as db:
        truck_type = await db.scalar(
            select(TruckType).where(TruckType.is_active.is_(True)).order_by(TruckType.id)
        )
        if truck_type is None:
            raise SystemExit(
                "❌ Bazada faol mashina turi (truck_type) yo'q — avval admin panelda qo'shing."
            )

        for acc in ACCOUNTS:
            await _upsert_user(db, acc, password_hash)
        await db.flush()  # drivers.user_id uchun users qatorlari mavjud bo'lsin

        for acc in DRIVERS:
            await _upsert_driver(db, acc, truck_type)

        await db.commit()

    print(f"✅ Sinov hisoblari tayyor (parol: {PASSWORD}, mashina: {truck_type.name})")
    for acc in ACCOUNTS:
        print(f"   {acc.role.value:<6}  {acc.phone}  {acc.full_name}")


async def delete() -> None:
    ids = [acc.telegram_id for acc in ACCOUNTS]
    async with async_session() as db:
        for driver in (await db.scalars(select(Driver).where(Driver.user_id.in_(ids)))).all():
            await db.delete(driver)
        for user in (await db.scalars(select(User).where(User.id.in_(ids)))).all():
            await db.delete(user)
        await db.commit()
    print(f"🗑  {len(ids)} ta sinov hisobi o'chirildi")


if __name__ == "__main__":
    asyncio.run(delete() if "--delete" in sys.argv else seed())
