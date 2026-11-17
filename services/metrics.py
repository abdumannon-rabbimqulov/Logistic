"""HTTP so'rov metrikalari: soni, tezligi (latency), xatolar — admin "Server" bo'limi uchun.

Har bir so'rov tugaganda Redis'dagi DAQIQALIK bo'lakka yoziladi:

    mon:m:<minute>   hash — umumiy:  n (soni), s4/s5 (4xx/5xx), ms (jami vaqt),
                                     b0..bN (latency gistogrammasi)
    mon:r:<minute>   hash — endpoint bo'yicha:  "<METHOD> <route>|n|ms|e4|e5"

`<minute>` = unix vaqt // 60. Kalitlar `RETENTION_SEC` (26 soat) dan keyin o'zi o'chadi,
ya'ni xotira cheklangan: 1440 daqiqa × 2 hash.

Nega Redis (Prometheus emas): loyihada allaqachon bor, alohida xizmat va konfiguratsiya
kerak emas, bir nechta `web` nusxasi bo'lsa ham hammasi bitta joyga yoziladi.

Percentil (p50/p95/p99) gistogrammadan hisoblanadi — har bir so'rovni saqlamasdan.
Aniqlik bo'lak chegaralari darajasida (masalan "p95 ≈ 250–500 ms orasida"), kuzatuv
uchun bu yetarli.

XAVFSIZLIK: yozish hech qachon so'rovni buzmasligi kerak — Redis ishlamasa yoki sekin
bo'lsa metrika jimgina tashlab yuboriladi (`WRITE_TIMEOUT_SEC`).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from services.live_location import get_redis

logger = logging.getLogger(__name__)

# Latency gistogrammasi chegaralari (ms). Oxirgi bo'lak — undan kattasi.
BUCKETS_MS: tuple[float, ...] = (25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)
RETENTION_SEC = 26 * 3600
WRITE_TIMEOUT_SEC = 0.25

# Kuzatuvni buzadigan shovqin: healthcheck har 30s, monitoring sahifasi esa o'zi
# har 15s so'raydi — ular "real foydalanuvchi trafigi" emas.
_SKIP_PREFIXES = ("/health", "/api/health", "/system/monitoring", "/api/system/monitoring")

# Shu jarayonda hozir bajarilayotgan so'rovlar (bir `web` nusxasi uchun).
_in_flight = 0
# Fon yozuvlariga havola: asyncio vazifani faqat zaif havola bilan saqlaydi, havolasiz
# vazifa tugamasdan GC tomonidan yig'ilib ketishi mumkin.
_pending_writes: set[asyncio.Task] = set()
_process_started = time.time()


def in_flight() -> int:
    return _in_flight


def process_uptime_sec() -> float:
    return time.time() - _process_started


def _bucket_index(ms: float) -> int:
    for i, edge in enumerate(BUCKETS_MS):
        if ms <= edge:
            return i
    return len(BUCKETS_MS)


def _route_label(scope: Scope) -> str:
    """`/orders/123` emas, `/orders/{order_id}` — aks holda har ID alohida qator bo'lardi."""
    route = scope.get("route")
    path = getattr(route, "path", None) or "(topilmadi)"
    return f"{scope.get('method', '?')} {path}"


