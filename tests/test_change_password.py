"""`PATCH /auth/me/password` — parol o'rnatish (birinchi marta) va o'zgartirish.

Telegram orqali kirgan foydalanuvchida parol yo'q: u eski parolsiz o'rnata olishi
kerak. Parol bor bo'lsa esa eski parol majburiy — aks holda o'g'irlangan token
bilan parolni almashtirib, akkauntni egallab olish mumkin bo'lardi.

Baza kerak emas: `update_password` almashtiriladi.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from users.models import User, UserRole
from users.schemas import ChangePasswordRequest, UserRead

router_module = pytest.importorskip(
    "users.router", reason="users.router import uchun .env (BOT_TOKEN/SECRET_KEY/DB_URL) kerak"
)
from users.auth import hash_password, verify_password  # noqa: E402


@pytest.fixture
def saved(monkeypatch):
    """`update_password` chaqirilganda yangi hash shu ro'yxatga tushadi."""
    calls: list[str] = []

    async def fake_update_password(db, user, new_hash):
        calls.append(new_hash)
        user.password = new_hash
        return user

    monkeypatch.setattr(router_module, "update_password", fake_update_password)
    return calls


def _user(password: str | None) -> User:
    return User(id=1, full_name="Test", role=UserRole.SENDER, password=password)


def _call(user: User, old: str | None, new: str):
    data = ChangePasswordRequest(old_password=old, new_password=new)
    return asyncio.run(router_module.change_password(data=data, db=None, current_user=user))


def test_first_time_set_without_old_password(saved):
    user = _user(None)
    res = _call(user, None, "yangiparol1")
    assert res["detail"] == "Parol o'rnatildi."
    assert len(saved) == 1 and verify_password("yangiparol1", saved[0])


def test_change_requires_correct_old_password(saved):
    user = _user(hash_password("eskiparol1"))
    res = _call(user, "eskiparol1", "yangiparol2")
    assert res["detail"] == "Parol muvaffaqiyatli o'zgartirildi."
    assert verify_password("yangiparol2", saved[0])


@pytest.mark.parametrize("old", [None, "", "notogri123"])
def test_change_rejected_without_valid_old_password(saved, old):
    user = _user(hash_password("eskiparol1"))
    with pytest.raises(HTTPException) as exc:
        _call(user, old, "yangiparol2")
    assert exc.value.status_code == 400
    assert saved == []


def test_new_password_min_length():
    with pytest.raises(ValueError):
        ChangePasswordRequest(old_password=None, new_password="qisqa")


def test_user_read_exposes_only_has_password_flag():
    from datetime import datetime

    now = datetime.now()
    base = dict(
        id=1, username=None, full_name="T", email=None, phone_number="+998901234567",
        role=UserRole.ADMIN, language="uz", is_active=True, is_banned=False,
        balance=0, created_at=now, updated_at=now,
    )
    with_pw = UserRead.model_validate(User(**base, password=hash_password("x" * 8)))
    without_pw = UserRead.model_validate(User(**base, password=None))
    assert with_pw.has_password is True
    assert without_pw.has_password is False
    assert "password" not in with_pw.model_dump()
