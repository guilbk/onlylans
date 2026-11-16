"""Event-driven Python twin of the game: engine, tips, the 7 AI rivals and the greedy bot.

It ports CONTRACT sections 10-13 and ``game/src/js/{20_engine,22_rules,25_ai}.js`` rule by rule, so
that the balance levers (``LEAD``, ``RADIUS``, ``DIFF_K`` and the rivals' ``DIFF`` table) can be
swept much faster than through the browser engine. The bot is the one of ``tools/engine_test.mjs``:
greedy fare per second, reacting ``delay`` game seconds after a pin appears (200 s = about 5 s of
real play). Roads are off (straight legs), exactly as ``engine_test.mjs`` runs without ``--roads``.

Units: metres, game seconds, euros, km/h. Randomness is the deterministic hash ``mix`` of the JS
code.

Usage::

    python -m pipeline.sim [--data game/game_data.json] [--compare] [--workers N]

``--compare`` runs ``node tools/engine_test.mjs`` on the same data and prints how far this twin is
from it (per-shift bot, bot and rival averages per difficulty).
"""

from __future__ import annotations

import argparse
import bisect
import math
import re
import struct
import subprocess
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---- constants of CONTRACT section 9 and of the JS engine ------------------------------------
SHIFT_S = 7200.0  # game s in one shift
BOARD_S = 30.0  # boarding seconds added to every eta
EPS = 1e-9  # tolerance for event times (engine EPS)
SHIFT_EPS = 1e-6  # the last step is clamped to the shift end inside this
TRAIL_EVERY_S = 10.0  # the engine wakes every 10 game s (trail sample)
BOT_STEP_S = 7.2  # bot cadence, game s per tick
BOT_TICKS = 1000  # ticks of the bot loop of engine_test
BOT_WINDOW_S = 900.0  # the bot looks at orders due within this many game s
CRUISE_WINDOW_S = 400.0  # the idle bot drives towards the nearest pin due within this many game s
CRUISE_MIN_M = 200.0  # no cruising for a pin nearer than this (metres)
HOME = (9110.0, 12443.0)  # start of the car, metres
MAP_W_M = 15000.0
MAP_H_M = 19000.0
RIDE_STEP_S = 15.0  # seconds between two GPS points of a ride
LEGEND_K = 1.25  # legend medal at 1.25 x the ghost total
DEFAULT_DELAY_S = 200.0

DIFFICULTIES = ("easy", "normal", "hard")
DEFAULT_LEAD = (720.0, 540.0, 420.0)  # game s, call types A, B, C
DEFAULT_RADIUS = (5000.0, 3500.0, 2500.0)  # metres, call types A, B, C
DEFAULT_DIFF_K = {"easy": 1.25, "normal": 1.0, "hard": 0.85}

# ---- constants of the rivals (25_ai.js) ------------------------------------------------------
GRID_S = 5.0  # game s between decision points of a free rival
CYCLE_S = 1500.0  # work + break cycle, game s
AIRPORT = (3232.0, 1323.0, 2500.0)  # x, y, radius in metres
NOTICE_K = 0.6  # share of the personal reaction spent before a pin is noticed
SURGE_HEAD_S = 240.0  # Lurdes heads for a surge this long before it starts
MIN_REPOS_M2 = 40000.0  # squared metres: no repositioning drive shorter than 200 m
MASK32 = 0xFFFFFFFF
RIVAL_IDS = ("ze", "fatima", "rui", "ines", "tiago", "lurdes", "nuno")

# ---- passenger kinds and tips (22_rules.js) --------------------------------------------------
TIP_RATE = {"regular": 0.05, "tourist": 0.15, "vip": 0.30, "rush": 0.10}
RUSH_LEAD_K = 0.6
COMBO_WINDOW_S = 90.0
COMBO_K = (1.0, 1.0, 1.1, 1.2, 1.3)

OK, GONE, LATE = 0, 1, 2  # feasibility reason codes of the engine


@dataclass(frozen=True)
class RivalDiff:
    """How sharp the 7 rivals are on one difficulty (``PG.ai.DIFF``).

    Attributes:
        react: Scale of the personal reaction time (dimensionless).
        radius: Scale of the radar radius of a rival (dimensionless).
        attn: Share of the pins a rival ever notices (0..1).
        duty: Share of the shift a rival works (0..1).
        speed: Scale of the rival's driving speed (dimensionless).
        near: Pins within this many metres of the player are always noticed (0 = off).
        near_react: Reaction scale for those near pins (dimensionless).
    """

    react: float
    radius: float
    attn: float
    duty: float
    speed: float
    near: float
    near_react: float


DEFAULT_RIVAL_DIFF = {
    "easy": RivalDiff(2.4, 0.7, 0.14, 0.25, 1.0, 0.0, 1.0),
    "normal": RivalDiff(1.0, 1.0, 0.20, 0.40, 1.15, 2500.0, 0.5),
    "hard": RivalDiff(0.55, 1.25, 0.28, 0.50, 1.3, 3200.0, 0.35),
}


@dataclass(frozen=True)
class Settings:
    """All balance levers of one simulation run.

    Attributes:
        lead: ``PG.C.LEAD`` per call type A, B, C, game s.
        radius: ``PG.C.RADIUS`` per call type A, B, C, metres.
        diff_k: ``PG.C.DIFF_K`` per difficulty (scales lead and radius).
        rivals: ``PG.ai.DIFF`` per difficulty.
        delay: Reaction time of the bot, game s (0 = sees every pin at once).
    """

    lead: tuple[float, float, float] = DEFAULT_LEAD
    radius: tuple[float, float, float] = DEFAULT_RADIUS
    diff_k: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_DIFF_K))
    rivals: dict[str, RivalDiff] = field(default_factory=lambda: dict(DEFAULT_RIVAL_DIFF))
    delay: float = DEFAULT_DELAY_S


@dataclass(slots=True)
class Order:
    """One real trip of a shift, in the shapes of ``PG.data`` (metres, game seconds).

    Attributes:
        i: Index in the shift's order list (time order).
        t: Pickup time, game s from the shift start.
        x0: Pickup x, metres.
        y0: Pickup y, metres.
        x1: Drop-off x, metres.
        y1: Drop-off y, metres.
        d: Ride duration, s.
        km: Ride length, km.
        fare: Fare, euros.
        c: Call type 0 = A, 1 = B, 2 = C.
        stand: Taxi stand id (0 = none).
        kind: Passenger kind (regular, tourist, vip, rush).
        xs: Route x of every GPS point, metres.
        ys: Route y of every GPS point, metres.
    """

    i: int
    t: float
    x0: float
    y0: float
    x1: float
    y1: float
    d: float
    km: float
    fare: float
    c: int
    stand: int
    kind: str
    xs: list[float]
    ys: list[float]


@dataclass(slots=True)
class Spot:
    """A hotspot or a demand wave on the map.

    Attributes:
        x: Centre x, metres.
        y: Centre y, metres.
        w: Weight (hotspot pickup share) or radius in metres (surge).
        t0: Surge start, game s (0 for a hotspot).
        t1: Surge end, game s (0 for a hotspot).
    """

    x: float
    y: float
    w: float
    t0: float = 0.0
    t1: float = 0.0


@dataclass(slots=True)
class Shift:
    """One campaign shift with everything the simulation reads.

    Attributes:
        id: Shift id such as ``mon-am``.
        start_hour: Local hour of the shift start (0..23).
        detour: Road / straight distance ratio.
        speed_by_hour: km/h per local hour of day.
        hot: Hotspots (``w`` = pickup share).
        surges: Demand waves (``w`` = radius in metres, ``t0``/``t1`` game s).
        orders: Orders sorted by pickup time.
        median: Median real driver, euros.
        top10: Top-10 % real driver, euros.
        ghost: Best real driver, euros.
        times: Pickup times of ``orders`` (for bisect).
    """

    id: str
    start_hour: int
    detour: float
    speed_by_hour: list[float]
    hot: list[Spot]
    surges: list[Spot]
    orders: list[Order]
    median: float
    top10: float
    ghost: float
    times: list[float] = field(default_factory=list)


@dataclass(slots=True)
class ShiftResult:
    """Outcome of one simulated shift.

    Attributes:
        shift_id: Shift id.
        earned: Player total with tips, euros.
        medal: 0 none, 1 bronze, 2 silver, 3 gold, 4 legend.
        rides: Player pickups.
        lost_to_rivals: Orders the rivals took from the player.
        rival_lost: Times a rival had to give up its target.
        rival_eur: Total of each rival in ``RIVAL_IDS`` order, euros.
        rival_rides: Pickups of each rival in ``RIVAL_IDS`` order.
        race_place: Place among the player and the 7 rivals (1..8).
    """

    shift_id: str
    earned: float
    medal: int
    rides: int
    lost_to_rivals: int
    rival_lost: int
    rival_eur: tuple[float, ...]
    rival_rides: tuple[int, ...]
    race_place: int


