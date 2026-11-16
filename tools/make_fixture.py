"""Build the synthetic test data ``game/fixture/mini.json`` in the CONTRACT section 4 schema.

The map, fare and ranking rules come from ``pipeline/geo.py`` and ``pipeline/shifts.py``; every
trip passes ``geo.trip_ok`` lengths (at least 4 points and 0.8 km), like a real order.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))  # tools/ is no package: find ``pipeline`` as a script

from pipeline import geo, shifts  # noqa: E402

SEED = 7  # random seed of the fixture
UNIT_M = 5  # metres per map unit
MAP_W_M = geo.MAP_W_M
MAP_H_M = geo.MAP_H_M
HOME_X_M, HOME_Y_M = geo.HOME  # player start, metres
CENTRAL_M = 5000.0  # side of the central square the trips stay in, metres
START_SPREAD = 0.8  # trips start within this share of the half-side from the centre
TURN_IN = 0.6  # a start farther out than this share of the half-side heads to the centre
TURN_IN_JITTER = 0.6  # random spread of that heading, radians
WANDER = 0.25  # random heading change per step, radians
N_TAXIS = 25  # drivers in the fixture
N_TRIPS = 120  # trips in the fixture
MIN_PTS = geo.MIN_POINTS  # fewest GPS points of a trip
MIN_PATH_M = geo.MIN_PATH_KM * geo.M_PER_KM + 50  # a trip is at least this long, metres
MAX_PTS = 12  # most GPS points of a trip
STEP_MIN_M = 150.0  # shortest GPS step, metres
STEP_MAX_M = 330.0  # longest GPS step, metres
STAND_MAX = 20  # stand numbers are 1..20
GPS_STEP_S = geo.GPS_STEP_S
SHIFT_S = geo.SHIFT_S
M_PER_KM = geo.M_PER_KM
KIB = 1024  # bytes in a KiB, for the size line
DETOUR = 1.25  # road/straight ratio of the fixture shift
TAXI_ID_BASE = 20000000  # TAXI_ID of the first driver
TAXI_ID_STEP = 101  # distance between two TAXI_IDs
SURGE_T0 = 150  # surge start, game seconds
SURGE_T1 = 1500  # surge end, game seconds
SURGE_R = 120  # surge radius, map units
SURGE_N = 14  # pickups counted in the surge
SURGE_DX_M, SURGE_DY_M = 200, -100  # surge centre offset from the start, metres
OUT_DEFAULT = Path("game/fixture/mini.json")
HOT_SPOTS = (
    ("Aliados", 0.0, 0.0, 0.45),
    ("Bolhão", 350.0, -250.0, 0.35),
    ("Trindade", -300.0, -300.0, 0.2),
)
SPEED_BY_HOUR = [
    34.0,
    36.0,
    38.0,
    38.0,
    38.0,
    36.0,
    32.0,
    28.0,
    24.0,
    26.0,
    28.0,
    28.0,
    27.0,
    27.0,
    28.0,
    28.0,
    26.0,
    24.0,
    24.0,
    27.0,
    30.0,
    32.0,
    33.0,
    34.0,
]


def fare(km: float) -> float:
    """Daytime fare in EUR (``geo.fare``, CONTRACT section 3).

    Args:
        km: Trip length in km.

    Returns:
        Fare in EUR.
    """
    return geo.fare(km, night=False)


def make_trip(rng: random.Random, t: int) -> list[Any]:
    """Make one synthetic trip: a straight-ish polyline inside the central square.

    Args:
        rng: Seeded random generator.
        t: Pickup time in game seconds.

    Returns:
        Order array ``[t, x0, y0, x1, y1, pts, d, km, fare, c, stand, taxi]`` (taxi = 0 for now).
    """
    half = CENTRAL_M / 2
    n = rng.randint(MIN_PTS, MAX_PTS)  # at least this many points; more if the path is short
    x = rng.uniform(HOME_X_M - half * START_SPREAD, HOME_X_M + half * START_SPREAD)
    y = rng.uniform(HOME_Y_M - half * START_SPREAD, HOME_Y_M + half * START_SPREAD)
    ang = rng.uniform(0, 2 * math.pi)
    # head towards the centre if the heading would leave the square
    if math.hypot(x - HOME_X_M, y - HOME_Y_M) > half * TURN_IN:
        ang = math.atan2(HOME_Y_M - y, HOME_X_M - x) + rng.uniform(-TURN_IN_JITTER, TURN_IN_JITTER)
    ux, uy = round(x / UNIT_M), round(y / UNIT_M)
    px, py = ux, uy
    deltas: list[int] = []
    metres = 0.0
    while len(deltas) // 2 < MAX_PTS - 1 and (len(deltas) // 2 < n - 1 or metres < MIN_PATH_M):
        ang += rng.uniform(-WANDER, WANDER)
        step = rng.uniform(STEP_MIN_M, STEP_MAX_M) / UNIT_M
        dx, dy = round(math.cos(ang) * step), round(math.sin(ang) * step)
        deltas += [dx, dy]
        metres += math.hypot(dx, dy) * UNIT_M
        px, py = px + dx, py + dy
    km = round(metres / M_PER_KM, 2)
    c = rng.choice((0, 1, 2))
    stand = rng.randint(1, STAND_MAX) if c == 1 else 0
    return [t, ux, uy, px, py, deltas, GPS_STEP_S * (len(deltas) // 2), km, fare(km), c, stand, 0]


def schedule(rng: random.Random, count: int) -> list[int]:
    """Pick non-overlapping pickup times for one driver.

    Args:
        rng: Seeded random generator.
        count: Number of trips.

    Returns:
        Ascending pickup times in game seconds, each trip ending inside its own segment.
    """
    seg = SHIFT_S // count
    longest = GPS_STEP_S * (MAX_PTS - 1)
    return [i * seg + rng.randint(0, seg - longest - 1) for i in range(count)]


def build_orders(rng: random.Random) -> tuple[list[list[Any]], list[int]]:
    """Make all orders with a driver id each, sorted by time.

    Args:
        rng: Seeded random generator.

    Returns:
        ``(orders, taxi_ids)``: orders whose last field holds a driver slot 0..24, and the
        TAXI_ID of each slot.
    """
    taxi_ids = [TAXI_ID_BASE + TAXI_ID_STEP * i for i in range(N_TAXIS)]
    counts = [N_TRIPS // N_TAXIS + (1 if i < N_TRIPS % N_TAXIS else 0) for i in range(N_TAXIS)]
    orders: list[list[Any]] = []
    for slot, cnt in enumerate(counts):
        for t in schedule(rng, cnt):
            o = make_trip(rng, t)
            o[11] = slot
            orders.append(o)
    orders.sort(key=lambda o: (o[0], o[11]))
    return orders, taxi_ids


def rank_drivers(orders: list[list[Any]], taxi_ids: list[int]) -> tuple[list[int], list[float]]:
    """Rank drivers by total fare and remap the order driver field to the rank position.

    Args:
        orders: Orders; field 11 is the driver slot on input and the rank index on output.
        taxi_ids: TAXI_ID per slot.

    Returns:
        ``(taxis, ranking)`` sorted by total descending, ties by TAXI_ID (totals in EUR).
    """
    cents = [0] * len(taxi_ids)
    for o in orders:
        cents[o[11]] += round(o[8] * geo.CENTS)
    order = sorted(range(len(taxi_ids)), key=lambda s: (-cents[s], taxi_ids[s]))
    pos = {slot: i for i, slot in enumerate(order)}
    for o in orders:
        o[11] = pos[o[11]]
    return [taxi_ids[s] for s in order], [cents[s] / geo.CENTS for s in order]


def hot_spots() -> list[dict[str, Any]]:
    """Place the three fixture hotspots around the player start.

    Returns:
        Hotspot dicts ``{x, y, w, name}`` with x, y in map units and ``w`` a share.
    """
    hx, hy = HOME_X_M / UNIT_M, HOME_Y_M / UNIT_M
    return [
        {"x": round(hx + dx / UNIT_M), "y": round(hy + dy / UNIT_M), "w": w, "name": nm}
        for nm, dx, dy, w in HOT_SPOTS
    ]


def fixture_surge() -> dict[str, Any]:
    """Describe the one fixture demand surge.

    Returns:
        Surge dict ``{x, y, r, t0, t1, n, name}``: x, y, r in map units, times in game seconds.
    """
    hx, hy = HOME_X_M / UNIT_M, HOME_Y_M / UNIT_M
    return {
        "x": round(hx + SURGE_DX_M / UNIT_M),
        "y": round(hy + SURGE_DY_M / UNIT_M),
        "r": SURGE_R,
        "t0": SURGE_T0,
        "t1": SURGE_T1,
        "n": SURGE_N,
        "name": "Bolhão",
    }


def build_shift() -> dict[str, Any]:
    """Build the one fixture shift ``fix-am`` (deterministic, seed 7).

    Returns:
        The shift dict of CONTRACT section 4; times in game seconds, money in EUR.
    """
    rng = random.Random(SEED)
    orders, taxi_ids = build_orders(rng)
    taxis, ranking = rank_drivers(orders, taxi_ids)
    n = len(ranking)
    return {
        "id": "fix-am",
        "name": "Тестова зміна",
        "day": "понеділок, 12 травня 2014",
        "slot": "am",
        "start_local": "2014-05-12 08:00",
        "start_hour": 8,
        "difficulty": 3,
        "nDrivers": n,
        "orders": orders,
        "taxis": taxis,
        "ranking": ranking,
        "ghost": shifts.ghost_of(orders, ranking),
        "median": shifts.median(ranking),
        "top10": shifts.top10_of(ranking),
        "speed_by_hour": SPEED_BY_HOUR,
        "detour": DETOUR,
        "hot": hot_spots(),
        "surges": [fixture_surge()],
    }


def build_fixture() -> dict[str, Any]:
    """Build the whole fixture (deterministic, seed 7).

    Returns:
        The game-data dict of CONTRACT section 4 with one shift ``fix-am``.
    """
    return {
        "version": 1,
        "unit_m": UNIT_M,
        "bounds": [0, 0, MAP_W_M // UNIT_M, MAP_H_M // UNIT_M],
        "generated": "synthetic fixture (seed 7)",
        "shifts": [build_shift()],
    }


def main(argv: list[str] | None = None) -> int:
    """Command line entry point.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        0 on success.
    """
    ap = argparse.ArgumentParser(description="Write the synthetic fixture")
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = ap.parse_args(argv)
    text = json.dumps(build_fixture(), separators=(",", ":"), ensure_ascii=False, sort_keys=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"wrote {args.out} ({len(text) // KIB} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
