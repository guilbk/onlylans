"""Map projection, distances, trip filter and fare rules (CONTRACT section 3).

Map frame: origin (0, 0) is the north-west corner of the map, x grows east, y grows south,
the unit is the metre. Distances between lon/lat points are in km unless stated otherwise.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

R_EARTH_KM = 6371.0
LON0 = -8.72
LAT0 = 41.26
LAT_REF = 41.15
M_LAT = 111194.92664455874  # metres per degree of latitude
M_LON = 83728.60524645654  # metres per degree of longitude at LAT_REF
MAP_W_M = 15000
MAP_H_M = 19000
HOME_LON = -8.6112
HOME_LAT = 41.1481
HOME = (9110.0, 12443.0)  # metres, player start (Aliados)

MIN_POINTS = 4
MAX_POINTS = 240
MIN_PATH_KM = 0.8
MAX_PATH_KM = 30.0
MAX_STEP_M = 625.0
MIN_STRAIGHT_KM = 0.3

FARE_BASE = 3.25
FARE_PER_KM = 0.50
FARE_NIGHT_FACTOR = 1.2
NIGHT_FROM = 22
NIGHT_TO = 5


def proj(lon: float, lat: float) -> tuple[float, float]:
    """Convert lon/lat degrees to map-frame metres (x east, y south)."""
    return (lon - LON0) * M_LON, (LAT0 - lat) * M_LAT


def unproj(x: float, y: float) -> tuple[float, float]:
    """Convert map-frame metres to (lon, lat) degrees."""
    return x / M_LON + LON0, LAT0 - y / M_LAT


def in_map(lon: float, lat: float) -> bool:
    """Return True if the lon/lat point lies inside the map rectangle."""
    x, y = proj(lon, lat)
    return 0 <= x <= MAP_W_M and 0 <= y <= MAP_H_M


def haversine(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Return the great-circle distance in km between two lon/lat points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_EARTH_KM * math.asin(math.sqrt(a))


def path_km(pts: Sequence[Sequence[float]]) -> float:
    """Return the length in km along a lon/lat polyline (sum of haversine steps)."""
    return sum(haversine(a[0], a[1], b[0], b[1]) for a, b in zip(pts, pts[1:], strict=False))


def _is_point(p: object) -> bool:
    """Return True if p is a 2-element sequence of finite numbers."""
    if not isinstance(p, Sequence) or isinstance(p, str | bytes) or len(p) != 2:
        return False
    return all(
        isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) for v in p
    )


def trip_ok(pts: Sequence[Sequence[float]]) -> bool:
    """Return True if a lon/lat polyline passes all game filters (CONTRACT section 3).

    Checks: 4..240 points, all valid and in the map, path 0.8..30 km, no step over 625 m,
    straight distance first to last at least 0.3 km.
    """
    if not MIN_POINTS <= len(pts) <= MAX_POINTS:
        return False
    if not all(_is_point(p) and in_map(p[0], p[1]) for p in pts):
        return False
    steps = [haversine(a[0], a[1], b[0], b[1]) * 1000.0 for a, b in zip(pts, pts[1:], strict=False)]
    if max(steps) > MAX_STEP_M:
        return False
    if not MIN_PATH_KM <= sum(steps) / 1000.0 <= MAX_PATH_KM:
        return False
    return haversine(pts[0][0], pts[0][1], pts[-1][0], pts[-1][1]) >= MIN_STRAIGHT_KM


def _seg_dist(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    """Return the distance from point p to segment a-b (any consistent unit)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    len2 = dx * dx + dy * dy
    if len2 == 0.0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def rdp(pts: Sequence[tuple[float, float]], tol_m: float) -> list[tuple[float, float]]:
    """Simplify a polyline given in metres (Ramer-Douglas-Peucker); keeps first and last."""
    n = len(pts)
    if n <= 2:
        return list(pts)
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        lo, hi = stack.pop()
        far, far_d = -1, tol_m
        for i in range(lo + 1, hi):
            d = _seg_dist(pts[i], pts[lo], pts[hi])
            if d > far_d:
                far, far_d = i, d
        if far >= 0:
            keep[far] = True
            stack.append((lo, far))
            stack.append((far, hi))
    return [p for p, k in zip(pts, keep, strict=True) if k]


def night_hour(hour: int) -> bool:
    """Return True if the local hour (0..23) is night: 22..23 or 0..5."""
    return hour >= NIGHT_FROM or hour <= NIGHT_TO


def fare(km: float, night: bool) -> float:
    """Return the fare in EUR: (3.25 + 0.50 km), x1.2 at night, rounded half-up to cents."""
    value = (FARE_BASE + FARE_PER_KM * km) * (FARE_NIGHT_FACTOR if night else 1.0)
    return math.floor(value * 100 + 0.5) / 100
