"""Tracking mikroservizi: haydovchilarning jonli GPS oqimi va senderga uzatish.

Ishga tushirish:  `uvicorn tracking_service.main:app --host 0.0.0.0 --port 8000`

Nega alohida: bu eng ko'p bir vaqtda ochiq ulanish talab qiladigan qism (har bir
liniyadagi haydovchi + har bir kuzatayotgan sender). U core'dan ajralgani uchun:
  * GPS xabarlari core'ning DB ulanishlarini band qilmaydi (ilgari har haydovchi WS
    uchun butun ulanish davomida bitta DB sessiyasi ochiq turardi);
  * alohida masshtablanadi va keyinchalik Go'ga birinchi bo'lib ko'chiriladi.

Protokol core'dagi eski endpointlar bilan BIR XIL (frontend o'zgarmaydi):
  WS {prefix}/drivers/ws/location?token=           — haydovchi GPS yuboradi
  WS {prefix}/orders/{id}/ws/driver-location?token= — sender haydovchini kuzatadi
Oxirgi nuqtani bazaga yozish — core'ning ishi (`services/live_location_sync.py`,
dispatch-worker ichida, Redis'dan davriy).
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, FastAPI, WebSocket, WebSocketDisconnect

from tracking_service import core_client, store
from tracking_service.config import API_PREFIX, LOG_LEVEL
from tracking_service.fixes import is_stale_fix, parse_fix_time

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s")
logger = logging.getLogger("tracking_service")


def _token(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    raw = raw.strip()
    return raw[7:].strip() if raw.lower().startswith("bearer ") else raw


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await core_client.close()
    await store.close()


app = FastAPI(title="Tracking service", lifespan=lifespan, docs_url=None, redoc_url=None)
router = APIRouter()


@app.get("/health")
async def health():
    await store.get_redis().ping()
    return {"status": "ok"}


@router.websocket("/drivers/ws/location")
async def driver_location_ws(websocket: WebSocket, token: Optional[str] = None):
    raw = _token(token or websocket.query_params.get("token"))
    identity = await core_client.driver_identity(raw) if raw else None
    if identity is None:
        await websocket.close(code=4401, reason="Unauthorized")
        return

    driver_id = int(identity["driver_id"])
    await websocket.accept()
    await websocket.send_json({"status": "connected", "driver_id": driver_id})
    stop_requested = False
    try:
        while True:
            data = await websocket.receive_json()
            event = data.get("event")
            if event == "stop":
                stop_requested = True
                break
            if event == "gps_lost":
                await store.mark_gps_lost(driver_id, str(data.get("reason") or "unknown")[:32])
                await websocket.send_json({"status": "acknowledged"})
                continue

            now = datetime.now(timezone.utc)
            fix_time = parse_fix_time(data.get("timestamp"), now)
            if is_stale_fix(fix_time, now):
                # Telefon keshdagi eski nuqtani yubormoqda — GPS amalda ishlamayapti.
                await websocket.send_json({"status": "stale"})
                continue
            try:
                lat, lon = float(data["latitude"]), float(data["longitude"])
            except (KeyError, TypeError, ValueError):
                await websocket.send_json({"status": "invalid"})
                continue
            accuracy = data.get("accuracy")
            payload = store.build_payload(
                identity, lat, lon, float(accuracy) if accuracy is not None else None, fix_time
            )
            await store.save_location(payload)
            await websocket.send_json({"status": "acknowledged"})
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Driver %s WS xatosi", driver_id)
        try:
            await websocket.close(code=1011, reason="Server error")
        except Exception:
            pass
    finally:
        if stop_requested:
            await store.stop(driver_id)


@router.websocket("/orders/{order_id}/ws/driver-location")
async def order_driver_location_ws(websocket: WebSocket, order_id: int, token: Optional[str] = None):
    raw = _token(token or websocket.query_params.get("token"))
    access = await core_client.order_access(raw, order_id) if raw else None
    if access is None:
        await websocket.close(code=4403)
        return

    driver_id = access.get("driver_id")
    await websocket.accept()
    if driver_id is None:
        await websocket.send_text(json.dumps({"event": "no_driver"}))
        await websocket.close(code=4404)
        return
    driver_id = int(driver_id)

    try:
        snapshot = await store.get_location(driver_id)
        await websocket.send_text(json.dumps({"event": "snapshot", "item": snapshot}))
    except Exception:
        logger.warning("Snapshot yuborilmadi (order %s)", order_id)

    async def pump() -> None:
        async for payload in store.subscribe_driver(driver_id):
            await websocket.send_text(json.dumps({"event": "update", "item": payload}))

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("Order %s WS receive xatosi: %s", order_id, exc)
    finally:
        pump_task.cancel()


# nginx `$request_uri` ni to'liq uzatadi (`/api/...`); ichki tarmoqdan esa prefiksiz.
app.include_router(router)
if API_PREFIX:
    app.include_router(router, prefix=API_PREFIX)
