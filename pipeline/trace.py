"""Shared trace code of the raster tools ``streets.py`` and ``roads.py``.

Both turn the week's taxi traces into a per-pixel trip count on the same map frame: read the
POLYLINE column, project to metres, sample each trip densely and mark the pixels it touches.
They differ in one rule only: ``streets.py`` drops samples that fall off the map, ``roads.py``
clips them to the nearest edge pixel (``clip`` in :func:`trip_pixels`). Pixel indices are
``(row, col)`` = ``(y, x)``; all map coordinates are metres in the map frame.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from pipeline import geo

POLYLINE_COLUMN = "POLYLINE"
SAMPLE_FRACTION = 0.5  # samples along a segment are this many pixels apart

Trip = NDArray[np.float64]


@dataclass(frozen=True)
class Grid:
    """Raster geometry: ``width`` x ``height`` pixels of ``cell_m`` metres, origin at (0, 0)."""

    width: int
    height: int
    cell_m: float


def map_grid(m_per_px: float) -> Grid:
    """Return the grid that covers the whole game map (CONTRACT section 3).

    Args:
        m_per_px: Pixel size in metres, greater than zero.

    Returns:
        Grid with ``ceil(MAP_W_M / m_per_px)`` columns and ``ceil(MAP_H_M / m_per_px)`` rows.
    """
    return Grid(
        math.ceil(geo.MAP_W_M / m_per_px), math.ceil(geo.MAP_H_M / m_per_px), float(m_per_px)
    )


def parse_polyline(text: str) -> list[list[float]] | None:
    """Parse a POLYLINE cell.

    Args:
        text: JSON text ``[[lon, lat], ...]``.

    Returns:
        The list of lon/lat points, or None if the text is not a JSON list.
    """
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, list) else None


def project_trip(pts: list[list[float]]) -> Trip:
    """Project a lon/lat polyline to map-frame metres.

    Args:
        pts: Points ``[lon, lat]`` in degrees.

    Returns:
        Array of shape ``(n, 2)`` with columns x, y in metres.
    """
    return np.array([geo.proj(p[0], p[1]) for p in pts], dtype=np.float64)


def load_trips(week_csv: Path) -> list[Trip]:
    """Read the week file and keep the trips that pass ``geo.trip_ok``.

    The caller sets the csv field limit once (``raw.set_csv_limit``).

    Args:
        week_csv: CSV with a POLYLINE column (one lon/lat point per 15 s).

    Returns:
        One ``(n, 2)`` metre array per accepted trip, in file order.
    """
    trips: list[Trip] = []
    with week_csv.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            pts = parse_polyline(row[POLYLINE_COLUMN])
            if pts is not None and geo.trip_ok(pts):
                trips.append(project_trip(pts))
    return trips


def sample_polyline(trip: Trip, step_m: float) -> Trip:
    """Sample a polyline so that consecutive samples are at most ``step_m`` apart.

    Args:
        trip: Array ``(n, 2)`` of x, y in metres, ``n >= 1``.
        step_m: Maximum spacing between samples, metres, greater than zero.

    Returns:
        Array ``(k, 2)`` in metres containing every vertex and the points between them.
    """
    if len(trip) < 2:
        return trip.copy()
    seg = np.diff(trip, axis=0)
    counts = np.maximum(1, np.ceil(np.hypot(seg[:, 0], seg[:, 1]) / step_m)).astype(np.int64)
    starts = np.repeat(np.arange(len(seg)), counts)
    first = np.cumsum(counts) - counts
    frac = (np.arange(int(counts.sum())) - np.repeat(first, counts)) / np.repeat(counts, counts)
    samples = trip[starts] + seg[starts] * frac[:, None]
    return np.vstack([samples, trip[-1:]])


def trip_pixels(trip: Trip, grid: Grid, *, clip: bool) -> NDArray[np.int64]:
    """List the flat pixel indices a trip passes through, each once.

    The polyline is sampled every half pixel, so consecutive samples are 8-connected pixels.

    Args:
        trip: Array ``(n, 2)`` of x, y in metres.
        grid: Raster geometry.
        clip: True moves a sample off the map to the nearest edge pixel; False drops it.

    Returns:
        Sorted unique indices ``row * grid.width + col``.
    """
    samples = sample_polyline(trip, grid.cell_m * SAMPLE_FRACTION)
    cols = np.floor(samples[:, 0] / grid.cell_m).astype(np.int64)
    rows = np.floor(samples[:, 1] / grid.cell_m).astype(np.int64)
    if clip:
        cols = np.clip(cols, 0, grid.width - 1)
        rows = np.clip(rows, 0, grid.height - 1)
    else:
        inside = (cols >= 0) & (cols < grid.width) & (rows >= 0) & (rows < grid.height)
        cols, rows = cols[inside], rows[inside]
    return np.unique(rows * grid.width + cols)
