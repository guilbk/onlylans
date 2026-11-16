"""Hotspots and demand surges of a shift (CONTRACT section 4, K1 brief). Stub for data v0."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def hot_and_surges(
    trips: Sequence[Any], orders: Sequence[Sequence[Any]], unit_m: int
) -> tuple[list[dict], list[dict]]:
    """Return (hot, surges) for a shift; both empty in data v0."""
    return [], []
