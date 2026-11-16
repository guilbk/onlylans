"""Road graph from the week's taxi traces (CONTRACT section 5).

Usage: ``python -m pipeline.roads [--week data/work/week.csv] [--out game/roads.json]``

Steps: trips -> 8 m raster (pixels hit by at least 3 trips) -> closing -> skeleton -> pixel graph
-> spur pruning -> largest component -> simplified polylines -> compact JSON in 2.5 m units.
Pixel indices are ``(row, col)`` = ``(y, x)``; all map coordinates are metres in the map frame.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from skimage.morphology import closing, skeletonize

from pipeline import geo

DEFAULT_WEEK = Path("data/work/week.csv")
DEFAULT_OUT = Path("game/roads.json")
POLYLINE_COLUMN = "POLYLINE"

# The polyline column holds long JSON strings; lift the csv module's default field limit.
CSV_FIELD_LIMIT = 1 << 27

CELL_M = 8.0  # raster pixel size, metres
MIN_TRIPS = 3  # a pixel is road if at least this many different trips touch it
SAMPLE_STEP_M = CELL_M / 2  # spacing of the points sampled along a segment, metres


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


def project_trip(pts: list[list[float]]) -> np.ndarray:
    """Project a lon/lat polyline to map-frame metres.

    Args:
        pts: Points ``[lon, lat]`` in degrees.

    Returns:
        Array of shape ``(n, 2)`` with columns x, y in metres.
    """
    return np.array([geo.proj(p[0], p[1]) for p in pts], dtype=np.float64)


def load_trips(week_csv: Path) -> list[np.ndarray]:
    """Read the week file and keep the trips that pass ``geo.trip_ok``.

    Args:
        week_csv: CSV with a POLYLINE column (one lon/lat point per 15 s).

    Returns:
        One ``(n, 2)`` metre array per accepted trip, in file order.
    """
    csv.field_size_limit(CSV_FIELD_LIMIT)
    trips: list[np.ndarray] = []
    with week_csv.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            pts = parse_polyline(row[POLYLINE_COLUMN])
            if pts is not None and geo.trip_ok(pts):
                trips.append(project_trip(pts))
    return trips


@dataclass(frozen=True)
class Grid:
    """Raster geometry: ``width`` x ``height`` pixels of ``cell_m`` metres, origin at (0, 0)."""

    width: int
    height: int
    cell_m: float = CELL_M


def map_grid() -> Grid:
    """Return the grid that covers the whole game map (CONTRACT section 3)."""
    return Grid(math.ceil(geo.MAP_W_M / CELL_M), math.ceil(geo.MAP_H_M / CELL_M))


def trip_pixels(trip: np.ndarray, grid: Grid) -> np.ndarray:
    """List the pixels a trip passes through, each once.

    The polyline is sampled every ``SAMPLE_STEP_M`` metres, so consecutive samples are
    8-connected pixels.

    Args:
        trip: Array ``(n, 2)`` of x, y in metres.
        grid: Raster geometry.

    Returns:
        Sorted unique flat pixel indices ``row * width + col``.
    """
    seg = np.diff(trip, axis=0)
    steps = np.maximum(1, np.ceil(np.hypot(seg[:, 0], seg[:, 1]) / SAMPLE_STEP_M)).astype(int)
    seg_id = np.repeat(np.arange(len(seg)), steps)
    first = np.repeat(np.cumsum(steps) - steps, steps)
    frac = (np.arange(steps.sum()) - first) / np.repeat(steps, steps)
    pts = np.vstack([trip[seg_id] + frac[:, None] * seg[seg_id], trip[-1:]])
    col = np.clip((pts[:, 0] // grid.cell_m).astype(int), 0, grid.width - 1)
    row = np.clip((pts[:, 1] // grid.cell_m).astype(int), 0, grid.height - 1)
    return np.unique(row * grid.width + col)


def count_trips(trips: list[np.ndarray], grid: Grid) -> np.ndarray:
    """Count, per pixel, how many different trips pass through it.

    Args:
        trips: Metre polylines, each ``(n, 2)``.
        grid: Raster geometry.

    Returns:
        Array ``(height, width)`` of trip counts (a trip adds at most 1 to a pixel).
    """
    counts = np.zeros(grid.width * grid.height, dtype=np.uint16)
    for trip in trips:
        counts[trip_pixels(trip, grid)] += 1
    return counts.reshape(grid.height, grid.width)


def road_mask(counts: np.ndarray, min_trips: int = MIN_TRIPS) -> np.ndarray:
    """Keep the pixels hit by at least ``min_trips`` trips.

    Args:
        counts: Per-pixel trip counts.
        min_trips: Threshold; chords between 15-s points are seen by fewer trips.

    Returns:
        Boolean mask ``(height, width)``.
    """
    return counts >= min_trips


def close_mask(mask: np.ndarray) -> np.ndarray:
    """Binary closing with a 3x3 square, which bridges one-pixel gaps.

    Args:
        mask: Boolean road mask.

    Returns:
        The closed boolean mask.
    """
    return closing(mask.astype(np.uint8), np.ones((3, 3), dtype=np.uint8)).astype(bool)


def thin_mask(mask: np.ndarray) -> np.ndarray:
    """Skeletonize a boolean mask to one-pixel-wide lines.

    Args:
        mask: Boolean road mask.

    Returns:
        Boolean skeleton of the same shape.
    """
    return skeletonize(mask).astype(bool)
