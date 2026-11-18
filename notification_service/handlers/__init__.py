"""Hodisa → yuboriladigan xabarlar ro'yxati."""

from __future__ import annotations

from typing import Any

from notification_service.handlers import orders, support
from notification_service.messages import Outgoing


def route(event: str, data: dict[str, Any]) -> list[Outgoing]:
    if event.startswith("order."):
        return orders.handle(event, data)
    if event.startswith("support."):
        return support.handle(event, data)
    return []
