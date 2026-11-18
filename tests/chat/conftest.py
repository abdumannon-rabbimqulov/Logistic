"""Chat mikroservizi testlari: real Postgres/Redis/RabbitMQ'siz.

* baza — SQLite (`aiosqlite`), har test uchun yangi fayl;
* Redis — `MemoryBroadcaster` (yuborilgan WS hodisalari ro'yxatda);
* RabbitMQ — `queue.capture_events` (chiqarilgan hodisalar ro'yxatda);
* media — vaqtinchalik papka.

`chat_service.config` majburiy muhit o'zgaruvchilarini import paytida o'qiydi,
shuning uchun ular shu yerda, import'dan OLDIN beriladi.
"""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("CHAT_DB_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("CORE_API_URL", "")

try:
    import aiosqlite  # noqa: F401
    from jose import jwt

    from chat_service import access, db as chat_db, queue, realtime, storage
    from chat_service.config import ALGORITHM, SECRET_KEY
    from chat_service.models import Base
except ImportError:  # pragma: no cover — bog'liqliklar o'rnatilmagan muhit (masalan `web` image)
    # Xato bilan yiqilmasdan, chat testlarini butunlay chetlab o'tamiz.
    # O'rnatish: pip install -r chat_service/requirements-dev.txt
    collect_ignore_glob = ["test_*.py"]

SENDER = 1001
DRIVER_USER = 2002
DRIVER_ID = 77
STRANGER = 3003


def make_token(user_id: int, role: str = "sender", token_type: str = "access") -> str:
    payload = {"sub": str(user_id), "role": role, "type": token_type, "exp": int(time.time()) + 3600}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def auth(user_id: int, role: str = "sender") -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(user_id, role)}"}


@pytest.fixture
async def chat_env(tmp_path, monkeypatch):
    engine = chat_db.init_engine(f"sqlite+aiosqlite:///{tmp_path / 'chat.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    broadcaster = realtime.MemoryBroadcaster()
    realtime.set_broadcaster(broadcaster)
    events: list = []
    queue.capture_events(events)
    storage.set_storage(storage.LocalStorage(tmp_path / "media"))

    async def no_core(token: str):
        return None

    monkeypatch.setattr(access, "core_driver_lookup", no_core)

    yield {"broadcaster": broadcaster, "events": events, "media_root": tmp_path / "media"}

    queue.capture_events(None)
    realtime.set_broadcaster(None)
    await chat_db.dispose_engine()


@pytest.fixture
async def client(chat_env):
    import httpx

    from chat_service.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://chat") as c:
        yield c
