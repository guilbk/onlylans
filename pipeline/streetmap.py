"""Street map of Porto from our own data: every road edge in one of three classes (KMAP).

Usage: ``python -m pipeline.streetmap [--roads game/roads.json] [--streets game/streets.png]
[--out game/streetmap.json]``

The road graph (``roads.json``) comes from the week's taxi traces. The trip density raster
(``streets.png``, alpha = how many trips touched a pixel) says how busy each edge is. Edges are
ranked by the median density along them and cut into main roads, avenues and streets. Output
coordinates are 2.5 m units, like ``roads.json``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

DEFAULT_ROADS = Path("game/roads.json")
DEFAULT_STREETS = Path("game/streets.png")
DEFAULT_OUT = Path("game/streetmap.json")
MAIN_SHARE = 0.10  # busiest share of the edges: main roads
AVENUE_SHARE = 0.30  # next share: avenues; the rest are streets
ALPHA_CHANNEL = 3
MAX_BYTES = 300_000


def edge_points(nodes: list[int], edge: list) -> list[int]:
    """Full flat polyline of an edge, end nodes included.

    Args:
        nodes: Flat node coordinates ``[x0, y0, x1, y1, ...]``.
        edge: ``[a, b, interior_flat]``.

    Returns:
        Flat list ``[xa, ya, ...interior, xb, yb]`` in the same units.
    """
    a, b, mid = edge
    return [nodes[2 * a], nodes[2 * a + 1], *mid, nodes[2 * b], nodes[2 * b + 1]]


def edge_score(flat: list[int], density: NDArray[np.uint8], px_units: float) -> float:
    """Median trip density under a polyline (max of a 3x3 window per point).

    Args:
        flat: Flat polyline in map units.
        density: 2-D density raster (rows = y).
        px_units: Map units per raster pixel.

    Returns:
        The median density, 0 for an empty polyline.
    """
    if len(flat) < 2:
        return 0.0
    xs = np.clip((np.asarray(flat[0::2]) / px_units).astype(int), 1, density.shape[1] - 2)
    ys = np.clip((np.asarray(flat[1::2]) / px_units).astype(int), 1, density.shape[0] - 2)
    vals = [density[y - 1 : y + 2, x - 1 : x + 2].max() for x, y in zip(xs, ys, strict=True)]
    return float(np.median(vals))


def classify(scores: list[float]) -> list[int]:
    """Class of every edge by rank: 0 main, 1 avenue, 2 street.

    Args:
        scores: Busyness per edge (higher = busier).

    Returns:
        One class per edge; the busiest ``MAIN_SHARE`` are 0, the next ``AVENUE_SHARE`` are 1.
    """
    n = len(scores)
    order = sorted(range(n), key=lambda i: -scores[i])
    out = [2] * n
    n_main = round(n * MAIN_SHARE)
    n_avenue = round(n * (MAIN_SHARE + AVENUE_SHARE))
    for rank, i in enumerate(order):
        out[i] = 0 if rank < n_main else 1 if rank < n_avenue else 2
    return out


def build(roads: dict, density: NDArray[np.uint8] | None, map_w_units: float) -> dict:
    """Build the street map layer.

    Args:
        roads: Parsed ``roads.json``.
        density: Trip density raster, or ``None`` (then longer edges rank higher).
        map_w_units: Width of the map in map units (to scale raster pixels).

    Returns:
        Dict ``{"v", "unit_m", "classes": [main, avenue, street]}``, each class a list of flat
        polylines.
    """
    nodes = roads["nodes"]
    polys = [edge_points(nodes, e) for e in roads["edges"]]
    if density is None:
        scores = [float(len(p)) for p in polys]
    else:
        px = map_w_units / density.shape[1]
        scores = [edge_score(p, density, px) for p in polys]
    classes: list[list[list[int]]] = [[], [], []]
    for poly, cls in zip(polys, classify(scores), strict=True):
        classes[cls].append(poly)
    return {"v": 1, "unit_m": roads["unit_m"], "classes": classes}


def load_density(path: Path) -> NDArray[np.uint8] | None:
    """Alpha channel of the density PNG, or ``None`` if the file is missing.

    Args:
        path: PNG path.

    Returns:
        2-D uint8 array or ``None``.
    """
    if not path.is_file():
        return None
    from PIL import Image

    return np.asarray(Image.open(path).convert("RGBA"))[..., ALPHA_CHANNEL]


def main(argv: list[str] | None = None) -> int:
    """Command line entry point.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        0 on success, 1 if the output is too large.
    """
    ap = argparse.ArgumentParser(description="Build game/streetmap.json")
    ap.add_argument("--roads", type=Path, default=DEFAULT_ROADS)
    ap.add_argument("--streets", type=Path, default=DEFAULT_STREETS)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    roads = json.loads(args.roads.read_text(encoding="utf-8"))
    map_units = 15000 / roads["unit_m"]
    text = json.dumps(build(roads, load_density(args.streets), map_units), separators=(",", ":"))
    if len(text) > MAX_BYTES:
        print(f"streetmap too large: {len(text)} bytes")
        return 1
    args.out.write_text(text, encoding="utf-8")
    print(f"wrote {args.out} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
