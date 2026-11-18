"""Admin "Server" bo'limi uchun infratuzilma holati.

Har bir komponent alohida tekshiriladi va o'z natijasini qaytaradi:

    {"status": "ok" | "warn" | "critical", "issues": [...], ...ko'rsatkichlar}

Bitta komponent ishlamasa (masalan RabbitMQ) qolganlari baribir ko'rsatiladi —
monitoring sahifasi aynan nosozlik paytida kerak, shuning uchun u o'zi yiqilmasligi
shart. Har tekshiruvga vaqt chegarasi qo'yilgan (`CHECK_TIMEOUT_SEC`).

Server ko'rsatkichlari `/proc` dan o'qiladi. Konteyner ichida `/proc/loadavg`,
`/proc/meminfo`, `/proc/stat` HOST mashinaniki (lxcfs yo'q) — ya'ni bu butun server
yuklamasi, faqat `web` konteyneriniki emas.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import httpx
from sqlalchemy import func, select, text

from config.config import OSRM_BASE_URL, async_session, engine
from order.dispatch_models import DispatchAttempt, DispatchAttemptStatus
from order.models import Order, OrderStatus
from services import metrics, queue
from services.dispatch import MAX_ROUNDS, STUCK_ORDER_AFTER_SEC
from services.live_location import get_redis

CHECK_TIMEOUT_SEC = 3.0
SUPPORT_URL = os.getenv("SUPPORT_INTERNAL_URL", "http://support:8000")

# Ogohlantirish chegaralari — bitta joyda, oson sozlash uchun.
CPU_WARN, CPU_CRIT = 75.0, 90.0
MEM_WARN, MEM_CRIT = 80.0, 92.0
DISK_WARN, DISK_CRIT = 80.0, 90.0
P95_WARN_MS, P95_CRIT_MS = 1000.0, 3000.0
ERR5XX_WARN, ERR5XX_CRIT = 1.0, 5.0          # % so'rovlardan
QUEUE_WARN, QUEUE_CRIT = 50, 200             # dispatch.jobs dagi kutayotgan xabarlar

_RANK = {"ok": 0, "warn": 1, "critical": 2}


def _worst(*statuses: str) -> str:
    return max(statuses, key=lambda s: _RANK.get(s, 0), default="ok")


def _level(value: float | None, warn: float, crit: float) -> str:
    if value is None:
        return "ok"
    return "critical" if value >= crit else "warn" if value >= warn else "ok"


async def _guard(name: str, fn: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(fn(), CHECK_TIMEOUT_SEC)
    except asyncio.TimeoutError:
        result = {"status": "critical", "issues": [f"{name}: {CHECK_TIMEOUT_SEC:.0f}s ichida javob bermadi"]}
    except Exception as exc:  # noqa: BLE001
        result = {"status": "critical", "issues": [f"{name}: {type(exc).__name__}: {exc}"[:300]]}
    result.setdefault("issues", [])
    result["check_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return result


# ── Server (host) ─────────────────────────────────────────────────────────────

_last_cpu: tuple[float, float] | None = None  # (idle, total) oldingi o'lchov


def _read_cpu() -> tuple[float, float]:
    with open("/proc/stat") as f:
        parts = [float(x) for x in f.readline().split()[1:]]
    idle = parts[3] + (parts[4] if len(parts) > 4 else 0)  # idle + iowait
    return idle, sum(parts)


async def _cpu_percent() -> float:
    """Ikki o'lchov orasidagi farq. Oldingi o'lchov (oldingi so'rovdan) bo'lmasa —
    0.3s kutib qayta o'lchanadi."""
    global _last_cpu
    prev = _last_cpu
    if prev is None:
        prev = _read_cpu()
        await asyncio.sleep(0.3)
    cur = _read_cpu()
    _last_cpu = cur
    d_total = cur[1] - prev[1]
    if d_total <= 0:
        return 0.0
    return round((1 - (cur[0] - prev[0]) / d_total) * 100, 1)


def _meminfo() -> dict[str, int]:
    out: dict[str, int] = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, _, rest = line.partition(":")
            out[key] = int(rest.split()[0]) * 1024  # kB → bayt
    return out


def _proc_rss() -> int | None:
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return None


async def check_server() -> dict[str, Any]:
    cpu = await _cpu_percent()
    with open("/proc/loadavg") as f:
        load1, load5, load15 = (float(x) for x in f.read().split()[:3])
    with open("/proc/uptime") as f:
        uptime = float(f.read().split()[0])
    mem = _meminfo()
    mem_total = mem.get("MemTotal", 0)
    mem_avail = mem.get("MemAvailable", 0)
    mem_pct = round((1 - mem_avail / mem_total) * 100, 1) if mem_total else None
    swap_total = mem.get("SwapTotal", 0)
    swap_used = swap_total - mem.get("SwapFree", 0)
    st = os.statvfs("/")
    disk_total = st.f_blocks * st.f_frsize
    disk_free = st.f_bavail * st.f_frsize
    disk_pct = round((1 - disk_free / disk_total) * 100, 1) if disk_total else None
    cores = os.cpu_count() or 1

    issues = []
    status = _worst(
        _level(cpu, CPU_WARN, CPU_CRIT),
        _level(mem_pct, MEM_WARN, MEM_CRIT),
        _level(disk_pct, DISK_WARN, DISK_CRIT),
        _level(load5 / cores, 1.0, 2.0),
    )
    if cpu >= CPU_WARN:
        issues.append(f"CPU yuklamasi yuqori: {cpu}%")
    if mem_pct is not None and mem_pct >= MEM_WARN:
        issues.append(f"RAM {mem_pct}% band")
    if disk_pct is not None and disk_pct >= DISK_WARN:
        issues.append(f"Disk {disk_pct}% to'lgan")
    if load5 / cores >= 1.0:
        issues.append(f"Load average (5 daq) {load5} — yadrolar soni {cores}")
    if swap_total and swap_used / swap_total > 0.5:
        status = _worst(status, "warn")
        issues.append("Swap yarmidan ko'p ishlatilmoqda — RAM yetishmayapti")

    return {
        "status": status,
        "issues": issues,
        "cpu_percent": cpu,
        "cpu_cores": cores,
        "load_avg": [load1, load5, load15],
        "mem_total": mem_total,
        "mem_used": mem_total - mem_avail,
        "mem_percent": mem_pct,
        "swap_total": swap_total,
        "swap_used": swap_used,
        "disk_total": disk_total,
        "disk_used": disk_total - disk_free,
        "disk_percent": disk_pct,
        "uptime_sec": int(uptime),
    }


# ── API jarayoni ──────────────────────────────────────────────────────────────

async def check_api(window: dict[str, Any]) -> dict[str, Any]:
    t = window["totals"]
    issues = []
    status = _worst(
        _level(t["p95_ms"], P95_WARN_MS, P95_CRIT_MS),
        _level(t["error_rate_5xx"], ERR5XX_WARN, ERR5XX_CRIT) if t["requests"] >= 20 else "ok",
    )
    if t["p95_ms"] and t["p95_ms"] >= P95_WARN_MS:
        issues.append(f"Sekin javoblar: p95 = {t['p95_ms']:.0f} ms")
    if t["errors_5xx"]:
        issues.append(f"{t['errors_5xx']} ta server xatosi (5xx) — {t['error_rate_5xx']}%")
    pool = engine.pool
    return {
        "status": status,
        "issues": issues,
        "in_flight": metrics.in_flight(),
        "process_uptime_sec": int(metrics.process_uptime_sec()),
        "process_rss": _proc_rss(),
        # `overflow()` bo'sh pool'da manfiy qaytaradi (checked_out - size) — 0 dan pastga tushirmaymiz.
        "db_pool": {
            "size": pool.size(),
            "checked_out": pool.checkedout(),
            "overflow": max(0, pool.overflow()),
        },
    }


# ── PostgreSQL ────────────────────────────────────────────────────────────────

async def check_postgres() -> dict[str, Any]:
    async with async_session() as db:
        # Birinchi so'rov ulanish ochishni ham o'z ichiga oladi — ping ikkinchisidan olinadi.
        await db.execute(text("select 1"))
        started = time.perf_counter()
        await db.execute(text("select 1"))
        ping_ms = round((time.perf_counter() - started) * 1000, 1)
        row = (await db.execute(text("""
            select
              (select count(*) from pg_stat_activity where datname = current_database()) as conns,
              (select count(*) from pg_stat_activity
                 where datname = current_database() and state = 'active') as active,
              (select setting::int from pg_settings where name = 'max_connections') as max_conns,
              pg_database_size(current_database()) as size_bytes,
              (select round(100.0 * blks_hit / nullif(blks_hit + blks_read, 0), 2)
                 from pg_stat_database where datname = current_database()) as cache_hit,
              (select deadlocks from pg_stat_database where datname = current_database()) as deadlocks,
              (select coalesce(max(extract(epoch from now() - query_start)), 0)
                 from pg_stat_activity
                 where datname = current_database() and state = 'active'
                   and pid <> pg_backend_pid()) as longest_query_sec
        """))).mappings().one()

    conns, max_conns = int(row["conns"]), int(row["max_conns"])
    longest = max(0.0, float(row["longest_query_sec"] or 0))
    cache_hit = float(row["cache_hit"]) if row["cache_hit"] is not None else None
    issues = []
    status = _worst(
        _level(conns / max_conns * 100 if max_conns else 0, 70, 90),
        _level(longest, 30, 120),
        _level(ping_ms, 100, 1000),
    )
    if longest >= 30:
        issues.append(f"Uzoq bajarilayotgan so'rov: {longest:.0f}s")
    if ping_ms >= 100:
        issues.append(f"Bazaga ping sekin: {ping_ms:.0f} ms")
    if conns / max_conns >= 0.7:
        issues.append(f"Ulanishlar {conns}/{max_conns}")
    if cache_hit is not None and cache_hit < 90:
        status = _worst(status, "warn")
        issues.append(f"Kesh samaradorligi past: {cache_hit}% — RAM yetmayapti yoki indeks yo'q")
    return {
        "status": status,
        "issues": issues,
        "ping_ms": ping_ms,
        "connections": conns,
        "active_queries": int(row["active"]),
        "max_connections": max_conns,
        "size_bytes": int(row["size_bytes"]),
        "cache_hit_percent": cache_hit,
        "deadlocks": int(row["deadlocks"] or 0),
        "longest_query_sec": round(longest, 1),
    }


# ── Redis ─────────────────────────────────────────────────────────────────────

async def check_redis() -> dict[str, Any]:
    r = get_redis()
    await r.ping()  # ulanishni isitish
    started = time.perf_counter()
    await r.ping()
    ping_ms = round((time.perf_counter() - started) * 1000, 1)
    info = await r.info()
    hits, misses = int(info.get("keyspace_hits", 0)), int(info.get("keyspace_misses", 0))
    used, maxmem = int(info.get("used_memory", 0)), int(info.get("maxmemory", 0))
    issues = []
    status = _level(ping_ms, 50, 500)
    if ping_ms >= 50:
        issues.append(f"Redis ping sekin: {ping_ms:.0f} ms")
    if maxmem and used / maxmem > 0.85:
        status = _worst(status, "warn")
        issues.append("Redis xotirasi limitga yaqin")
    if int(info.get("rejected_connections", 0)):
        status = _worst(status, "warn")
        issues.append(f"Rad etilgan ulanishlar: {info['rejected_connections']}")
    return {
        "status": status,
        "issues": issues,
        "ping_ms": ping_ms,
        "used_memory": used,
        "connected_clients": int(info.get("connected_clients", 0)),
        "ops_per_sec": int(info.get("instantaneous_ops_per_sec", 0)),
        "hit_rate_percent": round(hits / (hits + misses) * 100, 1) if hits + misses else None,
        "uptime_sec": int(info.get("uptime_in_seconds", 0)),
    }


# ── RabbitMQ: navbatlar va worker'lar ─────────────────────────────────────────

# (navbat, kim o'qiydi, iste'molchi bo'lishi shartmi)
QUEUES: list[tuple[str, str, bool]] = [
    (queue.JOBS_QUEUE, "dispatch-worker", True),
    (queue.DELAYED_QUEUE, "— (TTL taymer, iste'molchisiz)", False),
    (queue.DEAD_QUEUE, "— (yo'qolgan vazifalar)", False),
    (queue.SUPPORT_NOTIFICATIONS_QUEUE, "notification", True),
    (queue.ORDER_NOTIFICATIONS_QUEUE, "notification", True),
    (queue.SUPPORT_EVENTS_QUEUE, "support", True),
]


async def check_rabbitmq() -> dict[str, Any]:
    await queue.get_channel()  # ulanishni tayyorlaydi
    conn = queue._connection
    if conn is None:
        raise RuntimeError("RabbitMQ ulanishi yo'q")

    rows = []
    issues = []
    status = "ok"
    for name, consumer, must_consume in QUEUES:
        # Passiv e'lon yo'q navbatda kanalni yopadi — shuning uchun har navbatga alohida kanal.
        ch = await conn.channel()
        try:
            q = await ch.declare_queue(name, passive=True)
            res = q.declaration_result
            messages, consumers = int(res.message_count), int(res.consumer_count)
        except Exception:  # noqa: BLE001
            messages, consumers = None, None
        finally:
            if not ch.is_closed:
                await ch.close()

        row_status = "ok"
        if messages is None:
            row_status = "warn"
            issues.append(f"{name}: navbat topilmadi")
        else:
            if must_consume and consumers == 0:
                row_status = "critical"
                issues.append(f"{name}: o'quvchi yo'q — {consumer} ishlamayapti, xabarlar to'planib qolmoqda")
            if name == queue.DEAD_QUEUE and messages:
                row_status = _worst(row_status, "warn")
                issues.append(f"{messages} ta dispatch vazifasi barcha urinishlardan keyin ham bajarilmadi")
            if name == queue.JOBS_QUEUE:
                row_status = _worst(row_status, _level(messages, QUEUE_WARN, QUEUE_CRIT))
                if messages >= QUEUE_WARN:
                    issues.append(f"Dispatch navbati o'sib bormoqda: {messages} ta xabar")
        status = _worst(status, row_status)
        rows.append({
            "queue": name,
            "consumer": consumer,
            "messages": messages,
            "consumers": consumers,
            "status": row_status,
        })

    workers = {
        "dispatch-worker": next((r["consumers"] for r in rows if r["queue"] == queue.JOBS_QUEUE), None),
        "notification": next(
            (r["consumers"] for r in rows if r["queue"] == queue.SUPPORT_NOTIFICATIONS_QUEUE), None
        ),
    }
    return {"status": status, "issues": issues, "queues": rows, "workers": workers}


# ── HTTP orqali tekshiriladigan xizmatlar ────────────────────────────────────

async def _http_probe(url: str, expect: str) -> dict[str, Any]:
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=CHECK_TIMEOUT_SEC) as client:
        resp = await client.get(url)
    ms = round((time.perf_counter() - started) * 1000, 1)
    ok = resp.status_code == 200 and expect in resp.text
    issues = [] if ok else [f"Kutilmagan javob: HTTP {resp.status_code}"]
    status = "critical" if not ok else _level(ms, 300, 2000)
    if ok and ms >= 300:
        issues.append(f"Sekin javob: {ms:.0f} ms")
    return {"status": status, "issues": issues, "latency_ms": ms}


