"""Asosiy ilova (core) bilan ikki tor savol: "foydalanuvchi faolmi?" va
"bu buyurtma unga tegishlimi?".

Ikkalasi ham foydalanuvchining O'Z tokeni bilan so'raladi, ya'ni core o'zining
odatdagi huquq tekshiruvini qo'llaydi — support'ga maxsus ichki endpoint yoki
xizmat tokeni kerak emas, va support begona ma'lumotni ko'ra olmaydi.

Holat Redis'da `USER_STATUS_CACHE_SECONDS` (~60 s) keshlanadi: har so'rovda core'ga
borilmaydi, bloklangan foydalanuvchi esa eng ko'pi bilan shu oyna ichida chiqariladi.
Core vaqtincha javob bermasa, oxirgi ma'lum holat (`:stale`, 1 sutka) ishlatiladi;
u ham bo'lmasa — JWT tekshiruvi bilan kifoyalanamiz (fail-open), aks holda core
qayta ishga tushganda support ham butunlay to'xtab qolardi.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Optional

import httpx

from support_service.config import CORE_API_URL, CORE_TIMEOUT_SECONDS, USER_STATUS_CACHE_SECONDS
from support_service.kv import get_kv

logger = logging.getLogger(__name__)

STALE_TTL_SECONDS = 24 * 3600


class CoreUnavailable(RuntimeError):
    """Core javob bermadi yoki kutilmagan javob qaytardi."""


class CoreUnauthorized(RuntimeError):
    """Core tokenni rad etdi (foydalanuvchi o'chirilgan va h.k.)."""


@dataclass(frozen=True)
class UserStatus:
    active: bool
    role: Optional[str] = None
    full_name: Optional[str] = None


_client: Optional[httpx.AsyncClient] = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=CORE_API_URL, timeout=CORE_TIMEOUT_SECONDS)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def fetch_user_status(token: str) -> UserStatus:
    """`GET /auth/me` — core'ning `get_current_user` i bloklangan foydalanuvchini
    ham qaytaradi (403 bermaydi), shuning uchun bayroqlarni o'zimiz o'qiymiz."""
    try:
        resp = await _http().get("/auth/me", headers=_auth(token))
    except httpx.HTTPError as exc:
        raise CoreUnavailable(str(exc)) from exc
    if resp.status_code == 401:
        raise CoreUnauthorized("core tokenni rad etdi")
    if resp.status_code != 200:
        raise CoreUnavailable(f"/auth/me → {resp.status_code}")
    data = resp.json()
    return UserStatus(
        active=bool(data.get("is_active", True)) and not bool(data.get("is_banned", False)),
        role=data.get("role"),
        full_name=data.get("full_name"),
    )


def _key(user_id: int) -> str:
    return f"support:user:{user_id}"


async def invalidate_user_status(user_id: int) -> None:
    kv = get_kv()
    await kv.delete(_key(user_id))


async def get_user_status(token: str, user_id: int) -> Optional[UserStatus]:
    """Keshlangan holat. `None` — core mavjud emas va oxirgi ma'lum holat ham yo'q."""
    kv = get_kv()
    cached = await kv.get(_key(user_id))
    if cached:
        return UserStatus(**json.loads(cached))

    try:
        status = await fetch_user_status(token)
    except CoreUnavailable:
        logger.warning("Core mavjud emas — foydalanuvchi %s holati oxirgi ma'lum qiymatdan", user_id)
        stale = await kv.get(_key(user_id) + ":stale")
        return UserStatus(**json.loads(stale)) if stale else None

    payload = json.dumps(asdict(status))
    await kv.set(_key(user_id), payload, USER_STATUS_CACHE_SECONDS)
    await kv.set(_key(user_id) + ":stale", payload, STALE_TTL_SECONDS)
    return status


async def user_can_access_order(token: str, order_id: int) -> bool:
    """`GET /orders/{id}` — core egasi/haydovchi/xodimga 200, boshqalarga 403/404 beradi."""
    try:
        resp = await _http().get(f"/orders/{order_id}", headers=_auth(token))
    except httpx.HTTPError as exc:
        raise CoreUnavailable(str(exc)) from exc
    if resp.status_code == 200:
        return True
    if resp.status_code in (403, 404):
        return False
    if resp.status_code == 401:
        raise CoreUnauthorized("core tokenni rad etdi")
    raise CoreUnavailable(f"/orders/{order_id} → {resp.status_code}")
