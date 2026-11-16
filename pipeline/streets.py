"""Street glow image from the week's taxi traces (CONTRACT sections 5, 6 and 14).

Usage: ``python -m pipeline.streets [--week data/work/week.csv] [--out game/streets.png]
[--m-per-px 5]``

Steps: trips -> float accumulator (each pixel counted at most once per trip) -> tone map
(log, clipped at a percentile) -> light cool-blue pixels with alpha from the density ->
optimised PNG. The image covers the whole map; the renderer stretches it over the map and
draws it with ``lighter`` compositing. Pixel indices are ``(row, col)`` = ``(y, x)``; all map
coordinates are metres in the map frame.
"""

from __future__ import annotations

import argparse
import io
import math
import sys
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from pipeline import raw, trace
from pipeline.trace import Grid

DEFAULT_WEEK = Path("data/work/week.csv")
DEFAULT_OUT = Path("game/streets.png")

DEFAULT_M_PER_PX = 5.0  # metres per image pixel
MAX_M_PER_PX = 8.0  # coarsest resolution tried when the size budget is not met
M_PER_PX_STEP = 1.0  # step when raising metres per pixel, metres
MAX_BYTES = 1_200_000  # PNG size budget, bytes

CLIP_PERCENTILE = 99.5  # densities above this percentile of lit pixels map to full glow
STREET_RGB = (0x5A, 0xA9, 0xFF)  # cool blue, CONTRACT section 14
STREET_ALPHA = 0.30  # alpha of the busiest pixels (0..1); the runtime glow caps at 0.18
ALPHA_MAX = 255
PALETTE_SIZE = 256  # palette entries; entry i is the glow colour with alpha i

FloatGrid = NDArray[np.float32]
Alpha = NDArray[np.uint8]


def accumulate(trips: list[NDArray[np.float64]], grid: Grid) -> FloatGrid:
    """Count, for every pixel, how many trips pass through it.

    Args:
        trips: Trips as ``(n, 2)`` metre arrays.
        grid: Raster geometry.

    Returns:
        Float array ``(height, width)``; a trip adds at most 1 to a pixel.
    """
    flat = np.zeros(grid.width * grid.height, dtype=np.float32)
    for trip in trips:
        flat[trace.trip_pixels(trip, grid, clip=False)] += 1.0
    return flat.reshape(grid.height, grid.width)


def clip_level(counts: FloatGrid, percentile: float = CLIP_PERCENTILE) -> float:
    """Return the trip count that maps to full glow.

    Args:
        counts: Per-pixel trip counts.
        percentile: Percentile (0..100) of the lit pixels used as the clip level.

    Returns:
        The percentile of pixels with a count above zero, at least 1.0; 1.0 if nothing is lit.
    """
    lit = counts[counts > 0]
    if lit.size == 0:
        return 1.0
    return max(1.0, float(np.percentile(lit, percentile)))


def tone_map(counts: FloatGrid, clip: float) -> FloatGrid:
    """Map trip counts to glow strength with a logarithmic curve.

    Args:
        counts: Per-pixel trip counts, zero or more.
        clip: Count that maps to 1.0, greater than zero; larger counts are clipped.

    Returns:
        Array of the same shape with values in [0, 1]; 0 stays 0 and the map is non-decreasing.
    """
    scaled = np.log1p(np.clip(counts, 0.0, clip)) / math.log1p(clip)
    return np.clip(scaled, 0.0, 1.0).astype(np.float32)


def to_alpha(tone: FloatGrid) -> Alpha:
    """Turn a tone map into the alpha channel of the glow.

    Args:
        tone: Glow strength in [0, 1], shape ``(height, width)``.

    Returns:
        ``uint8`` array ``(height, width)``; the busiest pixels get ``STREET_ALPHA`` of full
        scale, a tone of 0 gives 0 (fully transparent).
    """
    return np.rint(tone * (STREET_ALPHA * ALPHA_MAX)).astype(np.uint8)


