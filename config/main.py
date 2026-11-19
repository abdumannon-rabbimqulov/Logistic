"""FastAPI ilovasi — backendning kirish nuqtasi (`uvicorn config.main:app`).

So'rov yo'li:  router (HTTP: validatsiya, ruxsat)  →  services/ yoki crud (mantiq, DB)  →  models

Bu faylda faqat: lifespan (startup/shutdown), middleware'lar, router'larni ulash va
/health. Biznes-mantiq bu yerga yozilmaydi.
"""

import logging
import mimetypes
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import configure_mappers
from config.config import (
    engine,
    DB_POOL_SIZE,
    UPLOAD_DIR,
    STATIC_PATH,
    ENVIRONMENT,
    API_PUBLIC_PREFIX,
    WEBAPP_URL,
    CORS_ORIGINS,
)
from config.registry import Base  # barcha modellarni ro'yxatdan o'tkazadi
from contracts import safe_logging
from middlewares.error_handler import setup_error_handlers
from services.metrics import MetricsMiddleware

configure_mappers()

from Admin_panel.router import router as admin_router  # noqa: E402
from driver.router import router as driver_router  # noqa: E402
from manager.router import router as manager_router  # noqa: E402
from order.router import router as order_router  # noqa: E402
from users.router import router as auth_router  # noqa: E402

logger = logging.getLogger(__name__)

