import math
from typing import Optional, Sequence

import numpy as np
import shapely

# Bir gradus kenglik (latitude) taxminan 111.32 km ga teng
_KM_PER_DEGREE = 111.32


def simplify_polyline(
    points: Sequence[tuple[float, float]], tolerance_m: float = 15.0
) -> list[tuple[float, float]]:
    """Douglas-Peucker: chiziq shaklini saqlagan holda ortiqcha nuqtalarni olib tashlaydi.

    OSRM `overview=full` juda ko'p nuqta qaytaradi (300 km yo'l uchun ~3000 ta, ~68 KB JSON).
    `overview=simplified` esa aksincha juda qo'pol (shahar ichidagi 7 km yo'l uchun atigi
    20 ta nuqta — burilishlarni "kesib" o'tadi). Shuning uchun to'liq geometriya olinib,
    shu yerda ko'rsatish uchun yetarli aniqlikda soddalashtiriladi: qisqa marshrutlar
    tafsilotini yo'qotmaydi, uzunlari esa keraksiz nuqtalardan tozalanadi.

    points: [(latitude, longitude), ...]. tolerance_m: chiziqdan ruxsat etilgan maksimal
    og'ish (metr) — undan kam og'adigan nuqtalar tashlab yuboriladi.
    """
    if len(points) <= 2:
        return list(points)
    arr = np.asarray(points, dtype=float)
    return simplify_lonlat_array(arr[:, ::-1], tolerance_m)


def simplify_lonlat_array(lonlat: "np.ndarray", tolerance_m: float = 15.0) -> list[tuple[float, float]]:
    """`simplify_polyline` ning o'zi, lekin kirish OSRM tartibida: (N, 2) massiv [lon, lat].

    Natija [(latitude, longitude), ...] — Yandex Maps shu tartibni kutadi.

    Unumdorlik (yuklama testi, 2026-11-19): sof Python'dagi Douglas-Peucker narx
    hisoblashda web CPU'sining ~30% ini yeyardi. Endi nuqtalar numpy bilan metrlik
    tekislikka o'tkaziladi va soddalashtirishni GEOS (shapely, C) bajaradi — algoritm
    o'sha (kesmagacha masofa, `preserve_topology=False` = klassik Douglas-Peucker).
    """
    n = len(lonlat)
    if n <= 2:
        return [(float(lat), float(lon)) for lon, lat in lonlat]

    # Gradusni taxminan metrga o'tkazish uchun masshtab. Uzunlik gradusi qutbga
    # yaqinlashgan sari qisqaradi, shuning uchun o'rtacha kenglik bo'yicha cos() olinadi.
    lat_scale = _KM_PER_DEGREE * 1000
    lon_scale = lat_scale * math.cos(math.radians(float(lonlat[:, 1].mean())))
    scale = np.array([lon_scale, lat_scale])

    simplified = shapely.simplify(
        shapely.linestrings(lonlat * scale), tolerance_m, preserve_topology=False
    )
    # Metrdan gradusga qaytishda float "shovqini" qoladi (41.311264 → 41.311263999999994).
    # OSRM koordinatalari 6 xonali, shuning uchun yaxlitlash asl qiymatni aynan tiklaydi
    # (GEOS faqat mavjud nuqtalarni qoldiradi, yangisini yaratmaydi).
    kept = np.round(shapely.get_coordinates(simplified) / scale, 6)
    return [(lat, lon) for lon, lat in kept.tolist()]


def lonlat_to_wkt(lonlat: "np.ndarray") -> str:
    """(N, 2) [lon, lat] massivdan PostGIS uchun "LINESTRING(lon lat, ...)" (to'liq aniqlik)."""
    return shapely.to_wkt(shapely.linestrings(lonlat), rounding_precision=-1, trim=True)


def calculate_distance_km(lat1: Optional[float], lon1: Optional[float], lat2: Optional[float], lon2: Optional[float]) -> Optional[float]:
    """
    Calculate the great circle distance in kilometers between two points 
    on the earth (specified in decimal degrees) using haversine formula.
    Returns None if any of the coordinates is None.
    """
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None

    # Convert decimal degrees to radians 
    lon1_rad, lat1_rad, lon2_rad, lat2_rad = map(math.radians, [lon1, lat1, lon2, lat2])

    # Haversine formula 
    dlon = lon2_rad - lon1_rad 
    dlat = lat2_rad - lat1_rad 
    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a)) 
    r = 6371 # Radius of earth in kilometers
    return c * r