def encode_png(alpha: Alpha) -> bytes:
    """Encode the glow as an optimised palette PNG without metadata.

    Every colour is ``STREET_RGB``; the pixel value is its own alpha through a ``tRNS``
    table. This is about four times smaller than an RGBA file of the same picture.

    Args:
        alpha: ``uint8`` array ``(height, width)`` of alpha values.

    Returns:
        PNG file bytes; the same array always gives the same bytes.
    """
    img = Image.frombytes("P", (alpha.shape[1], alpha.shape[0]), alpha.tobytes())
    img.putpalette(list(STREET_RGB) * PALETTE_SIZE)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True, transparency=bytes(range(PALETTE_SIZE)))
    return buf.getvalue()


def render_png(trips: list[NDArray[np.float64]], m_per_px: float) -> bytes:
    """Render the street glow PNG at one resolution.

    Args:
        trips: Trips as ``(n, 2)`` metre arrays.
        m_per_px: Pixel size in metres.

    Returns:
        PNG bytes of the whole map.
    """
    counts = accumulate(trips, trace.map_grid(m_per_px))
    return encode_png(to_alpha(tone_map(counts, clip_level(counts))))


def fits_budget(size_bytes: int, budget: int = MAX_BYTES) -> bool:
    """Tell whether a PNG is within the size budget.

    Args:
        size_bytes: PNG size, bytes.
        budget: Largest allowed size, bytes.

    Returns:
        True if ``size_bytes`` is at most ``budget``.
    """
    return size_bytes <= budget


def next_m_per_px(m_per_px: float, limit: float = MAX_M_PER_PX) -> float | None:
    """Pick the next coarser resolution to try.

    Args:
        m_per_px: Current pixel size, metres.
        limit: Coarsest pixel size allowed, metres.

    Returns:
        ``m_per_px + M_PER_PX_STEP`` in metres, or None if that would exceed ``limit``.
    """
    nxt = m_per_px + M_PER_PX_STEP
    return nxt if nxt <= limit else None


def build_within_budget(
    trips: list[NDArray[np.float64]],
    m_per_px: float = DEFAULT_M_PER_PX,
    budget: int = MAX_BYTES,
    limit: float = MAX_M_PER_PX,
) -> tuple[bytes, float]:
    """Render the PNG, coarsening the resolution until it fits the size budget.

    Args:
        trips: Trips as ``(n, 2)`` metre arrays.
        m_per_px: Starting pixel size, metres.
        budget: Largest allowed PNG size, bytes.
        limit: Coarsest pixel size to try, metres.

    Returns:
        ``(png_bytes, m_per_px_used)``; if even the coarsest size is over budget, the coarsest
        image is returned anyway and the caller checks ``fits_budget``.
    """
    current = m_per_px
    while True:
        data = render_png(trips, current)
        nxt = next_m_per_px(current, limit)
        if fits_budget(len(data), budget) or nxt is None:
            return data, current
        current = nxt


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command line.

    Args:
        argv: Arguments (``None`` means ``sys.argv[1:]``).

    Returns:
        Namespace with ``week`` and ``out`` paths and ``m_per_px`` (metres per pixel).
    """
    ap = argparse.ArgumentParser(prog="pipeline.streets", description=__doc__)
    ap.add_argument("--week", type=Path, default=DEFAULT_WEEK, help="week CSV")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output PNG")
    ap.add_argument(
        "--m-per-px", type=float, default=DEFAULT_M_PER_PX, help="metres per pixel to start from"
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Build ``game/streets.png`` from the week CSV.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        0 on success, 1 if the week file is missing, the pixel size is not positive or the
        image is over the size budget even at the coarsest resolution.
    """
    args = parse_args(argv)
    if not args.week.is_file():
        print(f"week file not found: {args.week}", file=sys.stderr)
        return 1
    if args.m_per_px <= 0:
        print("--m-per-px must be greater than zero", file=sys.stderr)
        return 1
    raw.set_csv_limit()
    trips = trace.load_trips(args.week)
    data, used = build_within_budget(trips, args.m_per_px)
    if not fits_budget(len(data)):
        print(f"PNG is {len(data)} bytes, over the {MAX_BYTES} budget", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(data)
    print(f"{len(trips)} trips, {used:g} m/px, {len(data)} bytes -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
