"""Self-hosted OSRM orqali marshrut hisoblash (masofa, davomiylik, geometriya).

Unumdorlik (yuklama testi, 2026-11-19): web CPU'sining ~60% i marshrut geometriyasiga
ketardi — katta GeoJSON'ni parse qilish, WKT qurish va soddalashtirish. Shuning uchun:
- bitta umumiy HTTP klient (har chaqiruvda yangi ulanish va SSL konteksti ochilmaydi);
- geometriya kerak bo'lmasa (`with_geometry=False`: ETA, dispatch) OSRM uni umuman
  qaytarmaydi;
- WKT va xarita uchun soddalashtirilgan chiziq faqat so'ralganda hisoblanadi;
- to'liq geometriyali natija Redis'da keshlanadi: mijoz narxni ko'rgach aynan shu
  nuqtalar bilan buyurtma beradi va marshrut qayta hisoblanmaydi.
"""

from __future__ import annotations

import base64
import json
import logging
import zlib
from dataclasses import dataclass, field
from functools import cached_property
from typing import Optional, Sequence

import httpx
import numpy as np

from config.config import OSRM_BASE_URL
from utils.geo import lonlat_to_wkt, simplify_lonlat_array

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 8.0

# Kesh: koordinatalar 5 xona (~1 m) aniqlikda kalitga kiradi. Maqsad — mijoz narxni
# ko'rgach o'sha nuqtalar bilan buyurtma berganda marshrutni qayta hisoblamaslik, shuning
# uchun muddat qisqa. Redis bir xil konteynerda jonli joylashuvlarni ham saqlaydi
# (prod'da 128 MB): qiymat siqiladi, juda uzun marshrutlar umuman keshlanmaydi.
ROUTE_CACHE_TTL_SEC = 10 * 60
ROUTE_CACHE_MAX_BYTES = 64 * 1024
_CACHE_PREFIX = "osrm:route:v2:"

_client: Optional[httpx.AsyncClient] = None


class OSRMRouteError(Exception):
    """OSRM marshrut hisoblay olmadi (server javob bermadi yoki nuqta yo'ldan uzoq)."""


class OSRMUnavailableError(OSRMRouteError):
    """OSRM serveriga umuman ulanib bo'lmadi — bu BIZNING infratuzilma nosozligimiz.

    Mijozga 503 qaytarilishi kerak: u manzilni o'zgartirib qayta urinsa ham foyda yo'q.
    """


class OSRMNoRouteError(OSRMRouteError):
    """OSRM javob berdi, lekin bu ikki nuqta orasida yo'l topa olmadi.

    Bu mijoz kiritgan ma'lumot muammosi (masalan nuqta yo'ldan juda uzoqda yoki
    dengiz ortida) — 422 qaytariladi, boshqa manzil tanlash yordam beradi.
    """


@dataclass
class RouteResult:
    distance_km: float
    duration_min: float
    # OSRM'ning xom geometriyasi: [[lon, lat], ...]. Keshdan olinganda yoki
    # `with_geometry=False` bo'lsa — bo'sh (u holda quyidagilar keshdan to'ldiriladi).
    coordinates: list = field(default_factory=list, repr=False)
    _wkt: Optional[str] = field(default=None, repr=False)
    _display: Optional[list[tuple[float, float]]] = field(default=None, repr=False)

    @cached_property
    def _lonlat(self) -> "np.ndarray":
        return np.asarray(self.coordinates, dtype=float).reshape(-1, 2)

    @cached_property
    def geometry_wkt(self) -> str:
        """"LINESTRING(lon lat, ...)" — SRID 4326, PostGIS'ga saqlash uchun."""
        if self._wkt is not None:
            return self._wkt
        return lonlat_to_wkt(self._lonlat)

    @cached_property
    def geometry(self) -> list[tuple[float, float]]:
        """To'liq geometriya [(latitude, longitude), ...] — Yandex Maps shu tartibni kutadi."""
        return [(lat, lon) for lon, lat in self.coordinates]

    @cached_property
    def display_geometry(self) -> list[tuple[float, float]]:
        """Xaritada ko'rsatish uchun soddalashtirilgan chiziq (`utils.geo.simplify_lonlat_array`)."""
        if self._display is not None:
            return self._display
        return simplify_lonlat_array(self._lonlat)


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )
    return _client


