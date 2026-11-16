"""Where real Porto taxi drivers earned, per shift and hour (CONTRACT section 21).

Every real trip of a shift drops its fare on the grid cell of its pickup point. The grid is coarse
(400 m cells), smoothed with a small blur and normalised for each hour. The output keeps only
the cells that are warm enough, as flat ``[gap, value, ...]`` lists: ``gap`` is the distance in
cells from the previous warm cell (row-major, ``row * cols + col``), ``value`` is 1..99.

Run ``python -m pipeline.heat`` to write ``game/heat.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

DATA_DEFAULT = Path("game/game_data.json")
OUT_DEFAULT = Path("game/heat.json")

CELL_M = 400  # grid cell side, metres
HOUR_S = 3600  # game seconds in one real hour
HOURS = 2  # every shift lasts two hours
KERNEL = (0.25, 0.5, 0.25)  # separable blur, one cell each way
MIN_VALUE = 8  # cells below this (of 99) are dropped
SCALE = 99

Grid = list[list[float]]


def grid_size(bounds: Sequence[int], unit_m: int, cell_m: int = CELL_M) -> tuple[int, int]:
    """Number of grid columns and rows that cover the map.

    Args:
        bounds: Map bounds ``[x0, y0, x1, y1]`` in map units.
        unit_m: Metres per map unit.
        cell_m: Cell side in metres.

    Returns:
        ``(cols, rows)``.
    """
    cols = -(-(bounds[2] - bounds[0]) * unit_m // cell_m)
    rows = -(-(bounds[3] - bounds[1]) * unit_m // cell_m)
    return int(cols), int(rows)


def hour_of(t: float) -> int:
    """Hour of the shift (0 or 1) of a pickup time.

    Args:
        t: Game seconds from the shift start.

    Returns:
        The hour index, clamped to ``0..HOURS-1``.
    """
    return min(max(int(t // HOUR_S), 0), HOURS - 1)


def bin_fares(
    orders: Sequence[Sequence[Any]], hour: int, cols: int, rows: int, unit_m: int
) -> Grid:
    """Sum the fares of one hour's trips on the grid, by pickup cell.

    Args:
        orders: Compact orders of the shift (CONTRACT section 4; index 0 time, 1-2 pickup, 8 fare).
        hour: Hour of the shift to take.
        cols: Grid columns.
        rows: Grid rows.
        unit_m: Metres per map unit.

    Returns:
        ``rows`` lists of ``cols`` floats.
    """
    grid = [[0.0] * cols for _ in range(rows)]
    for o in orders:
        if hour_of(o[0]) != hour:
            continue
        c = min(max(int(o[1] * unit_m // CELL_M), 0), cols - 1)
        r = min(max(int(o[2] * unit_m // CELL_M), 0), rows - 1)
        grid[r][c] += float(o[8])
    return grid


def blur(grid: Grid, passes: int = 2) -> Grid:
    """Smooth a grid with a small separable kernel, several times.

    Args:
        grid: Rows of floats.
        passes: How many times to blur.

    Returns:
        A new, smoothed grid of the same size.
    """
    for _ in range(passes):
        rows, cols = len(grid), len(grid[0]) if grid else 0
        horiz = [[0.0] * cols for _ in range(rows)]
        for r in range(rows):
            for c in range(cols):
                horiz[r][c] = sum(
                    w * grid[r][c + d - 1] for d, w in enumerate(KERNEL) if 0 <= c + d - 1 < cols
                )
        grid = [[0.0] * cols for _ in range(rows)]
        for r in range(rows):
            for c in range(cols):
                grid[r][c] = sum(
                    w * horiz[r + d - 1][c] for d, w in enumerate(KERNEL) if 0 <= r + d - 1 < rows
                )
    return grid


def pack(grid: Grid) -> list[int]:
    """Normalise a grid to its maximum and list the warm cells.

    Args:
        grid: Smoothed rows of floats.

    Returns:
        Flat ``[gap, value, ...]`` in row-major order (``gap`` counts cells from the previous warm
        cell, from cell 0 for the first), value ``1..99``, cells below ``MIN_VALUE`` left out;
        empty if the grid is empty.
    """
    top = max((v for row in grid for v in row), default=0.0)
    out: list[int] = []
    if top <= 0:
        return out
    last = 0
    for i, v in enumerate(v for row in grid for v in row):
        q = round(v / top * SCALE)
        if q >= MIN_VALUE:
            out += [i - last, q]
            last = i
    return out


def shift_heat(sh: dict[str, Any], cols: int, rows: int, unit_m: int) -> list[list[int]]:
    """Packed heat of every hour of one shift.

    Args:
        sh: Shift object of ``game_data.json``.
        cols: Grid columns.
        rows: Grid rows.
        unit_m: Metres per map unit.

    Returns:
        One packed list per hour.
    """
    return [pack(blur(bin_fares(sh["orders"], h, cols, rows, unit_m))) for h in range(HOURS)]


def build_heat(data: dict[str, Any]) -> dict[str, Any]:
    """Heat of all shifts.

    Args:
        data: Parsed ``game_data.json``.

    Returns:
        ``{"version", "cell_m", "cols", "rows", "shifts": {id: [hour0, hour1]}}``.
    """
    unit_m = data["unit_m"]
    cols, rows = grid_size(data["bounds"], unit_m)
    shifts = {sh["id"]: shift_heat(sh, cols, rows, unit_m) for sh in data["shifts"]}
    return {"version": 1, "cell_m": CELL_M, "cols": cols, "rows": rows, "shifts": shifts}


def main(argv: list[str] | None = None) -> int:
    """Command line entry point: write ``game/heat.json``.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        0 on success, 1 if the data file is missing.
    """
    ap = argparse.ArgumentParser(description="Compute the earnings heat map of each shift hour")
    ap.add_argument("--data", type=Path, default=DATA_DEFAULT)
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = ap.parse_args(argv)
    if not args.data.is_file():
        print(f"data file not found: {args.data}", file=sys.stderr)
        return 1
    doc = build_heat(json.loads(args.data.read_text(encoding="utf-8")))
    text = json.dumps(doc, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({len(text)} bytes, {len(doc['shifts'])} shifts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