# ---- small pure helpers ----------------------------------------------------------------------
def js_round(x: float) -> int:
    """Round half up like ``Math.round`` (Python's ``round`` is banker's rounding).

    Args:
        x: Any number.

    Returns:
        The nearest integer, ties towards plus infinity.
    """
    return math.floor(x + 0.5)


def to_cents(x: float) -> float:
    """Round euros to cents like the JS ``Math.round(x * 100) / 100``.

    Args:
        x: Amount, euros.

    Returns:
        The amount rounded to cents, euros.
    """
    return math.floor(x * 100 + 0.5) / 100


def f32(x: float) -> float:
    """Round to the nearest 32-bit float (the AI keeps its leads in a ``Float32Array``).

    Args:
        x: Any number.

    Returns:
        ``x`` as a float32, widened back to a double.
    """
    return struct.unpack("f", struct.pack("f", x))[0]


def clamp(x: float, lo: float, hi: float) -> float:
    """Limit ``x`` to ``[lo, hi]``.

    Args:
        x: Value.
        lo: Lower bound.
        hi: Upper bound.

    Returns:
        ``x`` clamped.
    """
    return lo if x < lo else (hi if x > hi else x)


def _imul(a: int, b: int) -> int:
    """32-bit integer multiply (``Math.imul`` on unsigned bit patterns)."""
    return (a * b) & MASK32


def mix(a: int, b: int) -> float:
    """Deterministic hash of two ints to ``[0, 1)`` (``mix`` of 25_ai.js).

    Args:
        a: First 32-bit value (a seed).
        b: Second value (a salt).

    Returns:
        A pseudo-random number in ``[0, 1)``.
    """
    h = _imul((a ^ 0x9E3779B9) & MASK32, 0x85EBCA6B) ^ (b & MASK32)
    h = _imul(h ^ (h >> 16), 0xC2B2AE35)
    h ^= h >> 13
    h = _imul(h, 0x27D4EB2F)
    h ^= h >> 15
    return h / 4294967296.0


def fnv(text: str) -> int:
    """FNV-1a over the UTF-16 code units of ``text``, low byte first (``fnv`` of 25_ai.js).

    Args:
        text: Any string (ids are ASCII).

    Returns:
        An unsigned 32-bit hash.
    """
    h = 2166136261
    for ch in text:
        c = ord(ch)
        h = _imul(h ^ (c & 255), 16777619)
        h = _imul(h ^ (c >> 8), 16777619)
    return h


def fnv1a32(text: str) -> int:
    """FNV-1a 32 bit over the UTF-8 bytes of ``text`` (``fnv1a32`` of 22_rules.js).

    Args:
        text: Any string.

    Returns:
        An unsigned 32-bit hash.
    """
    h = 2166136261
    for byte in text.encode("utf-8"):
        h = _imul(h ^ byte, 16777619)
    return h


def kind_for(shift_id: str, i: int) -> str:
    """Passenger kind of order ``i`` of a shift (CONTRACT section 13).

    Args:
        shift_id: Shift id.
        i: Order index.

    Returns:
        ``regular`` (70 %), ``tourist`` (10 %), ``vip`` (8 %) or ``rush`` (12 %).
    """
    u = fnv1a32(f"{shift_id}#{i}") / 4294967296.0
    if u < 0.70:
        return "regular"
    if u < 0.80:
        return "tourist"
    return "vip" if u < 0.88 else "rush"


def combo_k(n: int) -> float:
    """Fare multiplier of a combo of ``n`` rides.

    Args:
        n: Combo length (0 or more).

    Returns:
        1.0 up to n = 1, then 1.1, 1.2 and at most 1.3.
    """
    return COMBO_K[4] if n >= 4 else COMBO_K[max(n, 1)]


def tip_for(fare: float, kind: str, combo: int) -> float:
    """Tip paid at a drop-off: kind rate plus the combo bonus.

    Args:
        fare: Fare, euros.
        kind: Passenger kind.
        combo: Combo length before this drop-off.

    Returns:
        The tip rounded to cents, euros.
    """
    return to_cents(fare * TIP_RATE[kind] + fare * (combo_k(combo) - 1))


