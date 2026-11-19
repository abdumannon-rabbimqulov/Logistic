"""Imzolangan, muddatli media havolalari.

Nega token emas, imzo: `<img src>` / `<video src>` / `<audio src>` sarlavha
(Authorization) yubora olmaydi, JWT'ni URL'ga qo'yish esa uni loglar va
Referer orqali oshkor qiladi. Shuning uchun xabar ro'yxatini OLGAN ishtirokchiga
server HMAC bilan imzolangan qisqa muddatli URL beradi:

    /chat/media/<media_id>?v=orig|thumb&exp=<unix>&sig=<hex>

`exp` soat chegarasiga yaxlitlanadi — bir soat ichida URL bir xil bo'ladi va
brauzer keshi ishlaydi (har so'rovda yangi URL bo'lsa video qayta yuklanardi).
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Optional

from chat_service.config import MEDIA_SIGNING_KEY, MEDIA_URL_TTL_S

VARIANTS = ("orig", "thumb")
URL_PREFIX = "/chat/media"


def _signature(media_id: str, variant: str, exp: int) -> str:
    msg = f"{media_id}:{variant}:{exp}".encode()
    return hmac.new(MEDIA_SIGNING_KEY.encode(), msg, hashlib.sha256).hexdigest()[:32]


def signed_url(media_id: str, variant: str = "orig", *, now: Optional[float] = None) -> str:
    now = time.time() if now is None else now
    exp = (int(now) // 3600 + 1) * 3600 + MEDIA_URL_TTL_S
    sig = _signature(media_id, variant, exp)
    return f"{URL_PREFIX}/{media_id}?v={variant}&exp={exp}&sig={sig}"


def verify(media_id: str, variant: str, exp: int, sig: str, *, now: Optional[float] = None) -> bool:
    now = time.time() if now is None else now
    if variant not in VARIANTS or exp < now:
        return False
    return hmac.compare_digest(_signature(media_id, variant, exp), sig)