async def close_client() -> None:
    """Ilova to'xtaganda (lifespan) chaqiriladi."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _cache_key(coordinates: Sequence[tuple[float, float]]) -> str:
    return _CACHE_PREFIX + ";".join(f"{float(lat):.5f},{float(lon):.5f}" for lat, lon in coordinates)


async def _cache_get(key: str) -> Optional[RouteResult]:
    # Import shu yerda: live_location Redis klientini yaratadi, test va skriptlarda
    # OSRM moduli Redis'siz ham import qilinishi kerak.
    from services.live_location import get_redis

    try:
        raw = await get_redis().get(key)
    except Exception as exc:  # Redis ishlamasa — keshsiz davom etamiz (fail-open)
        logger.debug("OSRM keshini o'qib bo'lmadi: %s", exc)
        return None
    if not raw:
        return None
    try:
        data = json.loads(zlib.decompress(base64.b64decode(raw)))
        return RouteResult(
            distance_km=data["distance_km"],
            duration_min=data["duration_min"],
            _wkt=data["wkt"],
            _display=[tuple(p) for p in data["display"]],
        )
    except (ValueError, KeyError, TypeError):
        return None


async def _cache_set(key: str, route: RouteResult) -> None:
    from services.live_location import get_redis

    payload = base64.b64encode(zlib.compress(json.dumps({
        "distance_km": route.distance_km,
        "duration_min": route.duration_min,
        "wkt": route.geometry_wkt,
        "display": route.display_geometry,
    }).encode(), 1)).decode()
    if len(payload) > ROUTE_CACHE_MAX_BYTES:
        return
    try:
        await get_redis().set(key, payload, ex=ROUTE_CACHE_TTL_SEC)
    except Exception as exc:
        logger.debug("OSRM keshiga yozib bo'lmadi: %s", exc)


async def get_route(
    coordinates: Sequence[tuple[float, float]], *, with_geometry: bool = True
) -> RouteResult:
    """coordinates: ketma-ket (latitude, longitude) juftliklar ro'yxati (kamida 2 ta, pickup->delivery tartibida).

    `with_geometry=True` — `overview=full` (to'liq aniqlikdagi geometriya) so'raladi: u
    bazaga saqlanadigan `geometry_wkt` uchun kerak. Xaritada ko'rsatish uchun OSRM'ning
    o'z `overview=simplified` rejimi juda qo'pol (uzoq yo'llarda burilishlarni "kesib"
    o'tadi), shuning uchun `display_geometry` to'liq geometriyadan
    `utils.geo.simplify_polyline` bilan olinadi. Natija Redis'da keshlanadi.

    `with_geometry=False` — faqat masofa va vaqt (ETA, dispatch): geometriya so'ralmaydi.
    """
    if len(coordinates) < 2:
        # Ma'lumot muammosi (infratuzilma emas) — chaqiruvchi buni 422 sifatida
        # ushlashi uchun bazaviy OSRMRouteError emas, OSRMNoRouteError tashlanadi.
        raise OSRMNoRouteError("Marshrut hisoblash uchun kamida 2 ta nuqta kerak")

    cache_key = _cache_key(coordinates) if with_geometry else None
    if cache_key:
        cached = await _cache_get(cache_key)
        if cached is not None:
            return cached

    coords_str = ";".join(f"{lon},{lat}" for lat, lon in coordinates)
    url = f"{OSRM_BASE_URL}/route/v1/driving/{coords_str}"
    params = {"overview": "full", "geometries": "geojson"} if with_geometry else {"overview": "false"}

    try:
        response = await _http().get(url, params=params)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.error("OSRM so'rovi muvaffaqiyatsiz (%s): %s", url, exc)
        raise OSRMUnavailableError(f"OSRM serveriga ulanib bo'lmadi: {exc}") from exc

    if data.get("code") != "Ok" or not data.get("routes"):
        raise OSRMNoRouteError(f"OSRM marshrut topa olmadi: {data.get('code')}")

    route = data["routes"][0]
    result = RouteResult(
        distance_km=round(route["distance"] / 1000, 2),
        duration_min=round(route["duration"] / 60, 1),
        coordinates=route["geometry"]["coordinates"] if with_geometry else [],
    )
    if cache_key:
        await _cache_set(cache_key, result)
    return result