def speed_at(shift: Shift, t: float) -> float:
    """Speed of the shift at game second ``t``.

    Args:
        shift: The shift.
        t: Game seconds from the shift start.

    Returns:
        km/h.
    """
    return shift.speed_by_hour[(shift.start_hour + int(t // 3600)) % 24]


def medal_of(shift: Shift, earned: float) -> int:
    """Medal for a total, thresholds as in ``calcResult`` (compared in cents).

    Args:
        shift: The shift (median, top10, ghost).
        earned: Player total, euros.

    Returns:
        0 none, 1 bronze, 2 silver, 3 gold, 4 legend.
    """
    ec = js_round(earned * 100)
    if earned >= LEGEND_K * shift.ghost - 1e-9:
        return 4
    if ec > js_round(shift.ghost * 100):
        return 3
    if ec >= js_round(shift.top10 * 100):
        return 2
    return 1 if ec >= js_round(shift.median * 100) else 0


# ---- data loading ----------------------------------------------------------------------------
def parse_order(raw: Sequence[Any], i: int, unit_m: float, shift_id: str) -> Order:
    """Turn one compact order array of CONTRACT section 4 into an :class:`Order`.

    Args:
        raw: ``[t, x0, y0, x1, y1, pts, d, km, fare, c, stand, taxi]`` (map units).
        i: Index in the shift.
        unit_m: Metres per map unit.
        shift_id: Shift id (the passenger kind hashes it).

    Returns:
        The order in metres.
    """
    pts = raw[5]
    n = len(pts) // 2 + 1
    cx, cy = raw[1], raw[2]
    xs, ys = [cx * unit_m], [cy * unit_m]
    for k in range(1, n):
        cx += pts[2 * k - 2]
        cy += pts[2 * k - 1]
        xs.append(cx * unit_m)
        ys.append(cy * unit_m)
    d = raw[6] if raw[6] > 0 else RIDE_STEP_S * (n - 1)
    return Order(
        i, float(raw[0]), raw[1] * unit_m, raw[2] * unit_m, raw[3] * unit_m, raw[4] * unit_m,
        float(d), raw[7], raw[8], raw[9], raw[10], kind_for(shift_id, i), xs, ys,
    )  # fmt: skip


def parse_shift(raw: dict[str, Any], unit_m: float) -> Shift:
    """Turn one shift object of ``game_data.json`` into a :class:`Shift`.

    Args:
        raw: The JSON shift (CONTRACT section 4).
        unit_m: Metres per map unit.

    Returns:
        The shift in metres.
    """
    sid = raw["id"]
    orders = [parse_order(a, i, unit_m, sid) for i, a in enumerate(raw["orders"])]
    hot = [Spot(h["x"] * unit_m, h["y"] * unit_m, h["w"]) for h in raw.get("hot", [])]
    surges = [
        Spot(s["x"] * unit_m, s["y"] * unit_m, s["r"] * unit_m, float(s["t0"]), float(s["t1"]))
        for s in raw.get("surges", [])
    ]
    ranking = raw["ranking"]
    return Shift(
        sid, raw["start_hour"], raw["detour"], list(raw["speed_by_hour"]), hot, surges, orders,
        raw["median"], raw["top10"], ranking[0] if ranking else 0.0, [o.t for o in orders],
    )  # fmt: skip


def load_shifts(path: Path) -> list[Shift]:
    """Read ``game_data.json`` (CONTRACT section 4).

    Args:
        path: Path of the JSON file.

    Returns:
        All shifts in campaign order.
    """
    import json

    raw = json.loads(path.read_text(encoding="utf-8"))
    unit_m = float(raw["unit_m"])
    return [parse_shift(s, unit_m) for s in raw["shifts"]]


# ---- the rivals: personas (25_ai.js PERS) ----------------------------------------------------
@dataclass(frozen=True)
class Persona:
    """Personal traits of one rival.

    Attributes:
        react: Personal reaction time, game s.
        repos: Seconds between repositioning drives while idle.
        travel: Driving time multiplier (dimensionless).
        attn: Personal attention multiplier (dimensionless).
    """

    react: float
    repos: float
    travel: float = 1.0
    attn: float = 1.0


PERSONAS = {
    "ze": Persona(24, 150),
    "fatima": Persona(40, 600),
    "rui": Persona(34, 300),
    "ines": Persona(16, 120),
    "tiago": Persona(20, 45),
    "lurdes": Persona(30, 240),
    "nuno": Persona(55, 90, 1.25, 0.7),
}


def _score_ze(o: Order, eta: float, pdist: float, surge: bool, air: bool) -> float:
    """Ze: best euros per minute."""
    return o.fare / (eta + o.d + 30)


def _score_fatima(o: Order, eta: float, pdist: float, surge: bool, air: bool) -> float:
    """Fatima: likes taxi-stand orders and short pickups."""
    return o.fare / (eta + o.d + 30) * (1.6 if o.c == 1 else 1) * (1.15 if eta < 300 else 1)


def _score_rui(o: Order, eta: float, pdist: float, surge: bool, air: bool) -> float:
    """Rui: long trips and the airport."""
    return o.fare / (eta + o.d + 30) * (1 + o.km / 8) * (1.5 if air else 1)


def _score_ines(o: Order, eta: float, pdist: float, surge: bool, air: bool) -> float:
    """Ines: short rides."""
    return o.fare / (eta + 0.5 * o.d + 60)


def _score_tiago(o: Order, eta: float, pdist: float, surge: bool, air: bool) -> float:
    """Tiago: hunts orders within 1500 m of the player (pdist is 1e9 on easy)."""
    return o.fare / (eta + o.d + 30) * (1.8 if pdist < 1500 else 1)


def _score_lurdes(o: Order, eta: float, pdist: float, surge: bool, air: bool) -> float:
    """Lurdes: demand waves count double."""
    return o.fare / (eta + o.d + 30) * (2 if surge else 1)


def _score_nuno(o: Order, eta: float, pdist: float, surge: bool, air: bool) -> float:
    """Nuno: nearest first, nothing over 5 km."""
    return 0 if o.km > 5 else 1 / (eta + 60)


SCORERS: dict[str, Callable[[Order, float, float, bool, bool], float]] = {
    "ze": _score_ze,
    "fatima": _score_fatima,
    "rui": _score_rui,
    "ines": _score_ines,
    "tiago": _score_tiago,
    "lurdes": _score_lurdes,
    "nuno": _score_nuno,
}


@dataclass(slots=True)
class Claim:
    """Who is on the way to an order.

    Attributes:
        by: ``player`` or a rival id.
        t1: Arrival time at the pickup, game s.
        boarded: True once a rival has the passenger on board.
    """

    by: str
    t1: float
    boarded: bool = False


@dataclass(slots=True)
class Rival:
    """State of one AI rival (``rv`` and ``rv.p`` of 25_ai.js merged).

    Attributes:
        id: Rival id.
        seed: Per-rival hash seed.
        state: 0 free, 1 to pickup, 2 riding, 3 on break.
        mode: ``idle``, ``cruise``, ``pickup``, ``ride`` or ``break``.
        x: Position, metres (not tracked while riding: nothing reads it then).
        y: Position, metres.
        total: Money, euros.
        rides: Pickups.
        target: Order on the way to, or None.
        cur: Order being served, or None.
        nxt: Game time of the next decision, s.
    """

    id: str
    seed: int
    state: int = 0
    mode: str = "idle"
    x: float = 0.0
    y: float = 0.0
    total: float = 0.0
    rides: int = 0
    target: Order | None = None
    cur: Order | None = None
    nxt: float = 0.0
    ptr: int = 0
    phase: float = 0.0
    free_at: float = 0.0
    last_repos: float = -1e9
    idle_since: float = 0.0
    next_break: float = 0.0
    break_until: float = 0.0
    surge_go: int = -1
    repos_n: int = 0
    lt0: float = 0.0
    lt1: float = 0.0
    lx0: float = 0.0
    ly0: float = 0.0
    lx1: float = 0.0
    ly1: float = 0.0
    u_att: list[float] = field(default_factory=list)
    u_rdy: list[float] = field(default_factory=list)


@dataclass(slots=True)
class Game:
    """Engine state of one shift (``PG.engine.G`` plus the AI state ``G.ai``).

    Attributes:
        sh: The shift.
        st: The settings.
        dn: Difficulty name.
        diff_k: Radar/lead scale of the difficulty.
        D: The rivals' sharpness on this difficulty.
        lead: Pin lead per order, game s (engine, double).
        ai_lead: The same, as the AI sees it (float32).
        max_lead: Longest ``ai_lead``, s.
        stands: Taxi-stand centres (Fatima's pool).
        hot: Hotspots sorted by weight.
        seed: Shift hash seed.
        rivals: The 7 rivals.
        t: Game time, s.
        x: Car x, metres.
        y: Car y, metres.
        mode: ``idle``, ``cruise``, ``pickup`` or ``ride``.
        tot: Player money, euros.
        cur: Order being served, or None.
        nxt: Booked next order, or None.
        claim: Claims by order index.
        taken: Order indices the player boarded.
    """

    sh: Shift
    st: Settings
    dn: str
    diff_k: float
    D: RivalDiff
    lead: list[float]
    ai_lead: list[float]
    max_lead: float
    stands: list[Spot]
    hot: list[Spot]
    seed: int
    rivals: list[Rival] = field(default_factory=list)
    t: float = 0.0
    x: float = HOME[0]
    y: float = HOME[1]
    mode: str = "idle"
    lt0: float = 0.0
    lt1: float = 0.0
    lx0: float = HOME[0]
    ly0: float = HOME[1]
    lx1: float = HOME[0]
    ly1: float = HOME[1]
    tot: float = 0.0
    rides: int = 0
    tips: float = 0.0
    combo: int = 0
    last_drop_t: float = -1e9
    cur: Order | None = None
    nxt: Order | None = None
    claim: dict[int, Claim] = field(default_factory=dict)
    taken: set[int] = field(default_factory=set)
    over: bool = False
    real_ptr: int = 0
    spawn_ptr: int = 0
    spawn_t: list[float] = field(default_factory=list)
    next_trail: float = TRAIL_EVERY_S
    sc_x: float = 0.0
    sc_y: float = 0.0
    sc_t: float = 0.0
    sc_eta: float = 0.0
    lost_to_rivals: int = 0
    rival_lost: int = 0


# ---- places (stands, hotspots) ---------------------------------------------------------------
def build_stands(shift: Shift) -> list[Spot]:
    """Centroids of the taxi stands that have at least 3 orders, busiest 8 first.

    Args:
        shift: The shift.

    Returns:
        Stand centres in metres; ``w`` is the share of the shift's orders.
    """
    acc: dict[int, list[float]] = {}
    for o in shift.orders:
        if o.stand > 0:
            a = acc.setdefault(o.stand, [0.0, 0.0, 0.0])
            a[0] += o.x0
            a[1] += o.y0
            a[2] += 1
    total = len(shift.orders)
    stands = [
        (a[2], Spot(a[0] / a[2], a[1] / a[2], a[2] / total)) for a in acc.values() if a[2] >= 3
    ]
    stands.sort(key=lambda s: -s[0])
    return [s[1] for s in stands[:8]]


def build_hot(shift: Shift) -> list[Spot]:
    """Density hotspots: the shift's own list by weight, else the 6 busiest 1 km cells.

    Args:
        shift: The shift.

    Returns:
        Hotspots in metres, heaviest first.
    """
    if shift.hot:
        return sorted(shift.hot, key=lambda s: -s.w)
    cells: dict[int, list[float]] = {}
    for o in shift.orders:
        key = math.floor(o.x0 / 1000) * 1000 + math.floor(o.y0 / 1000)
        c = cells.setdefault(key, [0.0, 0.0, 0.0])
        c[0] += o.x0
        c[1] += o.y0
        c[2] += 1
    spots = [
        (c[2], Spot(c[0] / c[2], c[1] / c[2], c[2] / len(shift.orders))) for c in cells.values()
    ]
    spots.sort(key=lambda s: -s[0])
    return [s[1] for s in spots[:6]]


def pick(arr: Sequence[Spot], u: float) -> Spot:
    """Pick an element by a uniform ``u`` in ``[0, 1)``.

    Args:
        arr: Non-empty sequence.
        u: Uniform number.

    Returns:
        The chosen element.
    """
    return arr[min(len(arr) - 1, math.floor(u * len(arr)))]


# ---- rival movement --------------------------------------------------------------------------
def is_night(shift: Shift, t: float) -> bool:
    """Rui's night: local hour 22..05.

    Args:
        shift: The shift.
        t: Game s.

    Returns:
        True at night.
    """
    h = (shift.start_hour + int(t // 3600)) % 24
    return h >= 22 or h <= 5


def rival_speed(g: Game, t: float) -> float:
    """Driving speed of the rivals at game second ``t``.

    Args:
        g: The game.
        t: Game s.

    Returns:
        km/h (shift speed times the difficulty scale).
    """
    return speed_at(g.sh, t) * g.D.speed


def react_time(g: Game, rv: Rival) -> float:
    """Personal reaction time on this difficulty.

    Args:
        g: The game.
        rv: The rival.

    Returns:
        Game s.
    """
    return PERSONAS[rv.id].react * g.D.react


def grid_up(rv: Rival, t: float) -> float:
    """Round ``t`` up to the rival's decision grid (5 s, personal phase).

    Args:
        rv: The rival.
        t: Game s.

    Returns:
        The first grid time at or after ``t``, game s.
    """
    return rv.phase + math.ceil((t - rv.phase) / GRID_S) * GRID_S


def start_leg(rv: Rival, t: float, tx: float, ty: float, dur: float) -> None:
    """Start a straight leg of a rival.

    Args:
        rv: The rival.
        t: Start time, game s.
        tx: Target x, metres.
        ty: Target y, metres.
        dur: Leg duration, s.
    """
    rv.lt0, rv.lt1 = t, t + dur
    rv.lx0, rv.ly0, rv.lx1, rv.ly1 = rv.x, rv.y, tx, ty


def leg_pos(rv: Rival, t: float) -> float:
    """Move a rival along its current leg to game time ``t``.

    Args:
        rv: The rival (position is updated).
        t: Game s.

    Returns:
        The share of the leg done (0..1).
    """
    span = rv.lt1 - rv.lt0
    f = clamp((t - rv.lt0) / span, 0.0, 1.0) if span > 0 else 1.0
    rv.x = rv.lx0 + (rv.lx1 - rv.lx0) * f
    rv.y = rv.ly0 + (rv.ly1 - rv.ly0) * f
    return f


def place(rv: Rival, t: float) -> None:
    """Bring a rival's position and mode to game time ``t`` (free and pickup legs only).

    Args:
        rv: The rival.
        t: Game s.
    """
    if rv.state == 0:
        if rv.mode == "cruise" and leg_pos(rv, t) >= 1:
            rv.mode = "idle"
            rv.idle_since = rv.lt1
    elif rv.state == 1:
        leg_pos(rv, t)


def drive_time(g: Game, rv: Rival, t: float, tx: float, ty: float) -> float:
    """Time for a rival to drive from where it is to ``(tx, ty)``.

    Args:
        g: The game.
        rv: The rival.
        t: Departure, game s.
        tx: Target x, metres.
        ty: Target y, metres.

    Returns:
        Seconds.
    """
    km = math.sqrt((tx - rv.x) ** 2 + (ty - rv.y) ** 2) / 1000
    return km * g.sh.detour / rival_speed(g, t) * 3600 * PERSONAS[rv.id].travel


def player_at(g: Game, t: float) -> tuple[float, float]:
    """Where the AI believes the player is at game second ``t``.

    Args:
        g: The game.
        t: Game s.

    Returns:
        ``(x, y)`` metres: interpolated on a pickup or cruise leg, else the car position of
        the last engine wake-up.
    """
    if g.mode in ("pickup", "cruise") and g.lt1 > g.lt0:
        f = clamp((t - g.lt0) / (g.lt1 - g.lt0), 0.0, 1.0)
        return g.lx0 + (g.lx1 - g.lx0) * f, g.ly0 + (g.ly1 - g.ly0) * f
    return g.x, g.y


def player_pending(g: Game, o: Order) -> bool:
    """True when the player is on the way to ``o`` or has it booked next.

    Args:
        g: The game.
        o: The order.

    Returns:
        Whether the player's claim on ``o`` is live.
    """
    return (g.cur is o and g.mode == "pickup") or g.nxt is o


def destination(g: Game, rv: Rival, t: float) -> tuple[float, float]:
    """Spot a rival drives to when it has nothing to do (its tactic).

    Args:
        g: The game.
        rv: The rival (its ``repos_n`` counter advances).
        t: Game s.

    Returns:
        ``(x, y)`` metres, inside the map.
    """
    u = mix(rv.seed, 100 + rv.repos_n)
    rv.repos_n += 1
    tx, ty = _tactic_spot(g, rv, t, u)
    return clamp(tx, 0.0, MAP_W_M), clamp(ty, 0.0, MAP_H_M)


def _tactic_spot(g: Game, rv: Rival, t: float, u: float) -> tuple[float, float]:
    """Raw idle destination of a rival by its id (see :func:`destination`)."""
    hot, rid, seed = g.hot, rv.id, rv.seed
    if rid == "fatima":
        s = pick(g.stands or hot, u)
        return s.x, s.y
    if rid == "rui":
        night = is_night(g.sh, t)
        if t > 0 and u < (0.6 if night else 0.25):
            return AIRPORT[0], AIRPORT[1]
        s = pick(hot, u * 3.7 % 1)
        return s.x, s.y
    if rid == "tiago":
        px, py = player_at(g, t)
        return px + (u - 0.5) * 900, py + (mix(seed, 7 + rv.repos_n) - 0.5) * 900
    if rid == "lurdes":
        s = active_surge(g.sh, t)
        if s is not None:
            return s.x, s.y
        h = hot[int(min(len(hot), 2) * u)]
        return h.x, h.y
    if rid == "nuno":
        s = pick(hot, u)
        return (
            s.x + (mix(seed, 11 + rv.repos_n) - 0.5) * 1500,
            s.y + (mix(seed, 13 + rv.repos_n) - 0.5) * 1500,
        )
    return _nearest_busy_spot(g, rv, t, u) if rid == "ines" else _busiest_spot(g, rv)


def active_surge(shift: Shift, t: float) -> Spot | None:
    """First demand wave that is running or starts within 240 s.

    Args:
        shift: The shift.
        t: Game s.

    Returns:
        The surge, or None.
    """
    for s in shift.surges:
        if s.t1 > t >= s.t0 - SURGE_HEAD_S:
            return s
    return None


def _nearest_busy_spot(g: Game, rv: Rival, t: float, u: float) -> tuple[float, float]:
    """Ines: the nearest hotspot that is not right here (at the start: the busiest)."""
    best, bd = g.hot[0], 1e18
    if t > 0:
        for h in g.hot:
            dd = (h.x - rv.x) ** 2 + (h.y - rv.y) ** 2
            if 90000 < dd < bd:
                bd, best = dd, h
    return best.x, best.y


def _busiest_spot(g: Game, rv: Rival) -> tuple[float, float]:
    """Ze: the hotspot with the best weight / distance, jittered per visit."""
    best, bs = g.hot[0], -1.0
    for i, h in enumerate(g.hot):
        dist = math.sqrt((h.x - rv.x) ** 2 + (h.y - rv.y) ** 2)
        sc = h.w / (1 + dist / 3000) * (0.7 + 0.6 * mix(rv.seed, 20 + rv.repos_n + i))
        if sc > bs:
            bs, best = sc, h
    return best.x, best.y


# ---- claims ----------------------------------------------------------------------------------
def claim_kind(g: Game, o: Order, t1: float, t: float) -> int:
    """May a rival go for ``o``? 0 no, 1 free, 2 steal from a rival, 3 steal from the player.

    Args:
        g: The game.
        o: The order.
        t1: The rival's arrival time, game s.
        t: Now, game s.

    Returns:
        The claim kind code.
    """
    c = g.claim.get(o.i)
    if c is None:
        return 1
    if c.by == "player":
        if not player_pending(g, o):
            return 1 if c.t1 > t else 0
        return 3 if (g.dn != "easy" and t1 < c.t1) else 0
    if c.boarded:
        return 0
    return 2 if t1 < c.t1 else 0


def claim_blocks(g: Game, o: Order, t1: float) -> bool:
    """Does a rival's claim block a player commit arriving at ``t1`` (engine hook)?

    Args:
        g: The game.
        o: The order.
        t1: The player's arrival, game s.

    Returns:
        True when the order is lost for the player.
    """
    c = g.claim.get(o.i)
    if c is None or c.by == "player":
        return False
    if c.boarded:
        return True
    if g.dn == "easy":
        return False  # the shield: a player commit always wins on easy
    return c.t1 <= t1


def lose(g: Game, rv: Rival, t: float) -> None:
    """A rival gives up its target and goes back to idle.

    Args:
        g: The game.
        rv: The rival.
        t: Game s.
    """
    place(rv, t)
    rv.state, rv.cur, rv.target, rv.mode = 0, None, None, "idle"
    rv.idle_since = t
    rv.free_at = t + 0.5 * react_time(g, rv)
    rv.nxt = grid_up(rv, rv.free_at)
    g.rival_lost += 1


def rival_by_id(g: Game, rid: str) -> Rival | None:
    """Find a rival by id.

    Args:
        g: The game.
        rid: Rival id.

    Returns:
        The rival, or None (for example ``player``).
    """
    for rv in g.rivals:
        if rv.id == rid:
            return rv
    return None


# ---- the rivals' decisions -------------------------------------------------------------------
def in_surge(shift: Shift, o: Order) -> bool:
    """Is the pickup of ``o`` inside a running demand wave?

    Args:
        shift: The shift.
        o: The order.

    Returns:
        True when ``o.t`` is within a surge's time span and its pickup within the radius.
    """
    for s in shift.surges:
        if s.t0 <= o.t <= s.t1 and (o.x0 - s.x) ** 2 + (o.y0 - s.y) ** 2 <= s.w * s.w:
            return True
    return False


def near_airport(o: Order) -> bool:
    """Does the trip of ``o`` start or end within 2.5 km of the airport (Rui's bonus)?

    Args:
        o: The order.

    Returns:
        True near the airport.
    """
    ax, ay, r = AIRPORT
    return (o.x0 - ax) ** 2 + (o.y0 - ay) ** 2 <= r * r or (o.x1 - ax) ** 2 + (
        o.y1 - ay
    ) ** 2 <= r * r


def attention(g: Game, rv: Rival, o: Order, night: bool, surge: bool) -> float:
    """Share of pins of this kind a rival notices away from the player.

    Args:
        g: The game.
        rv: The rival.
        o: The order.
        night: Local hour 22..05.
        surge: ``o`` is inside a demand wave.

    Returns:
        A probability in 0..1 (may exceed 1 for boosted cases).
    """
    at = g.D.attn * PERSONAS[rv.id].attn
    if rv.id == "rui" and night:
        return at * 1.4
    if rv.id == "fatima" and o.c == 1:
        return at * 2
    if rv.id == "lurdes" and surge:
        return at * 2.5
    return at * 0.6 if rv.id == "tiago" else at


def scan(g: Game, rv: Rival, t: float) -> tuple[Order, float, int] | None:
    """The best order a free rival decides to go for at game time ``t``.

    Args:
        g: The game.
        rv: The rival (its order pointer advances).
        t: Game s.

    Returns:
        ``(order, eta, claim kind)`` or None.
    """
    sh, d, orders = g.sh, g.D, g.sh.orders
    pers, rid = PERSONAS[rv.id], rv.id
    while rv.ptr < len(orders) and orders[rv.ptr].t < t:
        rv.ptr += 1
    track = d.near > 0 or rid == "tiago"
    px, py = player_at(g, t) if track else (0.0, 0.0)
    night = is_night(sh, t)
    owl = 0.7 if (rid == "rui" and night) else 1
    r0, rn = pers.react * d.react * owl, pers.react * d.near_react * owl
    km_k = sh.detour / rival_speed(g, t) * 3600 * pers.travel / 1000
    scorer = SCORERS[rid]
    best: tuple[Order, float, int] | None = None
    best_score = -1.0
    t_end = t + g.max_lead
    for i in range(rv.ptr, len(orders)):
        o = orders[i]
        if o.t > t_end:
            break
        spawn = o.t - g.ai_lead[o.i]
        if spawn > t:
            continue
        eta = math.sqrt((o.x0 - rv.x) ** 2 + (o.y0 - rv.y) ** 2) * km_k + BOARD_S
        if t + eta > o.t or o.i in g.taken:
            continue
        kind = claim_kind(g, o, t + eta, t)
        if kind == 0:
            continue
        sc = _consider(g, rv, o, eta, t, spawn, (px, py, track, night, r0, rn), scorer)
        if sc is not None and sc > best_score:
            best_score, best = sc, (o, eta, kind)
    return best


def _consider(
    g: Game,
    rv: Rival,
    o: Order,
    eta: float,
    t: float,
    spawn: float,
    ctx: tuple[float, float, bool, bool, float, float],
    scorer: Callable[[Order, float, float, bool, bool], float],
) -> float | None:
    """Perception, attention and reaction gates of one candidate; its score or None."""
    px, py, track, night, r0, rn = ctx
    d = g.D
    near, pdist = False, 1e9
    if track:
        pdist = math.sqrt((o.x0 - px) ** 2 + (o.y0 - py) ** 2)
        near = d.near > 0 and pdist <= d.near
    if not near:
        dist = math.sqrt((o.x0 - rv.x) ** 2 + (o.y0 - rv.y) ** 2)
        if dist > g.st.radius[o.c] * d.radius:
            return None
    if rv.id == "tiago" and g.dn == "easy":
        pdist = 1e9
    surge = rv.id == "lurdes" and in_surge(g.sh, o)
    air = rv.id == "rui" and near_airport(o)
    if near:
        ready = spawn + NOTICE_K * rn * (0.8 + 0.4 * rv.u_rdy[o.i])
    else:
        if rv.u_att[o.i] >= attention(g, rv, o, night, surge):
            return None
        ready = spawn + NOTICE_K * r0 * (0.8 + 0.4 * rv.u_rdy[o.i])
    if ready > t:
        return None
    return scorer(o, eta, pdist, surge, air)


def commit(g: Game, rv: Rival, t: float, o: Order, eta: float, kind: int) -> None:
    """A rival commits to ``o`` (claims, steals, leg).

    Args:
        g: The game.
        rv: The rival.
        t: Game s.
        o: The order.
        eta: Pickup time, s.
        kind: Claim kind from :func:`claim_kind` (1, 2 or 3).
    """
    t1 = t + eta
    place(rv, t)
    c = g.claim.get(o.i)
    if c is None:
        g.claim[o.i] = Claim(rv.id, t1, False)
    else:
        loser = rival_by_id(g, c.by) if kind == 2 else None
        c.by, c.t1, c.boarded = rv.id, t1, False
        if kind == 3:
            g.lost_to_rivals += 1
        if loser is not None and loser is not rv:
            lose(g, loser, t)
    start_leg(rv, t, o.x0, o.y0, eta)
    rv.state, rv.cur, rv.nxt, rv.target, rv.mode = 1, o, t1, o, "pickup"


def start_break(g: Game, rv: Rival, t: float) -> None:
    """Send a rival on its break (work and break cycle).

    Args:
        g: The game.
        rv: The rival.
        t: Game s.
    """
    place(rv, t)
    duty = g.D.duty
    length = CYCLE_S * (1 - duty) * (0.8 + 0.4 * mix(rv.seed, 5 + rv.repos_n))
    rv.repos_n += 1
    rv.state, rv.mode, rv.target = 3, "break", None
    rv.break_until = t + length
    rv.next_break = rv.break_until + CYCLE_S * duty * (0.8 + 0.4 * mix(rv.seed, 9 + rv.repos_n))
    rv.nxt = rv.break_until


def _surge_headed(g: Game, rv: Rival, t: float, go: bool) -> bool:
    """Lurdes: drive to a running or imminent surge when not already on the way."""
    for j, s in enumerate(g.sh.surges):
        if s.t1 > t >= s.t0 - SURGE_HEAD_S:
            far = (s.x - rv.x) ** 2 + (s.y - rv.y) ** 2 > s.w * s.w * 0.25
            if rv.surge_go != j or far:
                if rv.mode != "cruise" or rv.surge_go != j:
                    go = True
                rv.surge_go = j
            break
    return go


def _free_step(g: Game, rv: Rival, t: float) -> None:
    """Decision of a free rival: take an order, else reposition now and then."""
    place(rv, t)
    if t >= rv.next_break:
        start_break(g, rv, t)
        return
    if t >= rv.free_at:
        found = scan(g, rv, t)
        if found is not None:
            commit(g, rv, t, *found)
            return
        go = t - rv.last_repos >= PERSONAS[rv.id].repos
        if rv.id == "lurdes":
            go = _surge_headed(g, rv, t, go)
        if go and t - rv.idle_since >= 10:
            tx, ty = destination(g, rv, t)
            rv.last_repos = t
            if (tx - rv.x) ** 2 + (ty - rv.y) ** 2 > MIN_REPOS_M2:
                start_leg(rv, t, tx, ty, max(1.0, drive_time(g, rv, t, tx, ty)))
                rv.mode = "cruise"
    rv.nxt = t + GRID_S


def process(g: Game, rv: Rival, t: float) -> None:
    """Run one wake-up of a rival at game time ``t`` (state machine of 25_ai.js).

    Args:
        g: The game.
        rv: The rival.
        t: Game s.
    """
    if rv.state == 0:
        _free_step(g, rv, t)
    elif rv.state == 1:
        o = rv.cur
        assert o is not None
        rv.x, rv.y = rv.lx1, rv.ly1
        rv.total = to_cents(rv.total + o.fare)
        rv.rides += 1
        c = g.claim.get(o.i)
        if c is not None and c.by == rv.id:
            c.boarded = True
        rv.state, rv.mode = 2, "ride"
        rv.lt0, rv.lt1, rv.nxt = t, t + o.d, t + o.d
    elif rv.state == 2:
        o = rv.cur
        assert o is not None
        rv.x, rv.y = o.x1, o.y1
        rv.state, rv.cur, rv.target, rv.mode = 0, None, None, "idle"
        rv.idle_since = t
        rv.free_at = t + 0.5 * react_time(g, rv) * (0.8 + 0.4 * mix(rv.seed, 3000 + rv.rides))
        rv.nxt = grid_up(rv, max(t, rv.free_at))
    else:
        rv.state, rv.mode, rv.idle_since = 0, "idle", t
        rv.free_at = t + 0.3 * react_time(g, rv)
        rv.nxt = grid_up(rv, rv.free_at)


def ai_tick(g: Game, t0: float, t1: float) -> None:
    """Process every rival wake-up in ``(t0, t1]`` in time order (lowest index wins ties).

    Args:
        g: The game.
        t0: Interval start, game s (unused: wake-ups are due when ``nxt <= t1``).
        t1: Interval end, game s.
    """
    rs = g.rivals
    for _ in range(200000):
        bi, bt = -1, math.inf
        for i, rv in enumerate(rs):
            if rv.nxt < bt:
                bt, bi = rv.nxt, i
        if bi < 0 or bt > t1:
            break
        process(g, rs[bi], bt)
    for rv in rs:
        place(rv, t1)


def on_player_commit(g: Game, o: Order) -> None:
    """The player committed to ``o``: rivals already heading there go back to idle.

    Args:
        g: The game.
        o: The order.
    """
    for rv in g.rivals:
        if rv.state == 1 and rv.target is o:
            lose(g, rv, g.t)


# ---- engine ----------------------------------------------------------------------------------
def make_rival(g: Game, k: int) -> Rival:
    """Create rival number ``k`` at its first spot with its first reaction time.

    Args:
        g: The game (stands and hotspots must be ready).
        k: Index in ``RIVAL_IDS``.

    Returns:
        The rival.
    """
    rid = RIVAL_IDS[k]
    seed = (g.seed ^ fnv(rid)) & MASK32
    n = len(g.sh.orders)
    rv = Rival(rid, seed)
    rv.u_att = [mix(seed, 2 * i + 1) for i in range(n)]
    rv.u_rdy = [mix(seed, 2 * i + 2) for i in range(n)]
    rv.phase = math.floor(mix(seed, 1) * GRID_S)
    duty = g.D.duty
    rv.next_break = 1e9 if duty >= 1 else CYCLE_S * duty * (0.3 + 0.7 * mix(seed, 2))
    rv.x, rv.y = destination(g, rv, 0.0)
    rv.free_at = react_time(g, rv) * mix(seed, 3)
    rv.nxt = grid_up(rv, rv.free_at)
    return rv


def new_game(shift: Shift, difficulty: str, settings: Settings) -> Game:
    """Build the state of a new shift (``newGame`` plus ``PG.ai.init``).

    Args:
        shift: The shift.
        difficulty: ``easy``, ``normal`` or ``hard``.
        settings: The balance levers.

    Returns:
        The game at ``t = 0``.
    """
    k = settings.diff_k[difficulty]
    lead = [settings.lead[o.c] * k * (RUSH_LEAD_K if o.kind == "rush" else 1) for o in shift.orders]
    ai_lead = [f32(v) for v in lead]
    g = Game(
        shift, settings, difficulty, k, settings.rivals[difficulty], lead, ai_lead,
        max(ai_lead, default=0.0), build_stands(shift), build_hot(shift), fnv(shift.id),
    )  # fmt: skip
    g.rivals = [make_rival(g, i) for i in range(len(RIVAL_IDS))]
    spawn = sorted(o.t - lead[o.i] for o in shift.orders)
    g.spawn_t = spawn
    while g.spawn_ptr < len(spawn) and spawn[g.spawn_ptr] <= EPS:
        g.spawn_ptr += 1
    return g


def eta_from(g: Game, fx: float, fy: float, t: float, o: Order) -> float:
    """Seconds to drive from ``(fx, fy)`` to the pickup of ``o`` (leaving at ``t``) plus boarding.

    Args:
        g: The game.
        fx: Start x, metres.
        fy: Start y, metres.
        t: Departure, game s.
        o: The order.

    Returns:
        Seconds.
    """
    return (
        math.hypot(o.x0 - fx, o.y0 - fy) / 1000 * g.sh.detour / speed_at(g.sh, t) * 3600 + BOARD_S
    )


def visible(g: Game, o: Order) -> bool:
    """Is the pin of ``o`` on the player's radar now (lead window and radius)?

    Args:
        g: The game.
        o: The order.

    Returns:
        True when visible.
    """
    if g.over or g.t >= o.t or g.t < o.t - g.lead[o.i] - EPS:
        return False
    return math.hypot(o.x0 - g.x, o.y0 - g.y) <= g.st.radius[o.c] * g.diff_k


def feasibility(g: Game, o: Order, relaxed: bool) -> int:
    """The single feasibility function of the engine; fills the ``sc_*`` scratch fields.

    Args:
        g: The game.
        o: The order.
        relaxed: Skip the radar test (re-validating a booked order).

    Returns:
        ``OK``, ``GONE`` or ``LATE``.
    """
    if g.mode == "ride":
        assert g.cur is not None
        g.sc_x, g.sc_y, g.sc_t = g.cur.x1, g.cur.y1, g.lt1
    else:
        g.sc_x, g.sc_y, g.sc_t = g.x, g.y, g.t
    g.sc_eta = eta_from(g, g.sc_x, g.sc_y, g.sc_t, o)
    if g.over or o.i in g.taken:
        return GONE
    cl = g.claim.get(o.i)
    if cl is not None and cl.by != "player" and claim_blocks(g, o, g.sc_t + g.sc_eta):
        return GONE
    if relaxed:
        if g.t >= o.t:
            return LATE
    elif not visible(g, o):
        return LATE
    return LATE if g.sc_t + g.sc_eta > o.t + EPS else OK


def release(g: Game, o: Order | None) -> None:
    """Drop the player's claim on an order the player gives up.

    Args:
        g: The game.
        o: The order or None.
    """
    if o is None:
        return
    cl = g.claim.get(o.i)
    if cl is not None and cl.by == "player":
        del g.claim[o.i]


def commit_player(g: Game, o: Order, t1: float) -> None:
    """Record a player commitment on ``o`` and tell the rivals.

    Args:
        g: The game.
        o: The order.
        t1: Arrival at the pickup, game s.
    """
    g.claim[o.i] = Claim("player", t1)
    on_player_commit(g, o)


def begin_leg(g: Game, mode: str, x1: float, y1: float, t0: float, t1: float) -> None:
    """Start a straight leg of the player's car.

    Args:
        g: The game.
        mode: ``pickup`` or ``cruise``.
        x1: Target x, metres.
        y1: Target y, metres.
        t0: Start, game s.
        t1: End, game s.
    """
    g.lt0, g.lt1, g.lx0, g.ly0, g.lx1, g.ly1 = t0, t1, g.x, g.y, x1, y1
    g.mode = mode


def start_pickup(g: Game, o: Order) -> bool:
    """Send the car to pick up ``o`` (not while riding).

    Args:
        g: The game.
        o: The order.

    Returns:
        True when accepted.
    """
    if g.over or g.mode == "ride" or feasibility(g, o, False) != OK:
        return False
    if g.mode == "pickup":
        release(g, g.cur)
    g.cur = o
    eta = g.sc_eta
    begin_leg(g, "pickup", o.x0, o.y0, g.t, g.t + eta)
    commit_player(g, o, g.t + eta)
    return True


def book_next(g: Game, o: Order) -> bool:
    """Book ``o`` as the next order while riding.

    Args:
        g: The game.
        o: The order.

    Returns:
        True when accepted.
    """
    if g.over or g.mode != "ride" or feasibility(g, o, False) != OK:
        return False
    if g.nxt is not None:
        release(g, g.nxt)
    g.nxt = o
    commit_player(g, o, g.sc_t + g.sc_eta)
    return True


def cruise_to(g: Game, x: float, y: float) -> bool:
    """Free drive to a point (not while riding; cancels a pickup).

    Args:
        g: The game.
        x: Target x, metres (clamped to the map).
        y: Target y, metres (clamped to the map).

    Returns:
        True when the car moves.
    """
    if g.over or g.mode == "ride":
        return False
    x, y = clamp(x, 0.0, MAP_W_M), clamp(y, 0.0, MAP_H_M)
    if g.mode == "pickup":
        release(g, g.cur)
        g.cur = None
    dist = math.hypot(x - g.x, y - g.y)
    if dist < 1:
        g.mode = "idle"
        return True
    dur = dist / 1000 * g.sh.detour / speed_at(g.sh, g.t) * 3600
    begin_leg(g, "cruise", x, y, g.t, g.t + dur)
    return True


def ride_pos(o: Order, f: float) -> tuple[float, float]:
    """Position on the route of ``o`` ``f`` seconds after pickup.

    Args:
        o: The order.
        f: Seconds since pickup (clamped to the ride).

    Returns:
        ``(x, y)`` metres.
    """
    n = len(o.xs)
    if n < 2:
        return o.x0, o.y0
    f = max(f, 0.0)
    i = min(int(f // RIDE_STEP_S), n - 2)
    fr = min((f - RIDE_STEP_S * i) / RIDE_STEP_S, 1.0)
    return o.xs[i] + (o.xs[i + 1] - o.xs[i]) * fr, o.ys[i] + (o.ys[i + 1] - o.ys[i]) * fr


def update_pos(g: Game) -> None:
    """Move the car to its position at ``g.t``.

    Args:
        g: The game.
    """
    if g.mode == "ride":
        assert g.cur is not None
        g.x, g.y = ride_pos(g.cur, g.t - g.lt0)
    elif g.mode in ("pickup", "cruise"):
        dur = g.lt1 - g.lt0
        f = clamp((g.t - g.lt0) / dur, 0.0, 1.0) if dur > 0 else 1.0
        g.x = g.lx0 + (g.lx1 - g.lx0) * f
        g.y = g.ly0 + (g.ly1 - g.ly0) * f


def on_pickup(g: Game) -> None:
    """The pickup leg ended: take the fare, start the ride, update the combo.

    Args:
        g: The game.
    """
    o = g.cur
    assert o is not None
    tev = g.lt1
    g.x, g.y = o.x0, o.y0
    g.tot = to_cents(g.tot + o.fare)
    g.rides += 1
    g.taken.add(o.i)
    g.lt0, g.lt1 = tev, tev + o.d
    g.lx0, g.ly0, g.lx1, g.ly1 = o.x0, o.y0, o.x1, o.y1
    g.mode = "ride"
    # 22_rules.js reads the leg end as "now", which is already the end of the ride here
    if g.combo > 0 and g.lt1 <= g.last_drop_t + COMBO_WINDOW_S:
        g.combo += 1
    else:
        g.combo = 1


def on_dropoff(g: Game) -> None:
    """The ride ended: pay the tip, then start the booked order or park.

    Args:
        g: The game.
    """
    o = g.cur
    assert o is not None
    tev = g.lt1
    g.x, g.y = o.x1, o.y1
    tip = tip_for(o.fare, o.kind, g.combo)
    g.tips = to_cents(g.tips + tip)
    g.last_drop_t = tev
    if tip > 0:
        g.tot = to_cents(g.tot + tip)
    g.cur, g.mode = None, "idle"
    g.lt0 = g.lt1 = tev
    nx = g.nxt
    if nx is None:
        return
    g.nxt = None
    release(g, nx)
    if feasibility(g, nx, True) == OK:
        g.cur = nx
        begin_leg(g, "pickup", nx.x0, nx.y0, tev, tev + g.sc_eta)
        commit_player(g, nx, tev + g.sc_eta)


def process_due(g: Game) -> None:
    """Process everything due at ``g.t``: clock pointers, then the player's leg ends.

    Args:
        g: The game.
    """
    orders, tt = g.sh.orders, g.t + EPS
    while g.real_ptr < len(orders) and orders[g.real_ptr].t <= tt:
        g.real_ptr += 1
    while g.spawn_ptr < len(g.spawn_t) and g.spawn_t[g.spawn_ptr] <= tt:
        g.spawn_ptr += 1
    while g.next_trail <= tt:
        g.next_trail += TRAIL_EVERY_S
    for _ in range(8):
        if g.mode == "idle" or g.lt1 > tt:
            break
        if g.mode == "pickup":
            on_pickup(g)
        elif g.mode == "ride":
            on_dropoff(g)
        else:
            g.x, g.y, g.mode = g.lx1, g.ly1, "idle"


def next_time(g: Game, t_end: float) -> float:
    """Earliest engine event not after ``t_end`` (leg end, real money, pin spawn, trail).

    Args:
        g: The game.
        t_end: Step end, game s.

    Returns:
        The event time, or infinity when only the step end is left.
    """
    te = g.lt1 if g.mode != "idle" else math.inf
    orders = g.sh.orders
    if g.real_ptr < len(orders) and orders[g.real_ptr].t < te:
        te = orders[g.real_ptr].t
    if g.spawn_ptr < len(g.spawn_t) and g.spawn_t[g.spawn_ptr] < te:
        te = g.spawn_t[g.spawn_ptr]
    te = min(te, g.next_trail)
    if te > t_end + EPS:
        return math.inf
    return max(te, g.t)


def drop_stolen(g: Game) -> None:
    """A rival that arrives first took the claim: the player's pickup or booked order falls back.

    Args:
        g: The game.
    """
    if g.mode == "pickup" and g.cur is not None:
        cl = g.claim.get(g.cur.i)
        if cl is not None and cl.by != "player":
            g.cur, g.mode = None, "idle"
            g.lt0 = g.lt1 = g.t
    if g.nxt is not None:
        cl = g.claim.get(g.nxt.i)
        if cl is not None and cl.by != "player":
            g.nxt = None


def advance(g: Game, te: float) -> None:
    """Move ``g.t`` forward to ``te``: position, then the rivals' interval.

    Args:
        g: The game.
        te: New game time, s.
    """
    t0 = g.t
    if te > t0:
        g.t = te
    update_pos(g)
    if te > t0:
        ai_tick(g, t0, te)
        drop_stolen(g)


def step(g: Game, dt: float) -> None:
    """Advance the game by ``dt`` game seconds (clamped to the shift end), events in time order.

    Args:
        g: The game.
        dt: Step, game s.
    """
    if g.over or not dt > 0:
        return
    t_end = g.t + dt
    if t_end > SHIFT_S - SHIFT_EPS:
        t_end = SHIFT_S
    for _ in range(200000):
        te = next_time(g, t_end)
        if te == math.inf:
            advance(g, t_end)
            break
        advance(g, te)
        process_due(g)
    if t_end >= SHIFT_S:
        g.t = SHIFT_S
        g.over = True


# ---- the greedy bot of engine_test.mjs -------------------------------------------------------
def bot_tick(g: Game) -> None:
    """One decision of the greedy bot: best fare per second among reachable pins, else cruise.

    Args:
        g: The game.
    """
    riding = g.mode == "ride"
    if g.mode == "pickup" or (riding and g.nxt is not None):
        return
    orders, delay = g.sh.orders, g.st.delay
    best, best_score = None, -1.0
    lo = bisect.bisect_left(g.sh.times, g.t)
    for k in range(lo, len(orders)):
        o = orders[k]
        if o.t > g.t + BOT_WINDOW_S:
            break
        if delay and g.t < o.t - g.lead[o.i] + delay:
            continue
        if feasibility(g, o, False) != OK:
            continue
        score = o.fare / (g.sc_eta + o.d)
        if score > best_score:
            best_score, best = score, o
    if best is not None:
        if riding:
            book_next(g, best)
        else:
            start_pickup(g, best)
        return
    if not riding:
        _bot_cruise(g)


def _bot_cruise(g: Game) -> None:
    """Idle bot: drive towards the nearest pin due within 400 s."""
    orders = g.sh.orders
    near, nd = None, math.inf
    lo = bisect.bisect_right(g.sh.times, g.t)
    for k in range(lo, len(orders)):
        o = orders[k]
        if o.t > g.t + CRUISE_WINDOW_S:
            break
        d = math.hypot(o.x0 - g.x, o.y0 - g.y)
        if d < nd:
            nd, near = d, o
    if near is None or nd <= CRUISE_MIN_M:
        return
    if g.mode == "idle" or math.hypot(g.lx1 - near.x0, g.ly1 - near.y0) > 50:
        cruise_to(g, near.x0, near.y0)


def play_shift(shift: Shift, difficulty: str, settings: Settings) -> ShiftResult:
    """Play one shift with the bot against the 7 rivals.

    Args:
        shift: The shift.
        difficulty: ``easy``, ``normal`` or ``hard``.
        settings: The balance levers.

    Returns:
        The result of the shift.
    """
    g = new_game(shift, difficulty, settings)
    for _ in range(BOT_TICKS):
        if g.over:
            break
        bot_tick(g)
        step(g, BOT_STEP_S)
    earned = to_cents(g.tot)
    ec = js_round(earned * 100)
    place_n = 1 + sum(1 for rv in g.rivals if js_round(rv.total * 100) > ec)
    return ShiftResult(
        shift.id, earned, medal_of(shift, earned), g.rides, g.lost_to_rivals, g.rival_lost,
        tuple(rv.total for rv in g.rivals), tuple(rv.rides for rv in g.rivals), place_n,
    )  # fmt: skip


# ---- many shifts at once ---------------------------------------------------------------------
_WORKER_SHIFTS: list[Shift] = []


def _init_worker(path: str) -> None:
    """Load the data once per worker process."""
    _WORKER_SHIFTS[:] = load_shifts(Path(path))


def _job(args: tuple[int, str, Settings]) -> ShiftResult:
    """Play one (shift, difficulty) job inside a worker process."""
    idx, difficulty, settings = args
    return play_shift(_WORKER_SHIFTS[idx], difficulty, settings)


def open_pool(data: Path, workers: int) -> ProcessPoolExecutor:
    """Start a worker pool whose processes have loaded the game data once.

    Args:
        data: Path of ``game_data.json``.
        workers: Worker processes.

    Returns:
        A pool to pass to :func:`play_many`; use it as a context manager.
    """
    return ProcessPoolExecutor(workers, initializer=_init_worker, initargs=(str(data),))


def play_many(
    jobs: Iterable[tuple[int, str, Settings]],
    data: Path,
    workers: int,
    pool: ProcessPoolExecutor | None = None,
) -> list[ShiftResult]:
    """Play many (shift index, difficulty, settings) jobs, in parallel when asked.

    Args:
        jobs: Jobs to run.
        data: Path of ``game_data.json`` (each worker loads it once).
        workers: Worker processes (1 = in this process); ignored when ``pool`` is given.
        pool: An open pool from :func:`open_pool`, reused across calls (faster for sweeps).

    Returns:
        Results in the order of ``jobs``.
    """
    job_list = list(jobs)
    if pool is not None:
        return list(pool.map(_job, job_list, chunksize=4))
    if workers <= 1:
        _init_worker(str(data))
        return [_job(j) for j in job_list]
    with open_pool(data, workers) as own:
        return list(own.map(_job, job_list, chunksize=4))


@dataclass(frozen=True)
class Summary:
    """Aggregate of the results of one difficulty over many shifts.

    Attributes:
        n: Shifts played.
        bronze: Share with at least a bronze medal (0..1).
        silver: Share with at least silver (0..1).
        gold: Share with at least gold (0..1).
        legend: Share with legend (0..1).
        bot_eur: Mean bot total per shift, euros.
        lost: Mean orders lost to rivals per shift.
        rival_eur: Mean total per shift of each rival in ``RIVAL_IDS`` order, euros.
        rival_rides: Mean pickups per shift of each rival.
        place: Mean race place of the player (1..8).
    """

    n: int
    bronze: float
    silver: float
    gold: float
    legend: float
    bot_eur: float
    lost: float
    rival_eur: tuple[float, ...]
    rival_rides: tuple[float, ...]
    place: float


def summarise(results: Sequence[ShiftResult]) -> Summary:
    """Aggregate shift results.

    Args:
        results: At least one result of the same difficulty.

    Returns:
        The medal shares and the means.
    """
    n = len(results)
    share = [sum(1 for r in results if r.medal >= m) / n for m in (1, 2, 3, 4)]
    cols = len(RIVAL_IDS)
    return Summary(
        n, share[0], share[1], share[2], share[3],
        sum(r.earned for r in results) / n,
        sum(r.lost_to_rivals for r in results) / n,
        tuple(sum(r.rival_eur[k] for r in results) / n for k in range(cols)),
        tuple(sum(r.rival_rides[k] for r in results) / n for k in range(cols)),
        sum(r.race_place for r in results) / n,
    )  # fmt: skip


def run_difficulties(
    data: Path,
    settings: Settings,
    difficulties: Sequence[str],
    workers: int,
    n_shifts: int,
    pool: ProcessPoolExecutor | None = None,
) -> dict[str, list[ShiftResult]]:
    """Play every shift on each given difficulty.

    Args:
        data: Path of ``game_data.json``.
        settings: The balance levers.
        difficulties: Difficulty names.
        workers: Worker processes.
        n_shifts: Number of shifts (the first ones).
        pool: An open pool from :func:`open_pool`, or None.

    Returns:
        Results per difficulty, in shift order.
    """
    jobs = [(i, d, settings) for d in difficulties for i in range(n_shifts)]
    flat = play_many(jobs, data, workers, pool)
    return {d: flat[k * n_shifts : (k + 1) * n_shifts] for k, d in enumerate(difficulties)}


# ---- fidelity against the real JS engine -----------------------------------------------------
SHIFT_ROW = re.compile(
    r"^([a-z]{3}-[a-z]+)\s+(-?[\d.]+)\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+\d\s+\d+/\d+\s+\d+\s+\d+\s*$"
)
DIFF_ROW = re.compile(r"^\s+(easy|normal|hard)\s+bot avg €([\d.]+)")
RIVAL_ROW = re.compile(r"^\s+ze €")
RIVAL_CELL = re.compile(r"([a-z]+) €([\d.]+) r([\d.]+)")


@dataclass(frozen=True)
class EngineRef:
    """Numbers parsed from the output of ``node tools/engine_test.mjs``.

    Attributes:
        shift_eur: Bot total per shift id, normal, no reaction delay, euros (section 3).
        bot_eur: Mean bot total per difficulty with the 200 s bot, euros (section 6).
        rival_eur: Mean rival total per difficulty and rival id, euros (section 6).
    """

    shift_eur: dict[str, float]
    bot_eur: dict[str, float]
    rival_eur: dict[str, dict[str, float]]


def parse_engine_test(text: str) -> EngineRef:
    """Parse the output of ``tools/engine_test.mjs`` (sections 3 and 6).

    Args:
        text: Standard output of the Node test.

    Returns:
        The reference numbers.
    """
    shift_eur: dict[str, float] = {}
    bot_eur: dict[str, float] = {}
    rival_eur: dict[str, dict[str, float]] = {}
    current = ""
    for line in text.splitlines():
        m = SHIFT_ROW.match(line)
        if m:
            shift_eur[m.group(1)] = float(m.group(2))
            continue
        m = DIFF_ROW.match(line)
        if m:
            current = m.group(1)
            bot_eur[current] = float(m.group(2))
        elif RIVAL_ROW.match(line) and current:
            rival_eur[current] = {k: float(v) for k, v, _ in RIVAL_CELL.findall(line)}
    return EngineRef(shift_eur, bot_eur, rival_eur)


def rel_diff(a: float, b: float) -> float:
    """Relative difference of ``a`` to the reference ``b``.

    Args:
        a: Measured value.
        b: Reference value.

    Returns:
        ``(a - b) / b`` (0 when both are 0, infinity when only ``b`` is 0).
    """
    if b == 0:
        return 0.0 if a == 0 else math.inf
    return (a - b) / b


def compare_lines(ref: EngineRef, shifts: Sequence[Shift], data: Path, workers: int) -> list[str]:
    """Run this twin on the same settings as the JS test and describe the differences.

    Args:
        ref: Parsed output of ``engine_test.mjs``.
        shifts: The shifts of the data file.
        data: Path of ``game_data.json``.
        workers: Worker processes.

    Returns:
        Report lines (a table and the mean absolute differences).
    """
    lines: list[str] = []
    plain = Settings(delay=0.0)
    res = play_many([(i, "normal", plain) for i in range(len(shifts))], data, workers)
    diffs = [
        rel_diff(r.earned, ref.shift_eur[r.shift_id]) for r in res if r.shift_id in ref.shift_eur
    ]
    lines.append(f"(3) bot per shift, normal, no delay: mean |diff| {_mean_abs(diffs):.1%}")
    for r in res:
        if r.shift_id in ref.shift_eur:
            lines.append(
                f"    {r.shift_id:<10} sim {r.earned:7.2f}  js {ref.shift_eur[r.shift_id]:7.2f}"
            )
    by_diff = run_difficulties(data, Settings(), DIFFICULTIES, workers, len(shifts))
    all_diffs: list[float] = []
    for d in DIFFICULTIES:
        sm = summarise(by_diff[d])
        lines.append(f"(6) {d}: bot sim {sm.bot_eur:.1f} js {ref.bot_eur[d]:.1f}")
        all_diffs.append(rel_diff(sm.bot_eur, ref.bot_eur[d]))
        for rid, eur in zip(RIVAL_IDS, sm.rival_eur, strict=True):
            js = ref.rival_eur[d][rid]
            all_diffs.append(rel_diff(eur, js))
            lines.append(f"      {rid:<7} sim {eur:5.1f} js {js:5.1f} ({rel_diff(eur, js):+.1%})")
    lines.append(f"(6) bot and rival averages: mean |diff| {_mean_abs(all_diffs):.1%}")
    return lines


def _mean_abs(xs: Sequence[float]) -> float:
    """Mean of the absolute values (0 for an empty list)."""
    return sum(abs(x) for x in xs) / len(xs) if xs else 0.0


def format_summary(difficulty: str, sm: Summary) -> str:
    """One table row of a difficulty summary.

    Args:
        difficulty: Difficulty name.
        sm: The summary.

    Returns:
        A line with medal shares, bot euros, lost orders and mean rival euros.
    """
    riv = sum(sm.rival_eur) / len(sm.rival_eur)
    return (
        f"{difficulty:<7} bronze+ {sm.bronze:4.0%} silver+ {sm.silver:4.0%} gold+ {sm.gold:4.0%} "
        f"legend {sm.legend:4.0%} | bot €{sm.bot_eur:5.1f} lost {sm.lost:3.1f} rival €{riv:5.1f}"
    )


def main(argv: list[str] | None = None) -> int:
    """CLI: play every shift on every difficulty, print the table, optionally the fidelity check.

    Args:
        argv: Command-line arguments (default: ``sys.argv[1:]``).

    Returns:
        0 on success, 1 when the Node reference could not be run.
    """
    ap = argparse.ArgumentParser(description="Python twin of the game engine, rivals and bot")
    ap.add_argument("--data", type=Path, default=Path("game/game_data.json"))
    ap.add_argument("--compare", action="store_true", help="compare with tools/engine_test.mjs")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args(argv)
    shifts = load_shifts(args.data)
    by_diff = run_difficulties(args.data, Settings(), DIFFICULTIES, args.workers, len(shifts))
    for d in DIFFICULTIES:
        print(format_summary(d, summarise(by_diff[d])))
    if not args.compare:
        return 0
    proc = subprocess.run(
        ["node", "tools/engine_test.mjs", "--data", str(args.data)],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    if proc.returncode != 0:
        print(proc.stdout[-2000:])
        return 1
    print("\n".join(compare_lines(parse_engine_test(proc.stdout), shifts, args.data, args.workers)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
