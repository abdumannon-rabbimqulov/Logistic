"""JWT tekshiruvi — `support_service/auth.py` bilan bir xil qoida.

Token asosiy ilovada beriladi (`users/auth.py`), `SECRET_KEY` umumiy. Faqat
`type=access` tokenlar qabul qilinadi. WebSocket brauzerda sarlavha yubora
olmagani uchun u yerda token `?token=` orqali keladi — tekshiruv o'sha funksiya.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from chat_service.config import ALGORITHM, SECRET_KEY

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user_id: int
    role: Optional[str]
    # Asl token — faqat core'ga haydovchini tasdiqlash so'rovi uchun (`access.py`).
    token: str = ""
    # Token muddati (unix) — WebSocket shu paytda yopiladi, mijoz yangi token bilan
    # qayta ulanadi (uzoq ochiq WS eskirgan token bilan ishlab qolmasin).
    exp: Optional[int] = None


class InvalidToken(Exception):
    pass


def principal_from_token(token: str) -> Principal:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise InvalidToken("Yaroqsiz yoki muddati o'tgan token") from exc
    if payload.get("type") != "access":
        raise InvalidToken("Bu token turi bilan kirish mumkin emas")
    sub = payload.get("sub")
    try:
        user_id = int(sub)
    except (TypeError, ValueError) as exc:
        raise InvalidToken("Token tarkibi xato") from exc
    exp = payload.get("exp")
    return Principal(
        user_id=user_id,
        role=payload.get("role"),
        token=token,
        exp=int(exp) if isinstance(exp, (int, float)) else None,
    )


async def get_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Principal:
    if credentials is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Avtorizatsiya tokeni yuborilmadi",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return principal_from_token(credentials.credentials)
    except InvalidToken as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail=str(exc), headers={"WWW-Authenticate": "Bearer"}
        ) from exc
