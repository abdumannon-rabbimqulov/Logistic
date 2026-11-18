from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Outgoing:
    """Yuboriladigan bitta Telegram xabari. Handlerlar faqat shularni QAYTARADI —
    yuborish alohida (`telegram.py`), shuning uchun handlerlar sof va testlanadi."""

    chat_id: int
    text: str
    reply_markup: Optional[dict] = None
