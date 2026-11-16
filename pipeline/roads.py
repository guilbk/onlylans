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

import networkx as nx
import numpy as np
from scipy import ndimage
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
MIN_SPUR_M = 40.0  # dead-end edges shorter than this are pruned, metres
DP_START_M = 6.0  # polyline simplification tolerance, metres
DP_MAX_M = 10.0
DP_STEP_M = 1.0
MAX_BYTES = 400_000
UNIT_M = 2.5  # coordinate unit of roads.json, metres
EIGHT = np.ones((3, 3), dtype=int)  # 8-connectivity structure
NEIGHBOURS = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))


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


Pixel = tuple[int, int]  # (row, col)
Point = tuple[float, float]  # (x, y) in metres


def px_to_m(row: float, col: float, cell_m: float = CELL_M) -> Point:
    """Return the metre position (x, y) of the centre of a pixel (pixel * cell + cell / 2)."""
    return col * cell_m + cell_m / 2, row * cell_m + cell_m / 2


def polyline_length(pts: list[Point]) -> float:
    """Return the length in metres of a polyline given in metres."""
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:], strict=False))


def classify_pixels(skel: np.ndarray) -> np.ndarray:
    """Count the 8-connected skeleton neighbours of every skeleton pixel.

    Args:
        skel: Boolean skeleton.

    Returns:
        Integer array of the same shape: neighbour count on skeleton pixels, 0 elsewhere.
    """
    total = ndimage.convolve(skel.astype(np.uint8), EIGHT.astype(np.uint8), mode="constant")
    return np.where(skel, total - 1, 0)


def node_pixels(skel: np.ndarray, degree: np.ndarray) -> np.ndarray:
    """Select the junction and end pixels (1 or at least 3 neighbours).

    A skeleton component without any such pixel (a pure ring) gets its first pixel as a node.

    Args:
        skel: Boolean skeleton with specks (0 neighbours) already removed.
        degree: Neighbour counts from :func:`classify_pixels`.

    Returns:
        Boolean mask of node pixels.
    """
    nodes = skel & ((degree == 1) | (degree >= 3))
    labels, count = ndimage.label(skel, structure=EIGHT)
    has_node = np.zeros(count + 1, dtype=bool)
    has_node[labels[nodes]] = True
    for i, box in enumerate(ndimage.find_objects(labels), start=1):
        if not has_node[i]:
            ys, xs = np.nonzero(labels[box] == i)
            nodes[box][ys[0], xs[0]] = True
    return nodes


def _walk_chain(pixels: set[Pixel], start: Pixel) -> list[Pixel]:
    """Follow a one-pixel-wide chain from ``start`` through unvisited neighbours."""
    path = [start]
    seen = {start}
    while True:
        r, c = path[-1]
        nxt = next(
            (
                (r + dr, c + dc)
                for dr, dc in NEIGHBOURS
                if (r + dr, c + dc) in pixels and (r + dr, c + dc) not in seen
            ),
            None,
        )
        if nxt is None:
            return path
        path.append(nxt)
        seen.add(nxt)


def _touching(pix: Pixel, cluster: np.ndarray) -> list[int]:
    """Return the sorted node-cluster ids among the 8 neighbours of a pixel."""
    r, c = pix
    h, w = cluster.shape
    found = {
        int(cluster[r + dr, c + dc])
        for dr, dc in NEIGHBOURS
        if 0 <= r + dr < h and 0 <= c + dc < w and cluster[r + dr, c + dc] > 0
    }
    return sorted(found)


