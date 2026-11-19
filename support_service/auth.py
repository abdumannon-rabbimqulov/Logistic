"""Autentifikatsiya: JWT mahalliy tekshiruvi + core'dan keshlangan holat.

Token asosiy ilovada (`users/auth.py`) beriladi va `SECRET_KEY` ikkala xizmatda bir
xil — imzo va muddat shu yerda tekshiriladi. Lekin token bloklangan foydalanuvchini
muddati tugaguncha kiritib yuborardi, shuning uchun foydalanuvchining faolligi va
JORIY roli core'dan (`core_client.get_user_status`, ~60 s kesh) olinadi.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from support_service import core_client
from support_service.config import ALGORITHM, SECRET_KEY, STAFF_ROLES

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user_id: int
    role: Optional[str]
    name: Optional[str] = None
    # Core'ga foydalanuvchi nomidan so'rov yuborish uchun (buyurtma egaligi).
    token: str = field(default="", repr=False)

    @property
    def is_staff(self) -> bool:
        return self.role in STAFF_ROLES


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _blocked() -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, detail="Akkaunt bloklangan yoki faol emas.")


async def authenticate_token(token: Optional[str]) -> Principal:
    """HTTP va WebSocket uchun umumiy tekshiruv."""
    if not token:
        raise _unauthorized("Avtorizatsiya tokeni yuborilmadi")

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise _unauthorized("Yaroqsiz yoki muddati o'tgan token") from exc

    # Faqat `access` token: refresh yoki parol tiklash tokeni bilan kirib bo'lmasin.
    if payload.get("type") != "access":
        raise _unauthorized("Bu token turi bilan kirish mumkin emas")

    sub = payload.get("sub")
    if not sub:
        raise _unauthorized("Token tarkibi xato")
    try:
        user_id = int(sub)
    except (TypeError, ValueError) as exc:
        raise _unauthorized("Token tarkibi xato") from exc

    role = payload.get("role")
    name: Optional[str] = None
    try:
        user_status = await core_client.get_user_status(token, user_id)
    except core_client.CoreUnauthorized as exc:
        raise _unauthorized("Foydalanuvchi topilmadi") from exc

    if user_status is not None:
        if not user_status.active:
            raise _blocked()
        # Core'dagi rol — haqiqat manbai (tokendagi claim eskirgan bo'lishi mumkin).
        role = user_status.role
        name = user_status.full_name

    return Principal(user_id=user_id, role=role, name=name, token=token)


async def get_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Principal:
    return await authenticate_token(credentials.credentials if credentials else None)


async def require_staff(principal: Principal = Depends(get_principal)) -> Principal:
    """Faqat admin yoki menejer."""
    if not principal.is_staff:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu amal faqat qo'llab-quvvatlash xodimlari (admin/menejer) uchun",
        )
    return principal
