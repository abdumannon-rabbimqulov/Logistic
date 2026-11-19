import os
import logging
from typing import AsyncGenerator

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession


logger = logging.getLogger(__name__)

load_dotenv()


def get_required_env(key: str, default: str | None = None) -> str:
    value = os.getenv(key, default)
    if not value:
        error_msg = f"❌ CRITICAL: Environment variable '{key}' is not set. Check .env file or set it manually."
        logger.error(error_msg)
        raise ValueError(error_msg)
    return value


def get_optional_env(key: str, default: str | None = None) -> str | None:
    return os.getenv(key, default)



BOT_TOKEN = get_required_env('BOT_TOKEN')
WEBAPP_URL = get_optional_env('WEBAPP_URL', 'http://localhost:8000')
API_PUBLIC_PREFIX = (get_optional_env("API_PUBLIC_PREFIX", "/api") or "/api").rstrip("/") or "/api"
ADMIN_IDS: set[int] = {int(i.strip()) for i in get_optional_env("ADMIN", "").split(",") if i.strip()}





SECRET_KEY = get_required_env('SECRET_KEY')
ALGORITHM = get_optional_env('ALGORITHM', 'HS256')
ACCESS_TOKEN_EXPIRE_MINUTES = int(get_optional_env('ACCESS_TOKEN_EXPIRE_MINUTES', '60'))
REFRESH_TOKEN_EXPIRE_DAYS = int(get_optional_env('REFRESH_TOKEN_EXPIRE_DAYS', '1'))


REDIS_HOST = get_optional_env('REDIS_HOST', 'logistika_redis')
REDIS_PORT = int(get_optional_env('REDIS_PORT', '6379'))
REDIS_DB = int(get_optional_env('REDIS_DB', '2'))

# ── RabbitMQ: haydovchi qidirish vazifalari navbati ──────────────────────────
# Qidiruv (services/dispatch.py) endi so'rov ichida emas, alohida worker jarayonida
# bajariladi (workers/dispatch_worker.py). API/bot faqat vazifani navbatga qo'yadi.
RABBITMQ_URL = get_optional_env('RABBITMQ_URL', 'amqp://guest:guest@rabbitmq:5672/')
# Rejalashtirilgan buyurtma uchun haydovchi qidiruvi yuklashdan shuncha vaqt oldin
# boshlanadi. Ilgari qidiruv buyurtma yaratilishi bilanoq ketardi — 2 kundan keyingi
# yuk uchun ham — va haydovchi shuncha vaqtga band bo'lib qolardi.
DISPATCH_LEAD_HOURS = int(get_optional_env('DISPATCH_LEAD_HOURS', '24'))
# Sana bo'yicha taqqoslashlar (haydovchining "qachondan yuk olaman" sanasi) shu
# mintaqada bajariladi — UTC'da emas. docker-compose'dagi `TZ` bilan bir xil bo'lishi kerak.
APP_TIMEZONE = get_optional_env('APP_TIMEZONE', 'Asia/Tashkent')
# Worker bir vaqtning o'zida nechta buyurtmani qidirishi (AMQP prefetch). Aynan shu
# raqam "birdaniga hamma buyurtmani qidirib tashlamaslik" cheklovini beradi: qolgan
# xabarlar navbatda kutib turadi, ya'ni DB/Telegram/OSRM yuki bir tekis taqsimlanadi.
DISPATCH_PREFETCH = int(get_optional_env('DISPATCH_PREFETCH', '5'))

# Yandex Geocoder — manzil qidirish/aniqlash (order/router.py, services/yandex_geocoder.py)
API_YANDEX_KEY = get_optional_env('API_YANDEX_KEY')

# Self-hosted OSRM — marshrut/masofa hisoblash (docker-compose'dagi "osrm" xizmati)
OSRM_BASE_URL = get_optional_env('OSRM_BASE_URL', 'http://osrm:5000')


LIVE_LOC_TTL_SEC = int(get_optional_env("LIVE_LOC_TTL_SEC", "120"))
LIVE_LOC_DB_THROTTLE_SEC = int(get_optional_env("LIVE_LOC_DB_THROTTLE_SEC", "60"))
LIVE_LOC_DEFAULT_PERIOD_SEC = int(get_optional_env("LIVE_LOC_DEFAULT_PERIOD_SEC", "1800"))

# ── Geofence: haydovchi nuqtaga haqiqatan yetib kelganini tekshirish ──────────
# (services/geofence.py). Haydovchi buyurtma qadamini faqat shu radius ichida
# turib yopa oladi — aks holda manzilga bormasdan "Yetkazdim" bosish mumkin edi.
GEOFENCE_RADIUS_M = int(get_optional_env("GEOFENCE_RADIUS_M", "1000"))
# GPS xatosi radiusga qo'shiladi (lekin bu chegaradan oshmaydi) — shahar ichida
# yoki ombor binosi yonida aniqlik pasayganda haqiqiy haydovchini rad etmaslik uchun.
GEOFENCE_ACCURACY_ALLOWANCE_M = int(get_optional_env("GEOFENCE_ACCURACY_ALLOWANCE_M", "250"))
# Bundan yomon aniqlikdagi o'lchov umuman qabul qilinmaydi — bunday koordinata
# bilan "nuqtadamisiz?" degan savolga ishonchli javob berib bo'lmaydi.
GEOFENCE_MAX_ACCURACY_M = int(get_optional_env("GEOFENCE_MAX_ACCURACY_M", "500"))
# Zaxira (Redis'dagi oxirgi ma'lum) koordinata shu muddatdan eski bo'lsa ishlatilmaydi.
GEOFENCE_LOCATION_MAX_AGE_SEC = int(get_optional_env("GEOFENCE_LOCATION_MAX_AGE_SEC", "120"))
# Jonli GPS bo'lmaganda haydovchining bazadagi OXIRGI ma'lum nuqtasi shuncha vaqt
# ishonchli hisoblanadi (dispatch nomzodlari va jonli xaritada). Bitta joyda —
# ilgari `services/dispatch.py` va `services/public_map.py` da alohida yozilgan edi.
LAST_KNOWN_LOCATION_MAX_AGE_SEC = int(get_optional_env("LAST_KNOWN_LOCATION_MAX_AGE_SEC", str(6 * 3600)))


ENVIRONMENT = get_optional_env('ENVIRONMENT', 'development')
LOG_LEVEL = get_optional_env('LOG_LEVEL', 'INFO')

# CORS: ruxsat etilgan originlar (vergul bilan ajratilgan). "*" ishlatilmaydi —
# allow_credentials=True bilan birga "*" xavfli va spetsifikatsiya bo'yicha taqiqlangan.
CORS_ORIGINS: list[str] = [
    o.strip()
    for o in get_optional_env("CORS_ORIGINS", WEBAPP_URL or "").split(",")
    if o.strip()
]





DATABASE_URL = get_required_env("DB_URL")

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True, pool_size=10, max_overflow=20)
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)




async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
STATIC_PATH = "/static/uploads"

if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

logger.info(f"✅ Configuration loaded successfully. Environment: {ENVIRONMENT}")