def skeleton_to_graph(skel: np.ndarray, cell_m: float = CELL_M) -> nx.MultiGraph:
    """Turn a skeleton into a road graph.

    Nodes are the skeleton pixels with 1 or at least 3 neighbours; touching node pixels are
    collapsed into one node placed at their centroid. Each pixel chain between nodes is an edge.

    Args:
        skel: Boolean skeleton.
        cell_m: Pixel size in metres.

    Returns:
        MultiGraph. Node attribute ``pos`` (x, y metres). Edge attributes ``a``, ``b`` (the
        end nodes), ``pts`` (polyline in metres from ``a`` to ``b``, ends included) and ``len``.
    """
    degree = classify_pixels(skel)
    skel = skel & (degree > 0)
    nodes = node_pixels(skel, degree)
    cluster, n_nodes = ndimage.label(nodes, structure=EIGHT)
    graph = nx.MultiGraph()
    centres = ndimage.center_of_mass(nodes, cluster, range(1, n_nodes + 1))
    for i, (r, c) in enumerate(centres, start=1):
        graph.add_node(i, pos=px_to_m(r, c, cell_m))
    chains, n_chains = ndimage.label(skel & ~nodes, structure=EIGHT)
    rows, cols = np.nonzero(chains)
    order = np.argsort(chains[rows, cols], kind="stable")
    bounds = np.searchsorted(chains[rows, cols][order], np.arange(1, n_chains + 2))
    for k in range(n_chains):
        idx = order[bounds[k] : bounds[k + 1]]
        _add_chain(graph, cluster, [(int(rows[i]), int(cols[i])) for i in idx], cell_m)
    return graph


def _add_chain(
    graph: nx.MultiGraph, cluster: np.ndarray, chain: list[Pixel], cell_m: float
) -> None:
    """Order one chain component, find its two end nodes and add it as an edge."""
    pixels = set(chain)
    ends = sorted(p for p in chain if _touching(p, cluster))
    if not ends:
        return
    path = _walk_chain(pixels, ends[0])
    first, last = _touching(path[0], cluster), _touching(path[-1], cluster)
    if len(path) == 1:
        a, b = first[0], first[-1]
    else:
        a, b = first[0], last[0] if last else first[0]
    pts = [graph.nodes[a]["pos"], *(px_to_m(r, c, cell_m) for r, c in path), graph.nodes[b]["pos"]]
    graph.add_edge(a, b, a=a, b=b, pts=pts, len=polyline_length(pts))


def oriented(data: dict, start: int) -> list[Point]:
    """Return an edge polyline in metres so that it begins at node ``start``."""
    pts: list[Point] = data["pts"]
    return pts if data["a"] == start else pts[::-1]


def contract_chains(graph: nx.MultiGraph) -> None:
    """Merge every node of degree 2 into the edge that passes through it (in place).

    Args:
        graph: Road graph; nodes whose two edge ends belong to two different edges disappear.
    """
    for node in sorted(graph.nodes):
        if graph.degree(node) != 2:
            continue
        edges = list(graph.edges(node, keys=True, data=True))
        if len(edges) != 2:
            continue  # a self-loop: nothing to merge
        (_, p, _, d1), (_, q, _, d2) = edges
        pts = [*oriented(d1, p), *oriented(d2, node)[1:]]
        graph.remove_node(node)
        graph.add_edge(p, q, a=p, b=q, pts=pts, len=polyline_length(pts))


def prune_spurs(graph: nx.MultiGraph, min_len_m: float = MIN_SPUR_M) -> None:
    """Remove short dead-end edges and tiny loops, repeating until none is left (in place).

    Args:
        graph: Road graph from :func:`skeleton_to_graph`.
        min_len_m: Edges shorter than this are spurs, in metres.
    """
    contract_chains(graph)
    changed = True
    while changed:
        changed = False
        for node in sorted(graph.nodes):
            if node not in graph:
                continue
            for _, other, key, data in list(graph.edges(node, keys=True, data=True)):
                dead_end = other != node and graph.degree(node) == 1
                if data["len"] < min_len_m and (dead_end or other == node):
                    graph.remove_edge(node, other, key)
                    changed = True
            if graph.degree(node) == 0:
                graph.remove_node(node)
        contract_chains(graph)


def largest_component(graph: nx.MultiGraph) -> nx.MultiGraph:
    """Return a copy of the connected component with the greatest total edge length.

    Args:
        graph: Road graph.

    Returns:
        The component as a new graph (ties go to the one with the smallest node id).
    """

    def total(nodes: set[int]) -> tuple[float, int]:
        length = sum(d["len"] for *_, d in graph.subgraph(nodes).edges(data=True))
        return length, -min(nodes)

    best = max(nx.connected_components(graph), key=total)
    return graph.subgraph(best).copy()