# uvicorn loglarni app import qilinishidan OLDIN sozlaydi (`--log-config`), shuning uchun
# filtr shu yerda o'rnatiladi: Telegram bot tokeni va `?token=` loglarga tushmasin.
safe_logging.install()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: jadval sxemasini yaratish (production'da alembic migratsiyasi tavsiya etiladi).
    # Bir nechta uvicorn worker bir vaqtda ishga tushadi: toza bazada ikkalasi bir xil
    # jadval/turni yaratishga urinib, biri "already exists" xatosini olishi mumkin.
    # Sxema baribir yaratilgan bo'ladi, shuning uchun bu worker'ni yiqitmaydi.
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # noqa: BLE001
        logger.warning("create_all boshqa worker bilan bir vaqtda ishladi: %s", exc)

    # Pool'dagi ulanishlarni oldindan ochish (services/db_warmup.py — nega kerakligi o'sha yerda).
    from services.db_warmup import warm_pool

    await warm_pool(engine, DB_POOL_SIZE, [t.name for t in Base.metadata.sorted_tables])

    # Navbat topologiyasi (dispatch vazifalari + `logistika.events` biznes hodisalari)
    # shu yerda ham e'lon qilinadi: worker/support'dan oldin ko'tarilsa ham birinchi
    # publish yo'qolmasin. Broker hali tayyor bo'lmasa API baribir ishlayveradi —
    # publish paytida qayta uriniladi.
    from services import queue as dispatch_queue

    try:
        await dispatch_queue.declare_topology()
    except dispatch_queue.QueueUnavailable:
        logger.warning("RabbitMQ hozircha mavjud emas — navbat birinchi so'rovda ulanadi")

    yield

    # Shutdown: RabbitMQ va Redis ulanishlarini yopish.
    #
    # DIQQAT: dispatch sweep loop'i endi bu yerda EMAS — u `workers/dispatch_worker.py`
    # ga ko'chirildi. Web jarayoni sof API bo'lib qoldi, fon ishlari worker'da.
    from services.live_location import close_redis
    from services.osrm_client import close_client as close_osrm_client

    await dispatch_queue.close_queue()
    await close_osrm_client()
    await close_redis()


_docs_prefix = API_PUBLIC_PREFIX or ""
app = FastAPI(
    title="Logistika AI API",
    version="1.0.0",
    description="🚀 Logistics platform with AI-powered order management",
    lifespan=lifespan,
    servers=[
        {"url": API_PUBLIC_PREFIX or "http://127.0.0.1:8003", "description": "API base (/api)"},
        {"url": "", "description": "Prefiksiz (localhost:8003)"},
    ],
    docs_url=f"{_docs_prefix}/docs" if _docs_prefix else "/docs",
    redoc_url=f"{_docs_prefix}/redoc" if _docs_prefix else "/redoc",
    openapi_url=f"{_docs_prefix}/openapi.json" if _docs_prefix else "/openapi.json",
)

# ─────────────────────────────────────────────────────────────
# Setup global error handlers
# ─────────────────────────────────────────────────────────────
setup_error_handlers(app)

# Uploads papkasini static qilib ulash.
# python:3.11-slim `.webp` ni tanimaydi va `application/octet-stream` qaytarardi
# (transport turi rasmlari webp) — turini aniq ro'yxatdan o'tkazamiz.
mimetypes.add_type("image/webp", ".webp")
app.mount(STATIC_PATH, StaticFiles(directory=UPLOAD_DIR), name="uploads")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS or [WEBAPP_URL],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# So'rovlar soni/tezligi/xatolari → Redis (admin "Server" bo'limi). Oxirgi qo'shilgan
# middleware eng tashqi qatlam bo'ladi — shuning uchun CORS va boshqa hamma narsa
# bilan birga o'lchanadi.
app.add_middleware(MetricsMiddleware)


# Barcha API router'lari bitta jadvalda: (router, qo'shimcha prefiks, teglar).
# Kim ishlatishini bilish uchun har router faylining boshidagi docstring'ga qarang.
API_ROUTERS = [
    (auth_router, "/auth", ["Auth"]),   # users/router.py       — login, profil, parol (hamma)
    (order_router, "", None),           # order/router.py       — /orders (sender, driver)
    (driver_router, "", None),          # driver/router.py      — /drivers (driver, truck-types)
    (admin_router, "", None),           # Admin_panel/router.py — /system (faqat admin, moliya)
    # `/manager` — moliyasiz operativ panel. `/system` dan ATAYLAB alohida:
    # menejerga admin endpointlaridan birortasi ham ochilmasligi kerak.
    (manager_router, "", None),         # manager/router.py     — /manager (menejer, admin)
]


def _register_api_routers(
    target: FastAPI,
    *,
    prefix: str = "",
    include_in_schema: bool = True,
) -> None:
    for router, extra_prefix, tags in API_ROUTERS:
        kwargs = {"prefix": f"{prefix}{extra_prefix}", "include_in_schema": include_in_schema}
        if tags:
            kwargs["tags"] = tags
        target.include_router(router, **kwargs)


_register_api_routers(app)
# Nginx /api/ → backend (prefix olib tashlanadi) va to'g'ridan-to'g'ri :8003/api/... uchun
_register_api_routers(app, prefix=API_PUBLIC_PREFIX, include_in_schema=False)


@app.get("/", tags=["System"], summary="API kirish nuqtasi")
@app.get(API_PUBLIC_PREFIX, tags=["System"], include_in_schema=False)
@app.get(f"{API_PUBLIC_PREFIX}/", tags=["System"], include_in_schema=False)
async def api_root():
    """Postman uchun: barcha endpointlar {API_PUBLIC_PREFIX} ostida chaqiriladi."""
    return {
        "service": "Logistika AI API",
        "api_base": API_PUBLIC_PREFIX,
        "docs": f"{API_PUBLIC_PREFIX}/docs",
        "health": f"{API_PUBLIC_PREFIX}/health",
        "examples": {
            "truck_types": f"{API_PUBLIC_PREFIX}/drivers/truck-types",
            "login": f"{API_PUBLIC_PREFIX}/auth/login",
        },
        "webapp_url": WEBAPP_URL,
    }





# ─────────────────────────────────────────────────────────────
# HEALTH CHECK & STATUS ENDPOINTS
# ─────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"], summary="Service health status")
@app.get(f"{API_PUBLIC_PREFIX}/health", tags=["System"], include_in_schema=False)
async def health_check():
    """Service ishlayaptimi tekshirish."""
    return {
        "status": "ok",
        "service": "Logistika AI API",
        "environment": ENVIRONMENT,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.get("/health/db", tags=["System"], summary="Database connection status")
@app.get(f"{API_PUBLIC_PREFIX}/health/db", tags=["System"], include_in_schema=False)
async def db_health():
    """Database ulanishini tekshirish."""
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        return {
            "status": "error",
            "database": "disconnected",
            "error": str(e)
        }




