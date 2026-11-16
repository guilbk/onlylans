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
MAP_W_M = 15000  # map width, metres
MAP_H_M = 19000  # map height, metres
HOME_LON = -8.6112
HOME_LAT = 41.1481
HOME = (9110.0, 12443.0)  # metres, player start (Aliados)

M_PER_KM = 1000.0  # metres in a kilometre
CENTS = 100  # cents in a euro

MIN_POINTS = 4  # a trip needs at least this many GPS points
MAX_POINTS = 240  # ... and at most this many (one point per 15 s, i.e. 1 hour)
MIN_PATH_KM = 0.8  # shortest accepted path along the polyline, km
MAX_PATH_KM = 30.0  # longest accepted path along the polyline, km
MAX_STEP_M = 625.0  # largest accepted gap between two consecutive points, metres
MIN_STRAIGHT_KM = 0.3  # shortest accepted first-to-last distance, km

FARE_BASE = 3.25  # flag fall, EUR
FARE_PER_KM = 0.50  # EUR per km
FARE_NIGHT_FACTOR = 1.2  # night multiplier
NIGHT_FROM = 22  # first night hour (local, inclusive)
NIGHT_TO = 5  # last night hour (local, inclusive)


def proj(lon: float, lat: float) -> tuple[float, float]:
    """Convert lon/lat degrees to map-frame metres.

    Args:
        lon: Longitude, degrees.
        lat: Latitude, degrees.

    Returns:
        ``(x, y)`` in metres from the north-west corner (x east, y south).
    """
    return (lon - LON0) * M_LON, (LAT0 - lat) * M_LAT


def unproj(x: float, y: float) -> tuple[float, float]:
    """Convert map-frame metres to lon/lat degrees (inverse of :func:`proj`).

    Args:
        x: Metres east of the map origin.
        y: Metres south of the map origin.

    Returns:
        ``(lon, lat)`` in degrees.
    """
    return x / M_LON + LON0, LAT0 - y / M_LAT


def in_map(lon: float, lat: float) -> bool:
    """Tell whether a lon/lat point lies inside the map rectangle.

    Args:
        lon: Longitude, degrees.
        lat: Latitude, degrees.

    Returns:
        True when 0 <= x <= 15000 m and 0 <= y <= 19000 m in the map frame.
    """
    x, y = proj(lon, lat)
    return 0 <= x <= MAP_W_M and 0 <= y <= MAP_H_M


def haversine(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Compute the great-circle distance between two lon/lat points.

    Args:
        lon1: Longitude of the first point, degrees.
        lat1: Latitude of the first point, degrees.
        lon2: Longitude of the second point, degrees.
        lat2: Latitude of the second point, degrees.

    Returns:
        Distance in kilometres.
    """
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_EARTH_KM * math.asin(math.sqrt(a))


def path_km(pts: Sequence[Sequence[float]]) -> float:
    """Measure a lon/lat polyline.

    Args:
        pts: Points ``[lon, lat]`` in degrees.

    Returns:
        Length in kilometres (sum of haversine steps); 0.0 for fewer than two points.
    """
    return sum(haversine(a[0], a[1], b[0], b[1]) for a, b in zip(pts, pts[1:], strict=False))


def _is_point(p: object) -> bool:
    """Tell whether ``p`` is a 2-element sequence of finite numbers (not bool).

    Args:
        p: Any value.

    Returns:
        True for a valid lon/lat pair.
    """
    if not isinstance(p, Sequence) or isinstance(p, str | bytes) or len(p) != 2:
        return False
    return all(
        isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) for v in p
    )


def trip_ok(pts: Sequence[Sequence[float]]) -> bool:
    """Tell whether a lon/lat polyline passes all game filters (CONTRACT section 3).

    Checks: 4..240 points, all valid and in the map, path 0.8..30 km, no step over 625 m,
    straight distance first to last at least 0.3 km.

    Args:
        pts: Points ``[lon, lat]`` in degrees.

    Returns:
        True when every check passes.
    """
    if not MIN_POINTS <= len(pts) <= MAX_POINTS:
        return False
    if not all(_is_point(p) and in_map(p[0], p[1]) for p in pts):
        return False
    steps = [
        haversine(a[0], a[1], b[0], b[1]) * M_PER_KM for a, b in zip(pts, pts[1:], strict=False)
    ]
    if max(steps) > MAX_STEP_M:
        return False
    if not MIN_PATH_KM <= sum(steps) / M_PER_KM <= MAX_PATH_KM:
        return False
    return haversine(pts[0][0], pts[0][1], pts[-1][0], pts[-1][1]) >= MIN_STRAIGHT_KM


def _seg_dist(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    """Measure the distance from a point to a segment.

    Args:
        p: The point.
        a: First end of the segment.
        b: Second end of the segment.

    Returns:
        Distance in the unit of the inputs (metres when called from :func:`rdp`).
    """
    dx, dy = b[0] - a[0], b[1] - a[1]
    len2 = dx * dx + dy * dy
    if len2 == 0.0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def rdp(pts: Sequence[tuple[float, float]], tol_m: float) -> list[tuple[float, float]]:
    """Simplify a polyline with Ramer-Douglas-Peucker; the first and last points are kept.

    Args:
        pts: Points ``(x, y)`` in metres.
        tol_m: Points closer than this to the simplified line are dropped, metres.

    Returns:
        The kept points, in order, in metres.
    """
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
    """Tell whether a local hour is night.

    Args:
        hour: Local hour of day, 0..23.

    Returns:
        True for 22..23 and 0..5.
    """
    return hour >= NIGHT_FROM or hour <= NIGHT_TO


def fare(km: float, night: bool) -> float:
    """Compute the fare of a trip: (3.25 + 0.50 per km), times 1.2 at night.

    Args:
        km: Trip length, kilometres.
        night: Whether the night factor applies.

    Returns:
        Fare in EUR, rounded half-up to cents.
    """
    value = (FARE_BASE + FARE_PER_KM * km) * (FARE_NIGHT_FACTOR if night else 1.0)
    return math.floor(value * CENTS + 0.5) / CENTS
