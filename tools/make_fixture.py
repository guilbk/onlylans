"""Build the synthetic test data ``game/fixture/mini.json`` in the CONTRACT section 4 schema."""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from typing import Any

SEED = 7
UNIT_M = 5
MAP_W_M = 15000
MAP_H_M = 19000
HOME_X_M = 9110.0
HOME_Y_M = 12443.0
CENTRAL_M = 5000.0
N_TAXIS = 25
N_TRIPS = 120
MIN_PTS = 3
MAX_PTS = 12
STEP_MIN_M = 150.0
STEP_MAX_M = 330.0
GPS_STEP_S = 15
SHIFT_S = 7200
SURGE_T0 = 150
FARE_BASE = 3.25
FARE_PER_KM = 0.5
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
    """Daytime fare in EUR, rounded half-up to cents (same formula as CONTRACT section 3).

    Args:
        km: Trip length in km.

    Returns:
        Fare in EUR.
    """
    return math.floor((FARE_BASE + FARE_PER_KM * km) * 100 + 0.5) / 100


def make_trip(rng: random.Random, t: int) -> list[Any]:
    """Make one synthetic trip: a straight-ish polyline inside the central square.

    Args:
        rng: Seeded random generator.
        t: Pickup time in game seconds.

    Returns:
        Order array ``[t, x0, y0, x1, y1, pts, d, km, fare, c, stand, taxi]`` (taxi = 0 for now).
    """
    half = CENTRAL_M / 2
    n = rng.randint(MIN_PTS, MAX_PTS)
    x = rng.uniform(HOME_X_M - half * 0.8, HOME_X_M + half * 0.8)
    y = rng.uniform(HOME_Y_M - half * 0.8, HOME_Y_M + half * 0.8)
    ang = rng.uniform(0, 2 * math.pi)
    # head towards the centre if the heading would leave the square
    if math.hypot(x - HOME_X_M, y - HOME_Y_M) > half * 0.6:
        ang = math.atan2(HOME_Y_M - y, HOME_X_M - x) + rng.uniform(-0.6, 0.6)
    ux, uy = round(x / UNIT_M), round(y / UNIT_M)
    px, py = ux, uy
    deltas: list[int] = []
    metres = 0.0
    for _ in range(n - 1):
        ang += rng.uniform(-0.25, 0.25)
        step = rng.uniform(STEP_MIN_M, STEP_MAX_M) / UNIT_M
        dx, dy = round(math.cos(ang) * step), round(math.sin(ang) * step)
        deltas += [dx, dy]
        metres += math.hypot(dx, dy) * UNIT_M
        px, py = px + dx, py + dy
    km = round(metres / 1000, 2)
    c = rng.choice((0, 1, 2))
    stand = rng.randint(1, 20) if c == 1 else 0
    return [t, ux, uy, px, py, deltas, GPS_STEP_S * (n - 1), km, fare(km), c, stand, 0]


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
    taxi_ids = [20000000 + 101 * i for i in range(N_TAXIS)]
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
        ``(taxis, ranking)`` sorted by total descending, ties by TAXI_ID.
    """
    totals = [0.0] * len(taxi_ids)
    for o in orders:
        totals[o[11]] += o[8]
    order = sorted(range(len(taxi_ids)), key=lambda s: (-round(totals[s], 2), taxi_ids[s]))
    pos = {slot: i for i, slot in enumerate(order)}
    for o in orders:
        o[11] = pos[o[11]]
    return [taxi_ids[s] for s in order], [round(totals[s], 2) for s in order]


def median(values: list[float]) -> float:
    """Median of a sorted list (mean of the two middle values if even).

    Args:
        values: Sorted values.

    Returns:
        The median.
    """
    n = len(values)
    return values[n // 2] if n % 2 else round((values[n // 2 - 1] + values[n // 2]) / 2, 2)


def build_fixture() -> dict[str, Any]:
    """Build the whole fixture (deterministic, seed 7).

    Returns:
        The game-data dict of CONTRACT section 4 with one shift ``fix-am``.
    """
    rng = random.Random(SEED)
    orders, taxi_ids = build_orders(rng)
    taxis, ranking = rank_drivers(orders, taxi_ids)
    n = len(ranking)
    hx, hy = HOME_X_M / UNIT_M, HOME_Y_M / UNIT_M
    shift = {
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
        "ghost": {
            "taxi": 0,
            "total": ranking[0],
            "orders": [i for i, o in enumerate(orders) if o[11] == 0],
        },
        "median": median(ranking),
        "top10": ranking[max(0, math.ceil(0.10 * n) - 1)],
        "speed_by_hour": SPEED_BY_HOUR,
        "detour": 1.25,
        "hot": [
            {"x": round(hx + dx / UNIT_M), "y": round(hy + dy / UNIT_M), "w": w, "name": nm}
            for nm, dx, dy, w in HOT_SPOTS
        ],
        "surges": [
            {
                "x": round(hx + 200 / UNIT_M),
                "y": round(hy - 100 / UNIT_M),
                "r": 120,
                "t0": SURGE_T0,
                "t1": 1500,
                "n": 14,
                "name": "Bolhão",
            }
        ],
    }
    return {
        "version": 1,
        "unit_m": UNIT_M,
        "bounds": [0, 0, MAP_W_M // UNIT_M, MAP_H_M // UNIT_M],
        "generated": "synthetic fixture (seed 7)",
        "shifts": [shift],
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
    print(f"wrote {args.out} ({len(text) // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
