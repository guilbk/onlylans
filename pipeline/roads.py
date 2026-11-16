"""Road graph from the week's taxi traces (CONTRACT section 5).

Usage: ``python -m pipeline.roads [--week data/work/week.csv] [--out game/roads.json]``

Steps: trips -> 8 m raster (pixels hit by at least 3 trips) -> closing -> skeleton -> pixel graph
-> spur pruning -> largest component -> simplified polylines -> compact JSON in 2.5 m units.
Pixel indices are ``(row, col)`` = ``(y, x)``; all map coordinates are metres in the map frame.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from pipeline import geo

DEFAULT_WEEK = Path("data/work/week.csv")
DEFAULT_OUT = Path("game/roads.json")
POLYLINE_COLUMN = "POLYLINE"

# The polyline column holds long JSON strings; lift the csv module's default field limit.
CSV_FIELD_LIMIT = 1 << 27


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
