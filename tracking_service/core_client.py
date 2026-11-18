"""Core API'ga avtorizatsiya so'rovlari — har WebSocket ochilishida BIR marta.

Tracking servisi bazani bilmaydi: "bu token kimniki, haydovchimi, bloklanganmi,
shu buyurtmani ko'ra oladimi" degan savollarga core javob beradi.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from tracking_service.config import CORE_API_URL

logger = logging.getLogger(__name__)

_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=CORE_API_URL, timeout=5)
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def _get(path: str, token: str) -> Optional[dict[str, Any]]:
    try:
        resp = await _get_client().get(path, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        logger.warning("Core API javob bermadi (%s): %s", path, exc)
        return None
    if resp.status_code != 200:
        return None
    return resp.json()


async def driver_identity(token: str) -> Optional[dict[str, Any]]:
    """Haydovchi: driver_id, user_id, full_name, truck_number, truck_type_id. Bloklangan — None."""
    return await _get("/drivers/me/tracking-identity", token)


async def order_access(token: str, order_id: int) -> Optional[dict[str, Any]]:
    """Kuzatish huquqi bo'lsa: {order_id, driver_id, status}; aks holda None."""
    return await _get(f"/orders/{order_id}/tracking-access", token)
