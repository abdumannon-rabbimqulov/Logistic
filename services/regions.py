"""Koordinata qaysi viloyatga tushishini aniqlash (jonli xarita filteri uchun).

Manba: `services/uz_regions.geojson` — `data/geo/uzbekistan_regional.geojson` dan
soddalashtirilgan nusxa (~100 KB, ~200 m aniqlik). `data/` papkasi Docker image'ga
kirmaydi (`.dockerignore`), shuning uchun kerakli qism shu yerda turadi.

Tashqi kutubxonasiz (ray casting): 14 ta poligon uchun bounding-box filtri bilan bitta
nuqtani tekshirish mikrosekundlar oladi. Fayl birinchi chaqiruvda bir marta yuklanadi.

ID'lar geojson'dagi `id` (1 — Andijon ... 14 — Toshkent sh.) va DB'dagi
`order_waypoints.region_id` bilan bir xil.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

_GEOJSON_PATH = Path(__file__).with_name("uz_regions.geojson")

Ring = list[tuple[float, float]]  # (lon, lat)


@dataclass(frozen=True)
class Region:
    id: int
    name: str
    # Har bir poligon: [tashqi halqa, teshiklar...]
    polygons: tuple[tuple[Ring, ...], ...]
    bbox: tuple[float, float, float, float]  # min_lon, min_lat, max_lon, max_lat

    @property
    def bbox_area(self) -> float:
        return (self.bbox[2] - self.bbox[0]) * (self.bbox[3] - self.bbox[1])


def _ring_contains(ring: Ring, lon: float, lat: float) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _polygon_contains(polygon: tuple[Ring, ...], lon: float, lat: float) -> bool:
    outer, *holes = polygon
    if not _ring_contains(outer, lon, lat):
        return False
    return not any(_ring_contains(h, lon, lat) for h in holes)


@lru_cache(maxsize=1)
def _load() -> tuple[Region, ...]:
    data = json.loads(_GEOJSON_PATH.read_text(encoding="utf-8"))
    regions: list[Region] = []
    for feature in data["features"]:
        geom = feature["geometry"]
        raw = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        polygons = tuple(
            tuple([(float(x), float(y)) for x, y in ring] for ring in poly) for poly in raw
        )
        xs = [x for poly in polygons for x, _ in poly[0]]
        ys = [y for poly in polygons for _, y in poly[0]]
        regions.append(
            Region(
                id=int(feature["properties"]["id"]),
                name=str(feature["properties"]["name"]),
                polygons=polygons,
                bbox=(min(xs), min(ys), max(xs), max(ys)),
            )
        )
    # Kichik hududlar oldin: Toshkent shahri Toshkent viloyati ichida joylashgan,
    # chegarada ikkalasi ham "ushlasa" shahar ustun bo'lsin.
    regions.sort(key=lambda r: r.bbox_area)
    return tuple(regions)


def region_for_point(lat: Optional[float], lon: Optional[float]) -> Optional[int]:
    """Nuqta tushgan viloyat ID si; O'zbekistondan tashqarida yoki koordinatasiz — `None`."""
    if lat is None or lon is None:
        return None
    lat_f, lon_f = float(lat), float(lon)
    for region in _load():
        min_lon, min_lat, max_lon, max_lat = region.bbox
        if not (min_lon <= lon_f <= max_lon and min_lat <= lat_f <= max_lat):
            continue
        if any(_polygon_contains(poly, lon_f, lat_f) for poly in region.polygons):
            return region.id
    return None


def list_regions() -> list[dict]:
    """Filter ro'yxati uchun `[{id, name}]` — nom bo'yicha tartiblangan, Toshkent sh. birinchi."""
    items = [{"id": r.id, "name": r.name} for r in _load()]
    items.sort(key=lambda r: (r["id"] != 14, r["name"]))
    return items


def region_name(region_id: Optional[int]) -> Optional[str]:
    if region_id is None:
        return None
    for r in _load():
        if r.id == region_id:
            return r.name
    return None
