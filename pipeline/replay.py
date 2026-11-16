"""Animated replay of the ghost's real shift (CONTRACT sections 4, 5 and 14).

Usage: ``python -m pipeline.replay [--data game/game_data.json] [--roads game/roads.json]
[--streets game/streets.png] [--shift mon-am] [--out docs/img] [--frames 120] [--size 480]``

The ghost is the real driver with the best total of the shift. The data holds only the GPS
points of the paid rides (one point per 15 s), so the replay shows exactly that: the ride is
drawn from the real points. Between two rides there is no GPS, so the ghost waits at the last
drop-off and, for the last ``DEADHEAD_S`` seconds before the next pickup, glides in a straight
thin line to the pickup. That glide is invented and is drawn dimmer than a ride. Money counts at
pickup (section 4). The replay runs until the last drop-off, which can be a few minutes after
the 2 hours (``REPLAY_COVERS_LAST_DROP``).

Map coordinates are metres in the map frame (x east, y south). The view is a square window of
``span`` metres; pixel (0, 0) is its north-west corner. Text is drawn from built-in 5x7 glyphs,
so the output does not depend on any installed font. Output: ``replay-<shift>.gif`` and a still
``replay-<shift>.png`` of the whole route, both deterministic.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from bisect import bisect_right
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from pipeline import geo

DEFAULT_DATA = Path("game/game_data.json")
DEFAULT_ROADS = Path("game/roads.json")
DEFAULT_STREETS = Path("game/streets.png")
DEFAULT_OUT = Path("docs/img")
DEFAULT_SHIFT = "mon-am"
DEFAULT_FRAMES = 120
DEFAULT_SIZE = 480  # picture side, pixels

SHIFT_S = geo.SHIFT_S  # nominal shift length, s
REPLAY_COVERS_LAST_DROP = True  # run on past SHIFT_S until the last drop-off
POINT_STEP_S = geo.GPS_STEP_S  # seconds between GPS points of a ride (section 4)
DEADHEAD_S = 240  # the invented glide before a pickup, s
MIN_SPAN_M = 1500.0  # smallest view window, m
VIEW_PAD = 0.15  # margin around the route, share of its larger side

# Order array indices (section 4).
I_T, I_PTS, I_FARE, I_CALL = 0, 5, 8, 9

GIF_MAX_BYTES = 1_500_000  # GIF size budget, bytes
MIN_SIZE = 240  # smallest picture tried when the budget is not met, pixels
SIZE_SHRINK = 0.85  # factor applied to the picture side per retry
FRAME_MS = 60  # display time of a frame, ms
LAST_HOLD_MS = 1800  # extra time on the last frame, ms
GIF_COLORS = 256
PALETTE_SAMPLES = 6  # frames mixed into the shared palette
STILL_SCALE = 2  # the still PNG is this many times larger than the GIF
STILL_COLORS = 256

SUPERSAMPLE = 2  # the scene is drawn this many times larger, then reduced
BASE_SIZE = 480  # marker sizes below are for this picture side, pixels
BACKGROUND = (0x07, 0x0B, 0x14)
PANEL = (0x0E, 0x14, 0x24)
TEXT = (0xE8, 0xEE, 0xFC)
MUTED = (0x8A, 0x96, 0xB3)
GHOST = (0xB4, 0x8C, 0xFF)
STREET = (0x5A, 0xA9, 0xFF)
CALL_RGB = {0: (0xFF, 0xC8, 0x57), 1: (0x5E, 0xE6, 0xFF), 2: (0xFF, 0x7A, 0x90)}
GLOW_PEAK = 0.55  # glow strength of the busiest street pixel (0..1)
GLOW_ALPHA_REF = 77  # alpha of the busiest pixel in streets.png (0.30 * 255)
ROAD_MIX = 0.35  # strength of fallback road lines (0..1)
DIM = 0.6  # share of the background mixed into a passed pin / not yet used flag
DEADHEAD_MIX = 0.45  # share of the background mixed into the invented glide line
TRAIL_MIX = 0.25  # share of the background mixed into the ride trail

# Sizes in pixels of a BASE_SIZE picture.
TRAIL_W = 3.0
HEAD_R = 5.5
HALO_R = 11.0
PIN_R = 6.0
FLAG_H = 17.0
BAR_H = 3.0
HUD_MARGIN = 8.0
HUD_PAD = 5.0
GLYPH_PX = 3  # glyph cell size at BASE_SIZE, pixels
GLYPH_GAP = 1  # blank columns between glyphs, in glyph cells
GLYPH_ROWS = 7  # height of a glyph, in glyph cells
PIN_HALF_W = 0.75  # half width of the pin's tail, in pin radii
PIN_TAIL_H = 0.8  # height of the pin's tail above the tip, in pin radii
PIN_HEAD_LIFT = 1.6  # distance of the pin's head centre above the tip, in pin radii
PIN_HOLE = 0.35  # radius of the pin's hole, in pin radii
FLAG_POLE_W = 1.5  # flag pole width at BASE_SIZE, pixels
FLAG_CLOTH_W = 0.6  # flag cloth width, in flag heights
FLAG_CLOTH_TOP = 0.75  # height of the cloth's upper corner, in flag heights
FLAG_CLOTH_MID = 0.5  # height of the cloth's inner corner, in flag heights
HALO_MIX = 0.7  # share of the background mixed into the halo of the ghost's head
MINUTES_PER_HOUR = 60
S_PER_MIN = 60
HOURS_PER_DAY = 24
ALPHA_MAX = 255  # largest 8-bit value
ALPHA_LEVELS = 256  # number of 8-bit alpha values

Point = tuple[float, float]
Order = Sequence[Any]

# 5x7 glyphs: rows from the top, '#' is a lit cell.
GLYPHS: dict[str, tuple[str, ...]] = {
    "0": (".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."),
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "2": (".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"),
    "3": ("####.", "....#", "....#", ".###.", "....#", "....#", "####."),
    "4": ("...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."),
    "5": ("#####", "#....", "####.", "....#", "....#", "#...#", ".###."),
    "6": ("..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."),
    "7": ("#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."),
    "8": (".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."),
    "9": (".###.", "#...#", "#...#", ".####", "....#", "...#.", ".##.."),
    ":": (".", ".", "#", ".", "#", ".", "."),
    ".": (".", ".", ".", ".", ".", "#", "#"),
    "€": ("..###", ".#...", "####.", ".#...", "####.", ".#...", "..###"),
}


@dataclass(frozen=True)
class Leg:
    """One stretch of the ghost's timeline.

    ``kind`` is ``ride`` (real GPS points), ``glide`` (invented straight move to a pickup) or
    ``wait`` (standing still). ``pts`` are map-frame metres; the ghost moves along them at a
    constant pace between ``t0`` and ``t1`` (shift seconds).
    """

    kind: str
    t0: float
    t1: float
    pts: tuple[Point, ...]


@dataclass(frozen=True)
class View:
    """Square map window: north-west corner ``(x0, y0)`` and side ``span``, all in metres."""

    x0: float
    y0: float
    span: float


@dataclass(frozen=True)
class Backdrop:
    """Street layer: an alpha picture of the whole map and/or road polylines in metres."""

    alpha: Image.Image | None
    roads: list[list[Point]]


@dataclass(frozen=True)
class Scene:
    """Everything the renderer needs for one shift."""

    legs: list[Leg]
    orders: list[Order]
    unit_m: float
    start_local: str
    end_s: float
    view: View


# ---------------------------------------------------------------- time, clock, money


def clock_text(start_local: str, t_s: float) -> str:
    """Return the wall clock ``HH:MM`` at ``t_s`` seconds after the shift start.

    Args:
        start_local: Shift start ``"YYYY-MM-DD HH:MM"`` (local time).
        t_s: Seconds since the start, zero or more.

    Returns:
        Hours and minutes; the clock wraps at midnight.
    """
    hh, mm = (int(p) for p in start_local.split(" ")[1].split(":"))
    total = (hh * MINUTES_PER_HOUR + mm + int(t_s // S_PER_MIN)) % (
        HOURS_PER_DAY * MINUTES_PER_HOUR
    )
    return f"{total // MINUTES_PER_HOUR:02d}:{total % MINUTES_PER_HOUR:02d}"


def replay_end_s(orders: Sequence[Order]) -> float:
    """Return how long the replay runs, in shift seconds.

    Args:
        orders: Ghost orders (section 4 arrays).

    Returns:
        ``SHIFT_S``, or the time of the last drop-off if that is later and
        ``REPLAY_COVERS_LAST_DROP`` is set.
    """
    if not REPLAY_COVERS_LAST_DROP or not orders:
        return float(SHIFT_S)
    last = max(o[I_T] + POINT_STEP_S * (len(o[I_PTS]) // 2) for o in orders)
    return float(max(SHIFT_S, last))


def frame_times(frames: int, end_s: float) -> list[float]:
    """Return the shift time of every frame, evenly spread from 0 to ``end_s`` inclusive.

    Args:
        frames: Number of frames, at least 2.
        end_s: Last time, seconds.

    Returns:
        ``frames`` times in seconds.
    """
    return [end_s * k / (frames - 1) for k in range(frames)]


def money_at(orders: Sequence[Order], t_s: float) -> float:
    """Return the ghost's money in euro at ``t_s``; a fare counts from its pickup (section 4).

    Args:
        orders: Ghost orders.
        t_s: Shift seconds.

    Returns:
        Sum of the fares with pickup time at or before ``t_s``, rounded to cents.
    """
    return round(sum(o[I_FARE] for o in orders if o[I_T] <= t_s), 2)


def money_timeline(orders: Sequence[Order]) -> list[tuple[float, float]]:
    """Return the steps of the money curve.

    Args:
        orders: Ghost orders.

    Returns:
        ``(pickup_t, total_after_pickup)`` for each order, by pickup time.
    """
    out: list[tuple[float, float]] = []
    total = 0.0
    for o in sorted(orders, key=lambda x: x[I_T]):
        total = round(total + o[I_FARE], 2)
        out.append((float(o[I_T]), total))
    return out


def money_text(value: float) -> str:
    """Format money for the picture, for example ``€12.56``.

    Args:
        value: Amount in euro.

    Returns:
        ``€`` and the amount with two decimals.
    """
    return f"€{value:.2f}"


# ---------------------------------------------------------------- the ghost's timeline


def build_timeline(orders: Sequence[Order], unit_m: float, end_s: float) -> list[Leg]:
    """Build the ghost's legs from its orders.

    Before the first pickup the ghost stands at it. After a drop-off it waits there and
    glides (invented) to the next pickup during the last ``DEADHEAD_S`` seconds of the gap.
    After the last drop-off it waits until ``end_s``.

    Args:
        orders: Ghost orders (any order; sorted here by pickup time).
        unit_m: Metres per map unit.
        end_s: End of the replay, seconds.

    Returns:
        Legs sorted by start time; empty if there are no orders.
    """
    legs: list[Leg] = []
    prev_end_t = 0.0
    here: Point | None = None
    for o in sorted(orders, key=lambda x: x[I_T]):
        pts = geo.decode_path(o, unit_m)
        t0 = float(o[I_T])
        if here is None:
            legs.append(Leg("wait", 0.0, t0, (pts[0],)))
        elif t0 > prev_end_t:
            glide = min(t0 - prev_end_t, float(DEADHEAD_S))
            if t0 - glide > prev_end_t:
                legs.append(Leg("wait", prev_end_t, t0 - glide, (here,)))
            legs.append(Leg("glide", t0 - glide, t0, (here, pts[0])))
        t1 = t0 + POINT_STEP_S * (len(pts) - 1)
        legs.append(Leg("ride", t0, t1, tuple(pts)))
        prev_end_t, here = t1, pts[-1]
    if here is not None and end_s > prev_end_t:
        legs.append(Leg("wait", prev_end_t, end_s, (here,)))
    return legs


def _lerp(a: Point, b: Point, f: float) -> Point:
    """Interpolate linearly between two points.

    Args:
        a: Start point, metres.
        b: End point, metres.
        f: Fraction of the way, 0..1.

    Returns:
        The point ``f`` of the way from ``a`` to ``b``, metres.
    """
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)


def _leg_index(leg: Leg, t_s: float) -> tuple[int, float]:
    """Locate a time on a leg's polyline.

    Args:
        leg: One leg.
        t_s: Shift seconds (clamped to the leg).

    Returns:
        ``(segment index, fraction 0..1 within that segment)``; ``(0, 0.0)`` for a leg that
        has fewer than two points or lasts no time.
    """
    n = len(leg.pts)
    if n < 2 or leg.t1 <= leg.t0:
        return 0, 0.0
    f = min(max((t_s - leg.t0) / (leg.t1 - leg.t0), 0.0), 1.0) * (n - 1)
    i = min(int(f), n - 2)
    return i, f - i


def position_at(legs: Sequence[Leg], t_s: float) -> Point:
    """Return the ghost's map position at ``t_s``.

    Args:
        legs: Timeline from ``build_timeline``, not empty.
        t_s: Shift seconds; before the first leg the first point, after a leg its last point.

    Returns:
        ``(x, y)`` in metres, interpolated along the leg's points.
    """
    k = max(bisect_right([leg.t0 for leg in legs], t_s) - 1, 0)
    leg = legs[k]
    if len(leg.pts) < 2:
        return leg.pts[0]
    i, f = _leg_index(leg, t_s)
    return _lerp(leg.pts[i], leg.pts[i + 1], f)


def leg_points_until(leg: Leg, t_s: float) -> list[Point]:
    """Return the part of a leg's polyline travelled by ``t_s``.

    Args:
        leg: One leg.
        t_s: Shift seconds.

    Returns:
        Points from the leg start to the current position; empty before the leg starts.
    """
    if t_s <= leg.t0:
        return []
    if t_s >= leg.t1 or len(leg.pts) < 2:
        return list(leg.pts)
    i, f = _leg_index(leg, t_s)
    return [*leg.pts[: i + 1], _lerp(leg.pts[i], leg.pts[i + 1], f)]


# ---------------------------------------------------------------- map frame -> pixels


def fit_view(points: Sequence[Point], pad: float = VIEW_PAD, min_span: float = MIN_SPAN_M) -> View:
    """Return the square window that holds all ``points`` with a margin.

    Args:
        points: Map-frame points, metres, not empty.
        pad: Margin on each side as a share of the larger side of the bounding box.
        min_span: Smallest window side, metres.

    Returns:
        View centred on the bounding box.
    """
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    span = max(max(xs) - min(xs), max(ys) - min(ys)) * (1 + 2 * pad)
    span = max(span, min_span)
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    return View(cx - span / 2, cy - span / 2, span)


def to_px(view: View, size: float, x_m: float, y_m: float) -> Point:
    """Convert a map-frame point to picture pixels.

    Args:
        view: Map window.
        size: Picture side, pixels.
        x_m: Map x, metres.
        y_m: Map y, metres (grows south).

    Returns:
        ``(px, py)``; the window's north-west corner is ``(0, 0)``, its south-east ``(size, size)``.
    """
    k = size / view.span
    return ((x_m - view.x0) * k, (y_m - view.y0) * k)


def mix(a: tuple[int, int, int], b: tuple[int, int, int], share: float) -> tuple[int, int, int]:
    """Blend two colours.

    Args:
        a: First RGB colour, 0..255 per channel.
        b: Second RGB colour.
        share: Weight of ``b``, 0..1.

    Returns:
        The blended RGB colour, rounded to integers.
    """
    return (
        round(a[0] + (b[0] - a[0]) * share),
        round(a[1] + (b[1] - a[1]) * share),
        round(a[2] + (b[2] - a[2]) * share),
    )


# ---------------------------------------------------------------- size budget (pure)


def fits_budget(size_bytes: int, budget: int = GIF_MAX_BYTES) -> bool:
    """Tell whether a file is within the size budget.

    Args:
        size_bytes: File size, bytes.
        budget: Largest allowed size, bytes.

    Returns:
        True if ``size_bytes`` is at most ``budget``.
    """
    return size_bytes <= budget


def next_size(size: int, min_size: int = MIN_SIZE) -> int | None:
    """Return the next smaller picture side to try, or None below ``min_size``.

    Args:
        size: Current side, pixels.
        min_size: Smallest allowed side, pixels.

    Returns:
        ``size * SIZE_SHRINK`` rounded down to an even number, at least one pixel smaller.
    """
    nxt = min(int(size * SIZE_SHRINK) // 2 * 2, size - 2)
    return nxt if nxt >= min_size else None


def build_within_budget(
    render: Callable[[int], bytes],
    size: int,
    budget: int = GIF_MAX_BYTES,
    min_size: int = MIN_SIZE,
) -> tuple[bytes, int]:
    """Render, making the picture smaller until the file fits the budget.

    Args:
        render: Function from picture side (pixels) to file bytes.
        size: Starting side, pixels.
        budget: Largest allowed size, bytes.
        min_size: Smallest side to try, pixels.

    Returns:
        ``(data, size_used)``; if even the smallest picture is over budget it is returned
        anyway and the caller checks ``fits_budget``.
    """
    current = size
    while True:
        data = render(current)
        nxt = next_size(current, min_size)
        if fits_budget(len(data), budget) or nxt is None:
            return data, current
        current = nxt


# ---------------------------------------------------------------- drawing


def glyph_width(ch: str) -> int:
    """Measure a glyph.

    Args:
        ch: A character that is a key of ``GLYPHS``.

    Returns:
        Width in glyph cells.
    """
    return len(GLYPHS[ch][0])


def text_width(text: str, cell: int) -> int:
    """Measure a text.

    Args:
        text: Characters from ``GLYPHS``.
        cell: Pixels per glyph cell.

    Returns:
        Width in pixels, gaps between glyphs included.
    """
    cells = sum(glyph_width(c) + GLYPH_GAP for c in text) - GLYPH_GAP
    return cells * cell


def draw_text(
    draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, cell: int, rgb: tuple[int, int, int]
) -> None:
    """Draw ``text`` with the built-in glyphs; unknown characters are skipped.

    Args:
        draw: Target drawing context.
        xy: Top-left pixel of the text.
        text: Characters from ``GLYPHS``.
        cell: Pixels per glyph cell.
        rgb: Text colour.
    """
    x, y = xy
    for ch in text:
        rows = GLYPHS.get(ch)
        if rows is None:
            continue
        for ry, row in enumerate(rows):
            for rx, c in enumerate(row):
                if c == "#":
                    px, py = x + rx * cell, y + ry * cell
                    draw.rectangle((px, py, px + cell - 1, py + cell - 1), fill=rgb)
        x += (len(rows[0]) + GLYPH_GAP) * cell


def alpha_mask(alpha: Image.Image) -> Image.Image:
    """Turn the alpha of ``streets.png`` into the glow mask.

    Args:
        alpha: 8-bit alpha picture, 0..255.

    Returns:
        8-bit picture whose value is the weight of ``STREET`` (0..255).
    """
    table = [
        min(ALPHA_MAX, round(a / GLOW_ALPHA_REF * GLOW_PEAK * ALPHA_MAX))
        for a in range(ALPHA_LEVELS)
    ]
    return alpha.point(table)


def draw_backdrop(view: View, side: int, backdrop: Backdrop) -> Image.Image:
    """Draw the dark map with the street glow.

    Args:
        view: Map window.
        side: Picture side, pixels.
        backdrop: Street alpha picture and/or road lines.

    Returns:
        RGB picture ``side`` x ``side``.
    """
    img = Image.new("RGB", (side, side), BACKGROUND)
    if backdrop.alpha is not None:
        ppm = backdrop.alpha.width / geo.MAP_W_M  # source pixels per metre
        box = (
            view.x0 * ppm,
            view.y0 * ppm,
            (view.x0 + view.span) * ppm,
            (view.y0 + view.span) * ppm,
        )
        crop = backdrop.alpha.transform(
            (side, side), Image.Transform.EXTENT, box, Image.Resampling.BILINEAR
        )
        img = Image.composite(Image.new("RGB", (side, side), STREET), img, alpha_mask(crop))
    elif backdrop.roads:
        draw = ImageDraw.Draw(img)
        line = mix(BACKGROUND, STREET, ROAD_MIX)
        for road in backdrop.roads:
            draw.line([to_px(view, side, x, y) for x, y in road], fill=line, width=SUPERSAMPLE)
    return img


def _pin(draw: ImageDraw.ImageDraw, p: Point, u: float, rgb: tuple[int, int, int]) -> None:
    """Draw a pickup pin.

    Args:
        draw: Target drawing context.
        p: Pixel of the pin's tip.
        u: Pixel scale (picture side over ``BASE_SIZE``).
        rgb: Pin colour.
    """
    x, y = p
    r = PIN_R * u
    tail_w, tail_h, lift, hole = PIN_HALF_W * r, PIN_TAIL_H * r, PIN_HEAD_LIFT * r, PIN_HOLE * r
    draw.polygon([(x - tail_w, y - tail_h), (x + tail_w, y - tail_h), (x, y)], fill=rgb)
    draw.ellipse((x - r, y - lift - r, x + r, y - lift + r), fill=rgb)
    draw.ellipse((x - hole, y - lift - hole, x + hole, y - lift + hole), fill=BACKGROUND)


def _flag(draw: ImageDraw.ImageDraw, p: Point, u: float, rgb: tuple[int, int, int]) -> None:
    """Draw a drop-off flag.

    Args:
        draw: Target drawing context.
        p: Pixel of the pole's foot.
        u: Pixel scale (picture side over ``BASE_SIZE``).
        rgb: Cloth colour.
    """
    x, y = p
    h = FLAG_H * u
    draw.line([(x, y), (x, y - h)], fill=TEXT, width=max(1, round(FLAG_POLE_W * u)))
    cloth = [
        (x, y - h),
        (x + FLAG_CLOTH_W * h, y - FLAG_CLOTH_TOP * h),
        (x, y - FLAG_CLOTH_MID * h),
    ]
    draw.polygon(cloth, fill=rgb)


def scene_px(scene: Scene, side: int, p: Point) -> Point:
    """Convert a map point to a pixel of the scene picture.

    Args:
        scene: Shift data and view.
        side: Picture side, pixels.
        p: Map-frame point, metres.

    Returns:
        ``(px, py)`` in pixels.
    """
    return to_px(scene.view, side, p[0], p[1])


def draw_trails(draw: ImageDraw.ImageDraw, scene: Scene, side: int, t_s: float) -> None:
    """Draw the travelled part of every ride (trail) and glide (thin dim line).

    Args:
        draw: Target drawing context.
        scene: Shift data and view.
        side: Picture side, pixels.
        t_s: Shift seconds.
    """
    u = side / BASE_SIZE
    for leg in scene.legs:
        pts = [scene_px(scene, side, p) for p in leg_points_until(leg, t_s)]
        if leg.kind == "ride" and len(pts) > 1:
            draw.line(
                pts, fill=mix(GHOST, BACKGROUND, TRAIL_MIX), width=round(TRAIL_W * u), joint="curve"
            )
        elif leg.kind == "glide" and len(pts) > 1:
            draw.line(pts, fill=mix(GHOST, BACKGROUND, DEADHEAD_MIX), width=max(1, round(u)))


def draw_orders(draw: ImageDraw.ImageDraw, scene: Scene, side: int, t_s: float) -> None:
    """Draw a flag at every drop-off and a pin at every pickup; used ones are dimmed.

    Args:
        draw: Target drawing context.
        scene: Shift data and view.
        side: Picture side, pixels.
        t_s: Shift seconds.
    """
    u = side / BASE_SIZE
    for o in scene.orders:
        rgb = CALL_RGB.get(o[I_CALL], MUTED)
        pts = geo.decode_path(o, scene.unit_m)
        taken = o[I_T] <= t_s
        _flag(draw, scene_px(scene, side, pts[-1]), u, rgb if taken else mix(rgb, BACKGROUND, DIM))
        _pin(draw, scene_px(scene, side, pts[0]), u, mix(rgb, BACKGROUND, DIM) if taken else rgb)


def draw_ghost(draw: ImageDraw.ImageDraw, scene: Scene, side: int, t_s: float) -> None:
    """Draw the ghost's head with its halo at its position.

    Args:
        draw: Target drawing context.
        scene: Shift data and view.
        side: Picture side, pixels.
        t_s: Shift seconds.
    """
    u = side / BASE_SIZE
    hx, hy = scene_px(scene, side, position_at(scene.legs, t_s))
    for r, rgb in ((HALO_R, mix(GHOST, BACKGROUND, HALO_MIX)), (HEAD_R, GHOST)):
        draw.ellipse((hx - r * u, hy - r * u, hx + r * u, hy + r * u), fill=rgb)


def draw_scene(scene: Scene, base: Image.Image, side: int, t_s: float) -> Image.Image:
    """Draw the map layer at time ``t_s``: trail, pins, flags and the ghost.

    Args:
        scene: Shift data and view.
        base: Backdrop of the same ``side`` (not changed).
        side: Picture side, pixels (supersampled).
        t_s: Shift seconds.

    Returns:
        New RGB picture ``side`` x ``side``.
    """
    img = base.copy()
    draw = ImageDraw.Draw(img)
    draw_trails(draw, scene, side, t_s)
    draw_orders(draw, scene, side, t_s)
    draw_ghost(draw, scene, side, t_s)
    return img


def draw_hud(img: Image.Image, scene: Scene, t_s: float) -> None:
    """Draw the clock, the ghost's money and a progress bar on the final-size picture.

    Args:
        img: Picture to draw on (changed in place).
        scene: Shift data.
        t_s: Shift seconds.
    """
    side = img.width
    cell = max(1, round(GLYPH_PX * side / BASE_SIZE))
    pad, margin = round(HUD_PAD * cell), round(HUD_MARGIN * cell)
    draw = ImageDraw.Draw(img)
    height = GLYPH_ROWS * cell
    for text, rgb, right in (
        (clock_text(scene.start_local, t_s), TEXT, False),
        (money_text(money_at(scene.orders, t_s)), GHOST, True),
    ):
        w = text_width(text, cell)
        x = side - margin - w if right else margin
        draw.rectangle((x - pad, margin - pad, x + w + pad, margin + height + pad), fill=PANEL)
        draw_text(draw, (x, margin), text, cell, rgb)
    bar = max(1, round(BAR_H * side / BASE_SIZE))
    done = round(side * t_s / scene.end_s)
    if done > 0:
        draw.rectangle((0, side - bar, done - 1, side), fill=GHOST)


def render_frame(scene: Scene, backdrop: Backdrop, size: int, t_s: float) -> Image.Image:
    """Render one picture at ``t_s`` (convenience for single frames and the still).

    Args:
        scene: Shift data.
        backdrop: Street layer.
        size: Final side, pixels.
        t_s: Shift seconds.

    Returns:
        RGB picture ``size`` x ``size``.
    """
    base = draw_backdrop(scene.view, size * SUPERSAMPLE, backdrop)
    return finish_frame(scene, draw_scene(scene, base, size * SUPERSAMPLE, t_s), size, t_s)


def finish_frame(scene: Scene, big: Image.Image, size: int, t_s: float) -> Image.Image:
    """Reduce a supersampled scene picture to its final size and add the HUD.

    Args:
        scene: Shift data.
        big: Supersampled scene picture (``size * SUPERSAMPLE`` pixels a side).
        size: Final side, pixels.
        t_s: Shift seconds.

    Returns:
        RGB picture ``size`` x ``size``.
    """
    img = big.resize((size, size), Image.Resampling.LANCZOS)
    draw_hud(img, scene, t_s)
    return img


def render_frames(scene: Scene, backdrop: Backdrop, size: int, frames: int) -> list[Image.Image]:
    """Render all frames of the replay.

    Args:
        scene: Shift data.
        backdrop: Street layer.
        size: Final side, pixels.
        frames: Number of frames, at least 2.

    Returns:
        One RGB picture per time from ``frame_times``.
    """
    base = draw_backdrop(scene.view, size * SUPERSAMPLE, backdrop)
    return [
        finish_frame(scene, draw_scene(scene, base, size * SUPERSAMPLE, t), size, t)
        for t in frame_times(frames, scene.end_s)
    ]


# ---------------------------------------------------------------- encoding


def shared_palette(frames: Sequence[Image.Image]) -> Image.Image:
    """Build one 256-colour palette picture from a spread of frames.

    Args:
        frames: RGB pictures of equal size, not empty.

    Returns:
        Palette ("P") picture to pass as ``palette`` to ``Image.quantize``; the same frames
        always give the same palette.
    """
    step = max(1, len(frames) // PALETTE_SAMPLES)
    picks = [*frames[::step], frames[-1]]
    w, h = frames[0].size
    mosaic = Image.new("RGB", (w, h * len(picks)))
    for i, f in enumerate(picks):
        mosaic.paste(f, (0, i * h))
    return mosaic.quantize(GIF_COLORS, Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)


def encode_gif(frames: Sequence[Image.Image]) -> bytes:
    """Encode frames as a looping GIF with one shared palette and no dithering.

    Args:
        frames: RGB pictures of equal size, not empty.

    Returns:
        GIF bytes; the last frame is held for ``LAST_HOLD_MS`` longer.
    """
    pal = shared_palette(frames)
    quant = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in frames]
    durations = [FRAME_MS] * (len(quant) - 1) + [FRAME_MS + LAST_HOLD_MS]
    buf = io.BytesIO()
    quant[0].save(
        buf, format="GIF", save_all=True, append_images=quant[1:], duration=durations, loop=0
    )
    return buf.getvalue()


def encode_png(img: Image.Image) -> bytes:
    """Encode a picture as an optimised palette PNG.

    Args:
        img: RGB picture.

    Returns:
        PNG bytes with ``STILL_COLORS`` colours and no dithering; the same picture always gives
        the same bytes.
    """
    buf = io.BytesIO()
    img.quantize(STILL_COLORS, Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(
        buf, format="PNG", optimize=True
    )
    return buf.getvalue()


# ---------------------------------------------------------------- data


def find_shift(data: dict[str, Any], shift_id: str) -> dict[str, Any] | None:
    """Look a shift up by id.

    Args:
        data: Parsed ``game_data.json``.
        shift_id: Shift id such as ``mon-am``.

    Returns:
        The shift object, or None if there is no such id.
    """
    return next((s for s in data["shifts"] if s["id"] == shift_id), None)


def ghost_orders(shift: dict[str, Any]) -> list[Order]:
    """List the ghost's orders of a shift.

    Args:
        shift: Shift object (section 4).

    Returns:
        The order arrays named by ``ghost.orders``, in that (ascending index) order.
    """
    return [shift["orders"][i] for i in shift["ghost"]["orders"]]


def make_scene(shift: dict[str, Any], unit_m: float) -> Scene | None:
    """Build the scene of a shift.

    Args:
        shift: Shift object (section 4).
        unit_m: Metres per map unit.

    Returns:
        The scene, or None if the ghost has no orders.
    """
    orders = ghost_orders(shift)
    if not orders:
        return None
    end_s = replay_end_s(orders)
    legs = build_timeline(orders, unit_m, end_s)
    return Scene(
        legs,
        orders,
        unit_m,
        shift["start_local"],
        end_s,
        fit_view([p for leg in legs for p in leg.pts]),
    )


def load_roads(path: Path) -> list[list[Point]]:
    """Read ``roads.json`` (section 5) as polylines.

    Args:
        path: Path of ``roads.json``.

    Returns:
        One polyline of ``(x, y)`` map-frame points in metres per edge.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    unit = float(data["unit_m"])
    nodes = data["nodes"]
    roads: list[list[Point]] = []
    for a, b, inner in data["edges"]:
        flat = [*nodes[2 * a : 2 * a + 2], *inner, *nodes[2 * b : 2 * b + 2]]
        roads.append([(flat[i] * unit, flat[i + 1] * unit) for i in range(0, len(flat), 2)])
    return roads


