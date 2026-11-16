"""Hotspots and demand surges of one shift (CONTRACT section 4, names from section 9).

Input is the list of compact orders of a shift (only ``t`` game seconds and the pickup point in
map units are read). Internally everything is in metres of the map frame (section 3).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np
from scipy.ndimage import gaussian_filter

from pipeline import geo

PLACES: tuple[tuple[str, float, float], ...] = (
    ("Aliados", -8.6112, 41.1481),
    ("Bolhão", -8.6062, 41.1494),
    ("São Bento", -8.6104, 41.1456),
    ("Campanhã", -8.5856, 41.1487),
    ("Casa da Música", -8.6307, 41.1588),
    ("Cedofeita", -8.6200, 41.1520),
    ("Hospital São João", -8.6014, 41.1827),
    ("Estádio do Dragão", -8.5835, 41.1618),
    ("Castelo do Queijo", -8.6890, 41.1690),
    ("Aeroporto", -8.6814, 41.2481),
    ("Santo Ovídio", -8.6040, 41.1170),
    ("Ribeira", -8.6129, 41.1406),
    ("Trindade", -8.6094, 41.1511),
    ("Clérigos", -8.6146, 41.1459),
    ("Bonfim", -8.5930, 41.1480),
    ("Boavista", -8.6340, 41.1620),
    ("Marquês", -8.6054, 41.1576),
    ("Asprela / університет", -8.5963, 41.1783),
    ("Foz", -8.6760, 41.1500),
    ("Matosinhos", -8.6910, 41.1823),
    ("Gaia (Cais)", -8.6160, 41.1370),
    ("Campo 24 de Agosto", -8.5990, 41.1495),
)

CELL_M = 500.0  # density grid cell size, metres
BLUR_SIGMA = 1.0  # Gaussian blur of the density grid, cells
HOT_MIN_SEP_M = 1200.0  # two hotspot peaks are at least this far apart, metres
HOT_MAX = 10  # at most this many hotspots per shift
HOT_MIN = 6  # peaks below the relative threshold are kept until this many exist
HOT_REL_MIN = 0.15  # a later peak must reach this share of the strongest peak
HOT_CENTRE_M = 700.0  # pickups within this radius of a peak define the hotspot centre, metres
W_DECIMALS = 3  # decimals of a hotspot's share ``w``
NAME_EXACT_M = 900.0  # a point this close to a place gets its plain name, metres
NAME_AREA_M = 2500.0  # ... this close gets "район <place>", metres
NAME_FAR = "околиця"  # name of a point far from every place

BIN_S = 150  # time bin of the surge histogram, game seconds
WINDOW_S = 750  # length of a surge window, game seconds
SHIFT_S = geo.SHIFT_S
T0_MIN_S = 150  # no surge starts before this, game seconds
SURGE_R_M = 700.0  # surge circle radius, metres
SURGE_MAX = 6  # at most this many surges per shift
SURGE_MIN_RATE, SURGE_MIN_N = 2.0, 5  # strict: window count >= rate * expected, and >= n
SURGE_MIN_RATE_RELAXED, SURGE_MIN_N_RELAXED = 1.6, 4  # used if the strict pass finds too few
SURGE_MIN_COUNT = 3  # fewer surges than this triggers the relaxed pass
CIRCLE_MIN_TOTAL = 10  # a circle needs this many pickups in the shift to have a stable rate

Point = tuple[float, float]


def place_points() -> list[tuple[str, float, float]]:
    """List the named places in the map frame.

    Returns:
        ``(name, x_m, y_m)`` per place, positions in metres.
    """
    return [(n, *geo.proj(lon, lat)) for n, lon, lat in PLACES]


def place_name(x_m: float, y_m: float) -> str:
    """Name a map point after the nearest place.

    Args:
        x_m: Map x, metres.
        y_m: Map y, metres.

    Returns:
        The place within 900 m, else ``район <nearest>`` within 2500 m, else ``околиця``.
    """
    best_name, best_d = NAME_FAR, math.inf
    for name, px, py in place_points():
        d = math.hypot(px - x_m, py - y_m)
        if d < best_d:
            best_name, best_d = name, d
    if best_d <= NAME_EXACT_M:
        return best_name
    if best_d <= NAME_AREA_M:
        return f"район {best_name}"
    return NAME_FAR


def pickups_m(orders: Sequence[Sequence[Any]], unit_m: int) -> np.ndarray:
    """Extract the pickups of compact orders.

    Args:
        orders: Compact orders; ``o[0]`` is the time, ``o[1]``/``o[2]`` the pickup in map units.
        unit_m: Metres per map unit.

    Returns:
        Float array of shape ``(n, 3)``: x in metres, y in metres, t in game seconds.
    """
    arr = np.array([(o[1] * unit_m, o[2] * unit_m, o[0]) for o in orders], dtype=float)
    return arr.reshape(-1, 3)


def density_grid(xy: np.ndarray) -> np.ndarray:
    """Count pickups per grid cell and blur the counts.

    Args:
        xy: Pickups ``(n, >=2)``; columns x, y in metres.

    Returns:
        Array ``(rows, cols)`` of pickups per 500 m cell, blurred with sigma = 1 cell.
    """
    cols = math.ceil(geo.MAP_W_M / CELL_M)
    rows = math.ceil(geo.MAP_H_M / CELL_M)
    ix = np.clip((xy[:, 0] // CELL_M).astype(int), 0, cols - 1)
    iy = np.clip((xy[:, 1] // CELL_M).astype(int), 0, rows - 1)
    grid = np.zeros((rows, cols))
    np.add.at(grid, (iy, ix), 1.0)
    return gaussian_filter(grid, sigma=BLUR_SIGMA, mode="constant")


def find_peaks(grid: np.ndarray) -> list[Point]:
    """Pick the strongest peaks of the blurred grid, greedily.

    Stops at 10 peaks, or at a peak under 15 % of the maximum once 6 peaks are found.

    Args:
        grid: Blurred density, shape ``(rows, cols)``, cells of 500 m.

    Returns:
        Peak positions ``(x, y)`` as cell centres in metres, at least 1200 m apart.
    """
    work = grid.copy()
    top = float(work.max()) if work.size else 0.0
    rows, cols = work.shape
    cy, cx = np.mgrid[0:rows, 0:cols]
    centres_x, centres_y = (cx + 0.5) * CELL_M, (cy + 0.5) * CELL_M
    peaks: list[Point] = []
    while len(peaks) < HOT_MAX and top > 0:
        i = int(np.argmax(work))
        value = float(work.flat[i])
        if value <= 0 or (len(peaks) >= HOT_MIN and value < HOT_REL_MIN * top):
            break
        px, py = float(centres_x.flat[i]), float(centres_y.flat[i])
        peaks.append((px, py))
        work[np.hypot(centres_x - px, centres_y - py) < HOT_MIN_SEP_M] = 0.0
    return peaks


def hotspots(xy: np.ndarray, unit_m: int) -> list[dict]:
    """Build the hotspots of a shift.

    Args:
        xy: Pickups ``(n, >=2)``; columns x, y in metres.
        unit_m: Metres per map unit.

    Returns:
        Up to 10 dicts ``{x, y, w, name}``: centre in map units, ``w`` the share (0..1) of the
        shift's pickups within 700 m of the peak, ``name`` the nearest place.
    """
    if len(xy) == 0:
        return []
    out = []
    for px, py in find_peaks(density_grid(xy)):
        near = xy[np.hypot(xy[:, 0] - px, xy[:, 1] - py) <= HOT_CENTRE_M]
        if len(near) == 0:
            continue  # a peak made only by blur: nothing to point at
        cx, cy = float(near[:, 0].mean()), float(near[:, 1].mean())
        out.append(
            {
                "x": round(cx / unit_m),
                "y": round(cy / unit_m),
                "w": round(len(near) / len(xy), W_DECIMALS),
                "name": place_name(cx, cy),
            }
        )
    return out


def circle_candidates(xy: np.ndarray) -> list[Point]:
    """List the cell centres whose 700 m circle has enough pickups to define a rate.

    Args:
        xy: Pickups ``(n, >=2)``; columns x, y in metres.

    Returns:
        Circle centres ``(x, y)`` in metres.
    """
    cols = math.ceil(geo.MAP_W_M / CELL_M)
    rows = math.ceil(geo.MAP_H_M / CELL_M)
    cells = [((c + 0.5) * CELL_M, (r + 0.5) * CELL_M) for r in range(rows) for c in range(cols)]
    return [
        (cx, cy)
        for cx, cy in cells
        if np.count_nonzero(np.hypot(xy[:, 0] - cx, xy[:, 1] - cy) <= SURGE_R_M) >= CIRCLE_MIN_TOTAL
    ]


def best_window(times: np.ndarray, min_rate: float, min_n: int) -> list[tuple[float, int, int]]:
    """Find the surge windows of one circle.

    Windows are 750 s long, start on 150 s bins at t0 >= 150 and end at t1 <= 7200. The expected
    count lambda is the circle's average rate over [150, 7200] times 750 s.

    Args:
        times: Pickup times inside the circle, game seconds.
        min_rate: A window needs at least ``min_rate * lambda`` pickups.
        min_n: ... and at least this many pickups.

    Returns:
        ``(z, t0, n)`` per qualifying window: z-score, start (game seconds), pickup count.
    """
    nbins = SHIFT_S // BIN_S
    hist = np.bincount((times // BIN_S).astype(int).clip(0, nbins - 1), minlength=nbins)
    span = WINDOW_S // BIN_S
    lam = float(hist[T0_MIN_S // BIN_S :].sum()) * WINDOW_S / (SHIFT_S - T0_MIN_S)
    found = []
    if lam <= 0:
        return found
    for k in range(T0_MIN_S // BIN_S, nbins - span + 1):
        n = int(hist[k : k + span].sum())
        if n >= min_n and n >= min_rate * lam:
            found.append(((n - lam) / math.sqrt(lam), k * BIN_S, n))
    return found


def collect_surges(xy: np.ndarray, min_rate: float, min_n: int) -> list[tuple]:
    """Collect the qualifying surge windows of every circle.

    Args:
        xy: Pickups ``(n, 3)``: x, y in metres, t in game seconds.
        min_rate: Rate threshold, see :func:`best_window`.
        min_n: Count threshold, see :func:`best_window`.

    Returns:
        Tuples ``(-z, t0, cx, cy, n)`` (t0 in game seconds, centre in metres), best z first.
    """
    cands = []
    for cx, cy in circle_candidates(xy):
        inside = np.hypot(xy[:, 0] - cx, xy[:, 1] - cy) <= SURGE_R_M
        for z, t0, n in best_window(xy[inside, 2], min_rate, min_n):
            cands.append((-z, t0, cx, cy, n))
    cands.sort()
    return cands


def pick_surges(xy: np.ndarray, min_rate: float, min_n: int, unit_m: int) -> list[dict]:
    """Choose time-disjoint surges greedily, best z first, at most 6.

    Args:
        xy: Pickups ``(n, 3)``: x, y in metres, t in game seconds.
        min_rate: Rate threshold, see :func:`best_window`.
        min_n: Count threshold, see :func:`best_window`.
        unit_m: Metres per map unit.

    Returns:
        Surge dicts ``{x, y, r, t0, t1, n, name}`` (x, y, r in map units, times in game seconds),
        sorted by start time.
    """
    chosen: list[dict] = []
    for _negz, t0, cx, cy, _n in collect_surges(xy, min_rate, min_n):
        t1 = t0 + WINDOW_S
        if any(t0 < s["t1"] and s["t0"] < t1 for s in chosen):
            continue
        sel = (
            (np.hypot(xy[:, 0] - cx, xy[:, 1] - cy) <= SURGE_R_M)
            & (xy[:, 2] >= t0)
            & (xy[:, 2] < t1)
        )
        mx, my = float(xy[sel, 0].mean()), float(xy[sel, 1].mean())
        chosen.append(
            {
                "x": round(mx / unit_m),
                "y": round(my / unit_m),
                "r": round(SURGE_R_M / unit_m),
                "t0": t0,
                "t1": t1,
                "n": int(sel.sum()),
                "name": place_name(mx, my),
            }
        )
        if len(chosen) == SURGE_MAX:
            break
    return sorted(chosen, key=lambda s: (s["t0"], s["x"], s["y"]))


def surges(xy: np.ndarray, unit_m: int) -> list[dict]:
    """Find the demand surges of a shift, relaxing the thresholds if fewer than 3 are found.

    Args:
        xy: Pickups ``(n, 3)``: x, y in metres, t in game seconds.
        unit_m: Metres per map unit.

    Returns:
        Surge dicts ``{x, y, r, t0, t1, n, name}`` (x, y, r in map units, times in game seconds).
    """
    if len(xy) == 0:
        return []
    found = pick_surges(xy, SURGE_MIN_RATE, SURGE_MIN_N, unit_m)
    if len(found) < SURGE_MIN_COUNT:
        found = pick_surges(xy, SURGE_MIN_RATE_RELAXED, SURGE_MIN_N_RELAXED, unit_m)
    return found


def hot_and_surges(orders: Sequence[Sequence[Any]], unit_m: int) -> tuple[list[dict], list[dict]]:
    """Compute hotspots and surges of a shift.

    Args:
        orders: Compact orders of the shift (time in game seconds, pickup in map units).
        unit_m: Metres per map unit.

    Returns:
        ``(hot, surges)`` as returned by :func:`hotspots` and :func:`surges`.
    """
    xy = pickups_m(orders, unit_m)
    return hotspots(xy, unit_m), surges(xy, unit_m)