async def check_osrm() -> dict[str, Any]:
    # Toshkent ichidagi qisqa marshrut — xarita yuklangani va hisoblash ishlashi tekshiriladi.
    return await _http_probe(
        f"{OSRM_BASE_URL}/route/v1/driving/69.24,41.31;69.28,41.33?overview=false", '"code":"Ok"'
    )


async def check_support() -> dict[str, Any]:
    return await _http_probe(f"{SUPPORT_URL}/health", "ok")


# ── Biznes: so'rovlar/buyurtmalar "yo'qolmayaptimi" ───────────────────────────

async def check_business() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    hour_ago = now - timedelta(hours=1)
    stuck_before = now - timedelta(seconds=STUCK_ORDER_AFTER_SEC)
    live_attempts = (
        select(DispatchAttempt.order_id)
        .where(
            DispatchAttempt.status == DispatchAttemptStatus.PENDING,
            DispatchAttempt.expires_at > now,
        )
        .scalar_subquery()
    )
    async with async_session() as db:
        searching = await db.scalar(
            select(func.count()).select_from(Order).where(
                Order.status == OrderStatus.PENDING, Order.driver_id.is_(None)
            )
        )
        # Qidiruvda, lekin hech kimga taklif yuborilmagan va navbatga ham uzoq vaqt
        # qo'yilmagan — ya'ni qidiruv "yo'qolgan". Worker'dagi sweep ularni qayta
        # qo'zg'atishi kerak; bu son o'smasligi kerak.
        stuck = await db.scalar(
            select(func.count()).select_from(Order).where(
                Order.status == OrderStatus.PENDING,
                Order.driver_id.is_(None),
                Order.dispatch_paused_at.is_(None),
                Order.price_bump_requested_at.is_(None),
                Order.dispatch_round < MAX_ROUNDS,
                Order.last_dispatch_enqueued_at.is_not(None),
                Order.last_dispatch_enqueued_at <= stuck_before,
                Order.id.notin_(live_attempts),
            )
        )
        waiting_price = await db.scalar(
            select(func.count()).select_from(Order).where(
                Order.status == OrderStatus.PENDING, Order.price_bump_requested_at.is_not(None)
            )
        )
        created_hour = await db.scalar(
            select(func.count()).select_from(Order).where(Order.created_at >= hour_ago)
        )
        attempts = dict(
            (await db.execute(
                select(DispatchAttempt.status, func.count())
                .where(DispatchAttempt.sent_at >= hour_ago)
                .group_by(DispatchAttempt.status)
            )).all()
        )

    issues = []
    status = "ok"
    if stuck:
        status = "warn" if stuck < 5 else "critical"
        issues.append(f"{stuck} ta buyurtma qidiruvda qotib qolgan (taklif ham, navbat ham yo'q)")
    attempts_out = {s.value: int(c) for s, c in attempts.items()}
    sent = sum(attempts_out.values())
    expired = attempts_out.get("expired", 0)
    if sent >= 10 and expired / sent > 0.5:
        status = _worst(status, "warn")
        issues.append(f"Takliflarning {expired}/{sent} tasi javobsiz qolgan (1 soat)")
    return {
        "status": status,
        "issues": issues,
        "orders_searching": int(searching or 0),
        "orders_stuck": int(stuck or 0),
        "orders_waiting_price": int(waiting_price or 0),
        "orders_created_last_hour": int(created_hour or 0),
        "dispatch_attempts_last_hour": attempts_out,
    }


# ── Hammasi birga ─────────────────────────────────────────────────────────────

async def overview(minutes: int) -> dict[str, Any]:
    window = await metrics.read_window(minutes)
    names = ["server", "postgres", "redis", "rabbitmq", "osrm", "support", "business"]
    results = await asyncio.gather(
        _guard("Server", check_server),
        _guard("PostgreSQL", check_postgres),
        _guard("Redis", check_redis),
        _guard("RabbitMQ", check_rabbitmq),
        _guard("OSRM", check_osrm),
        _guard("Support", check_support),
        _guard("Buyurtmalar", check_business),
    )
    components = dict(zip(names, results))
    components["api"] = await _guard("API", lambda: check_api(window))
    overall = _worst(*(c["status"] for c in components.values()))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": overall,
        "components": components,
        "requests": window,
    }