def load_backdrop(streets: Path, roads: Path) -> Backdrop:
    """Load the street layer.

    Args:
        streets: Path of ``streets.png``.
        roads: Path of ``roads.json``, used when ``streets`` is missing.

    Returns:
        The alpha of ``streets`` if that file exists, else the lines of ``roads`` if that file
        exists, else an empty backdrop.
    """
    if streets.is_file():
        with Image.open(streets) as im:
            return Backdrop(im.convert("RGBA").getchannel("A"), [])
    if roads.is_file():
        return Backdrop(None, load_roads(roads))
    return Backdrop(None, [])


def render_shift(
    scene: Scene, backdrop: Backdrop, size: int, frames: int
) -> tuple[bytes, bytes, int]:
    """Render the GIF (within the size budget) and the still PNG of one shift.

    Args:
        scene: Shift data.
        backdrop: Street layer.
        size: Starting GIF side, pixels.
        frames: Number of GIF frames.

    Returns:
        ``(gif_bytes, png_bytes, gif_size_used)``.
    """
    gif, used = build_within_budget(
        lambda s: encode_gif(render_frames(scene, backdrop, s, frames)), size
    )
    still = render_frame(scene, backdrop, size * STILL_SCALE, scene.end_s)
    return gif, encode_png(still), used


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command line.

    Args:
        argv: Arguments (``None`` means ``sys.argv[1:]``).

    Returns:
        Namespace with the paths, ``shift`` (comma separated ids), ``frames`` and ``size``
        (pixels).
    """
    ap = argparse.ArgumentParser(prog="pipeline.replay", description=__doc__)
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA, help="game_data.json")
    ap.add_argument("--roads", type=Path, default=DEFAULT_ROADS, help="roads.json (fallback)")
    ap.add_argument("--streets", type=Path, default=DEFAULT_STREETS, help="streets.png")
    ap.add_argument("--shift", default=DEFAULT_SHIFT, help="shift ids, comma separated")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output directory")
    ap.add_argument("--frames", type=int, default=DEFAULT_FRAMES, help="GIF frames (>= 2)")
    ap.add_argument("--size", type=int, default=DEFAULT_SIZE, help="GIF side, pixels")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Write ``replay-<shift>.gif`` and ``replay-<shift>.png`` for each requested shift.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        0 on success, 1 for a missing data file, an unknown shift, a ghost without orders,
        bad ``--frames`` / ``--size`` or a GIF that is over budget at the smallest size.
    """
    args = parse_args(argv)
    if not args.data.is_file():
        print(f"data file not found: {args.data}", file=sys.stderr)
        return 1
    if args.frames < 2 or args.size < MIN_SIZE:
        print(f"need --frames >= 2 and --size >= {MIN_SIZE}", file=sys.stderr)
        return 1
    data = json.loads(args.data.read_text(encoding="utf-8"))
    backdrop = load_backdrop(args.streets, args.roads)
    args.out.mkdir(parents=True, exist_ok=True)
    for shift_id in args.shift.split(","):
        shift = find_shift(data, shift_id)
        scene = make_scene(shift, float(data["unit_m"])) if shift else None
        if scene is None:
            print(f"unknown shift or ghost without orders: {shift_id}", file=sys.stderr)
            return 1
        gif, png, used = render_shift(scene, backdrop, args.size, args.frames)
        (args.out / f"replay-{shift_id}.gif").write_bytes(gif)
        (args.out / f"replay-{shift_id}.png").write_bytes(png)
        print(f"{shift_id}: gif {len(gif)} bytes at {used} px, still {len(png)} bytes")
        if not fits_budget(len(gif)):
            print(f"{shift_id}: GIF over the {GIF_MAX_BYTES} budget", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