async def _write(route: str, status: int, ms: float) -> None:
    minute = int(time.time() // 60)
    mk, rk = f"mon:m:{minute}", f"mon:r:{minute}"
    r = get_redis()
    pipe = r.pipeline(transaction=False)
    pipe.hincrby(mk, "n", 1)
    pipe.hincrbyfloat(mk, "ms", ms)
    pipe.hincrby(mk, f"b{_bucket_index(ms)}", 1)
    pipe.hincrby(rk, f"{route}|n", 1)
    pipe.hincrbyfloat(rk, f"{route}|ms", ms)
    if 400 <= status < 500:
        pipe.hincrby(mk, "s4", 1)
        pipe.hincrby(rk, f"{route}|e4", 1)
    elif status >= 500:
        pipe.hincrby(mk, "s5", 1)
        pipe.hincrby(rk, f"{route}|e5", 1)
    pipe.expire(mk, RETENTION_SEC)
    pipe.expire(rk, RETENTION_SEC)
    await pipe.execute()


async def record(route: str, status: int, ms: float) -> None:
    try:
        await asyncio.wait_for(_write(route, status, ms), WRITE_TIMEOUT_SEC)
    except Exception as exc:  # noqa: BLE001 — metrika hech qachon so'rovni yiqitmaydi
        logger.debug("Metrika yozilmadi: %s", exc)


class MetricsMiddleware:
    """Sof ASGI middleware (BaseHTTPMiddleware emas): javob oqimini buzmaydi va
    javob TO'LIQ yuborilguncha bo'lgan vaqtni o'lchaydi. Ilova istisno tashlasa ham
    so'rov 500 sifatida hisobga olinadi — "yo'qolgan" so'rovlar shu yerda ko'rinadi."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path", "").startswith(_SKIP_PREFIXES):
            await self.app(scope, receive, send)
            return

        global _in_flight
        _in_flight += 1
        started = time.perf_counter()
        status: Optional[int] = None

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            status = 500
            raise
        finally:
            _in_flight -= 1
            ms = (time.perf_counter() - started) * 1000
            # Javob boshlanmasdan uzilgan so'rov (mijoz ketib qoldi va h.k.) — 499,
            # nginx konventsiyasi bo'yicha: server xatosi emas, lekin ko'rinib turishi kerak.
            final_status = status if status is not None else 499
            task = asyncio.ensure_future(record(_route_label(scope), final_status, ms))
            _pending_writes.add(task)
            task.add_done_callback(_pending_writes.discard)


# ── O'qish (admin endpointi uchun) ────────────────────────────────────────────


def _percentile(buckets: list[int], total: int, q: float) -> Optional[float]:
    """Gistogrammadan percentil: kerakli tartib raqami tushgan bo'lak ichida chiziqli
    interpolyatsiya. Oxirgi (cheksiz) bo'lak uchun uning pastki chegarasi qaytariladi."""
    if total <= 0:
        return None
    target = q * total
    seen = 0
    for i, count in enumerate(buckets):
        if count and seen + count >= target:
            lo = BUCKETS_MS[i - 1] if i > 0 else 0.0
            if i >= len(BUCKETS_MS):
                return float(BUCKETS_MS[-1])
            hi = BUCKETS_MS[i]
            return lo + (hi - lo) * ((target - seen) / count)
        seen += count
    return float(BUCKETS_MS[-1])


# ── Oxirgi server xatolari ────────────────────────────────────────────────────
# Gistogramma "nechta xato" ni biladi, lekin "qaysi va nima uchun" ni emas. Admin
# monitoringida muammo bosilganda aynan shu ro'yxat ko'rsatiladi. Faqat oxirgi
# ERRORS_KEEP tasi saqlanadi (Redis LIST, LTRIM).
ERRORS_KEY = "mon:errors"
ERRORS_KEEP = 100


async def _write_error(entry: dict[str, Any]) -> None:
    r = get_redis()
    pipe = r.pipeline(transaction=False)
    pipe.lpush(ERRORS_KEY, json.dumps(entry, ensure_ascii=False))
    pipe.ltrim(ERRORS_KEY, 0, ERRORS_KEEP - 1)
    pipe.expire(ERRORS_KEY, RETENTION_SEC)
    await pipe.execute()


async def record_error(
    *, method: str, path: str, status: int, exc_type: str, message: str, request_id: str
) -> None:
    """Xatoni monitoring ro'yxatiga yozadi. Hech qachon exception tashlamaydi."""
    entry = {
        "ts": int(time.time()),
        "method": method,
        "path": path,
        "status": status,
        "exc_type": exc_type,
        "message": message[:400],
        "request_id": request_id,
    }
    try:
        await asyncio.wait_for(_write_error(entry), WRITE_TIMEOUT_SEC)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Xato monitoringga yozilmadi: %s", exc)


async def read_recent_errors(minutes: int, limit: int = 30) -> list[dict[str, Any]]:
    """Oxirgi `minutes` daqiqadagi xatolar, eng yangisi birinchi."""
    since = time.time() - minutes * 60
    try:
        raw = await get_redis().lrange(ERRORS_KEY, 0, ERRORS_KEEP - 1)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Xatolar ro'yxatini o'qib bo'lmadi: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        try:
            entry = json.loads(item)
        except (TypeError, ValueError):
            continue
        if entry.get("ts", 0) >= since:
            out.append(entry)
            if len(out) >= limit:
                break
    return out


async def read_window(minutes: int) -> dict[str, Any]:
    """Oxirgi `minutes` daqiqa: vaqt qatori (≤ ~120 nuqta), jami ko'rsatkichlar va
    endpointlar reytingi."""
    minutes = max(5, min(minutes, 24 * 60))
    now_min = int(time.time() // 60)
    mins = list(range(now_min - minutes + 1, now_min + 1))

    r = get_redis()
    pipe = r.pipeline(transaction=False)
    for m in mins:
        pipe.hgetall(f"mon:m:{m}")
    for m in mins:
        pipe.hgetall(f"mon:r:{m}")
    raw = await pipe.execute()
    per_min, per_route = raw[: len(mins)], raw[len(mins):]

    nb = len(BUCKETS_MS) + 1
    # Grafik uchun nuqtalarni guruhlash: 24 soat = 1440 daqiqa → 12 daqiqalik qadam.
    step = max(1, -(-minutes // 120))
    series: list[dict[str, Any]] = []
    tot_n = tot_s4 = tot_s5 = 0
    tot_ms = 0.0
    tot_b = [0] * nb

    for start in range(0, len(mins), step):
        n = s4 = s5 = 0
        ms = 0.0
        b = [0] * nb
        chunk = per_min[start:start + step]
        for h in chunk:
            n += _int(h.get("n"))
            s4 += _int(h.get("s4"))
            s5 += _int(h.get("s5"))
            ms += float(h.get("ms") or 0)
            for i in range(nb):
                b[i] += _int(h.get(f"b{i}"))
        tot_n += n
        tot_s4 += s4
        tot_s5 += s5
        tot_ms += ms
        for i in range(nb):
            tot_b[i] += b[i]
        series.append({
            "t": mins[start] * 60,
            "rpm": round(n / len(chunk), 2),          # so'rov / daqiqa (o'rtacha)
            "avg_ms": round(ms / n, 1) if n else None,
            "p95_ms": round(_percentile(b, n, 0.95), 1) if n else None,
            "errors_5xx": s5,
            "errors_4xx": s4,
        })

    routes: dict[str, dict[str, float]] = {}
    for h in per_route:
        for key, val in h.items():
            name, _, field = key.rpartition("|")
            entry = routes.setdefault(name, {"n": 0, "ms": 0.0, "e4": 0, "e5": 0})
            entry[field] = entry.get(field, 0) + float(val)
    route_rows = [
        {
            "route": name,
            "count": int(v["n"]),
            "avg_ms": round(v["ms"] / v["n"], 1) if v["n"] else None,
            "errors_4xx": int(v["e4"]),
            "errors_5xx": int(v["e5"]),
        }
        for name, v in routes.items()
        if v["n"]
    ]

    return {
        "minutes": minutes,
        "step_minutes": step,
        "bucket_edges_ms": list(BUCKETS_MS),
        "series": series,
        "totals": {
            "requests": tot_n,
            "rpm": round(tot_n / minutes, 2),
            "errors_4xx": tot_s4,
            "errors_5xx": tot_s5,
            "error_rate_5xx": round(tot_s5 / tot_n * 100, 2) if tot_n else 0.0,
            "avg_ms": round(tot_ms / tot_n, 1) if tot_n else None,
            "p50_ms": _round(_percentile(tot_b, tot_n, 0.50)),
            "p95_ms": _round(_percentile(tot_b, tot_n, 0.95)),
            "p99_ms": _round(_percentile(tot_b, tot_n, 0.99)),
            "histogram": tot_b,
        },
        "slowest_routes": sorted(
            (r for r in route_rows if r["count"] >= 3), key=lambda r: r["avg_ms"] or 0, reverse=True
        )[:10],
        "error_routes": sorted(
            (r for r in route_rows if r["errors_5xx"] or r["errors_4xx"]),
            key=lambda r: (r["errors_5xx"], r["errors_4xx"]),
            reverse=True,
        )[:10],
        "busiest_routes": sorted(route_rows, key=lambda r: r["count"], reverse=True)[:10],
        "recent_errors": await read_recent_errors(minutes),
    }


def _int(v: Any) -> int:
    """Redis qiymati: odatda "7", lekin HINCRBYFLOAT bilan aralashgan bo'lsa "7.0"."""
    return int(float(v)) if v else 0


def _round(v: Optional[float]) -> Optional[float]:
    return round(v, 1) if v is not None else None
