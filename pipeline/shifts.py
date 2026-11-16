"""Build the 28 campaign shifts and write game/game_data.json (CONTRACT section 4).

CLI: ``python -m pipeline.shifts --week data/work/week.csv [--out game/game_data.json]``.
Units: map coordinates are integers in map units (``unit_m`` metres), times are game seconds from
the shift start, money is EUR, speeds km/h.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple
from zoneinfo import ZoneInfo

from pipeline import geo, places

TZ = ZoneInfo("Europe/Lisbon")
SHIFT_S = 7200
UNIT_M = 5
UNIT_M_FALLBACK = 10
MAX_BYTES = 5_000_000
GENERATED = "2014-05-12/2014-05-19 UCI339"
MONDAY = (2014, 5, 12)
MIN_ORDERS_WARN = 150
GPS_STEP_S = 15
SPEED_MIN, SPEED_MAX = 12.0, 60.0
SPEED_MIN_TRIPS = 30
DETOUR_MIN, DETOUR_MAX, DETOUR_DEFAULT = 1.1, 1.8, 1.3
DETOUR_MIN_STRAIGHT_KM = 0.5
CALL_INDEX = {"A": 0, "B": 1, "C": 2}

DAY_IDS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_NAMES = ("понеділок", "вівторок", "середа", "четвер", "п'ятниця", "субота", "неділя")
DAY_DATE_FMT = "{name}, {n} травня 2014"
SLOTS = (("am", 8), ("lunch", 12), ("pm", 17), ("night", 22))
NIGHT_SAT_DAY = "з суботи на неділю, 18 травня 2014"
NAMES = (
    ("Понеділковий ранок", "Обід у Байші", "Додому після роботи", "Тиха ніч понеділка"),
    ("Ранковий пік", "Обід біля ринку", "Вечір над Дору", "Ніч у вівторок"),
    ("Ранок у середу", "Обід на швидку руку", "Вечір у центрі", "Нічна середа"),
    ("Четвер: до університету", "Обід у четвер", "Четвер після роботи", "Переддень п'ятниці"),
    ("Ранок перед вихідними", "Обід у п'ятницю", "Вечір п'ятниці", "П'ятнична ніч"),
    ("Суботній ранок", "Субота на Рібейрі", "Суботній вечір", "Ніч на неділю"),
    ("Недільний ранок", "Недільний обід", "Недільний вечір", "Остання ніч тижня"),
)


class Trip(NamedTuple):
    """One valid trip of the week (lon/lat points, km from the raw polyline)."""

    trip_id: str
    taxi: int
    ts: int
    call: int
    stand: int
    pts: list[list[float]]
    km: float
    hour: int


class ShiftDef(NamedTuple):
    """Campaign slot: identity, display strings and the unix start (Europe/Lisbon)."""

    index: int
    id: str
    name: str
    day: str
    slot: str
    start_local: str
    start_hour: int
    start: int


def local_hour(ts: int) -> int:
    """Return the Europe/Lisbon hour of day (0..23) of a unix timestamp."""
    return datetime.fromtimestamp(ts, tz=TZ).hour


def shift_defs() -> list[ShiftDef]:
    """Return the 28 shift definitions in campaign order (mon-am ... sun-night)."""
    defs: list[ShiftDef] = []
    for d, day_id in enumerate(DAY_IDS):
        for s, (slot, hour) in enumerate(SLOTS):
            day_n = 12 + d
            sat_night = day_id == "sat" and slot == "night"
            if sat_night:
                local = datetime(*MONDAY[:2], 18, 0, 0, tzinfo=TZ)
                day = NIGHT_SAT_DAY
            else:
                local = datetime(*MONDAY[:2], day_n, hour, 0, tzinfo=TZ)
                day = DAY_DATE_FMT.format(name=DAY_NAMES[d], n=day_n)
            defs.append(
                ShiftDef(
                    index=len(defs),
                    id=f"{day_id}-{slot}",
                    name=NAMES[d][s],
                    day=day,
                    slot=slot,
                    start_local=local.strftime("%Y-%m-%d %H:%M"),
                    start_hour=local.hour,
                    start=int(local.timestamp()),
                )
            )
    return defs


def parse_row(row: dict[str, str]) -> Trip | None:
    """Return a Trip for a CSV row that passes the game filters, else None."""
    if row["MISSING_DATA"].strip().lower() == "true":
        return None
    try:
        pts = json.loads(row["POLYLINE"])
    except ValueError:
        return None
    if not isinstance(pts, list) or not geo.trip_ok(pts):
        return None
    ts = int(row["TIMESTAMP"])
    stand_raw = row["ORIGIN_STAND"].strip()
    return Trip(
        trip_id=row["TRIP_ID"],
        taxi=int(row["TAXI_ID"]),
        ts=ts,
        call=CALL_INDEX[row["CALL_TYPE"].strip()],
        stand=int(stand_raw) if stand_raw.isdigit() else 0,
        pts=pts,
        km=geo.path_km(pts),
        hour=local_hour(ts),
    )


def load_trips(week: Path) -> list[Trip]:
    """Read week.csv and return all trips passing trip_ok, in file order."""
    csv.field_size_limit(sys.maxsize)
    trips: list[Trip] = []
    with week.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            trip = parse_row(row)
            if trip is not None:
                trips.append(trip)
    return trips


def median(values: Sequence[float]) -> float:
    """Return the median (mean of the two middle values for an even count); 0.0 if empty."""
    return float(statistics.median(values)) if values else 0.0


def speed_by_hour(trips: Iterable[Trip]) -> list[float]:
    """Return km/h per local hour 0..23: median of km/(d/3600), clamped 12..60, 1 decimal.

    An hour with fewer than 30 trips uses the overall median.
    """
    by_hour: dict[int, list[float]] = defaultdict(list)
    for t in trips:
        dur = GPS_STEP_S * (len(t.pts) - 1)
        by_hour[t.hour].append(round(t.km, 2) / (dur / 3600.0))
    overall = median([v for vals in by_hour.values() for v in vals])
    out = []
    for h in range(24):
        vals = by_hour.get(h, [])
        v = median(vals) if len(vals) >= SPEED_MIN_TRIPS else overall
        out.append(round(min(SPEED_MAX, max(SPEED_MIN, v)), 1))
    return out


def to_units(x_m: float, y_m: float, unit_m: int) -> tuple[int, int]:
    """Convert map metres to integer map units."""
    return round(x_m / unit_m), round(y_m / unit_m)


def make_order(trip: Trip, start: int, taxi_idx: int, unit_m: int) -> list[Any]:
    """Build the compact order array of CONTRACT section 4 (pts are deltas in units)."""
    cells = [to_units(*geo.proj(p[0], p[1]), unit_m) for p in trip.pts]
    deltas: list[int] = []
    for (xa, ya), (xb, yb) in zip(cells, cells[1:], strict=False):
        deltas += [xb - xa, yb - ya]
    km = round(trip.km, 2)
    return [
        trip.ts - start,
        cells[0][0],
        cells[0][1],
        cells[-1][0],
        cells[-1][1],
        deltas,
        GPS_STEP_S * (len(cells) - 1),
        km,
        geo.fare(km, geo.night_hour(trip.hour)),
        trip.call,
        trip.stand,
        taxi_idx,
    ]


def rank_drivers(trips: Sequence[Trip]) -> tuple[list[int], list[float]]:
    """Return (taxi ids, totals in EUR) sorted by total descending, ties by TAXI_ID."""
    cents: dict[int, int] = defaultdict(int)
    for t in trips:
        km = round(t.km, 2)
        cents[t.taxi] += round(geo.fare(km, geo.night_hour(t.hour)) * 100)
    order = sorted(cents, key=lambda k: (-cents[k], k))
    return order, [cents[k] / 100 for k in order]


def detour_of(trips: Sequence[Trip]) -> float:
    """Median road/straight ratio over trips with straight distance >= 0.5 km, clamped."""
    ratios = []
    for t in trips:
        straight = geo.haversine(t.pts[0][0], t.pts[0][1], t.pts[-1][0], t.pts[-1][1])
        if straight >= DETOUR_MIN_STRAIGHT_KM:
            ratios.append(t.km / straight)
    value = median(ratios) if ratios else DETOUR_DEFAULT
    return round(min(DETOUR_MAX, max(DETOUR_MIN, value)), 3)


def top10_of(ranking: Sequence[float]) -> float:
    """Return the ranking value at the 10 % mark (0.0 for an empty ranking)."""
    if not ranking:
        return 0.0
    return ranking[max(0, math.ceil(0.10 * len(ranking)) - 1)]


def pickup_spread(trips: Sequence[Trip]) -> float:
    """Return the mean distance (m) of pickups to their centroid; 0.0 if no trips."""
    if not trips:
        return 0.0
    pts = [geo.proj(t.pts[0][0], t.pts[0][1]) for t in trips]
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    return sum(math.hypot(p[0] - cx, p[1] - cy) for p in pts) / len(pts)


def build_shift(sd: ShiftDef, trips: Sequence[Trip], speeds: list[float], unit_m: int) -> dict:
    """Build one shift object (without difficulty) from the trips inside its window."""
    inside = sorted(
        (t for t in trips if sd.start <= t.ts < sd.start + SHIFT_S),
        key=lambda t: (t.ts, t.trip_id),
    )
    taxis, ranking = rank_drivers(inside)
    idx = {taxi: i for i, taxi in enumerate(taxis)}
    orders = [make_order(t, sd.start, idx[t.taxi], unit_m) for t in inside]
    return {
        "id": sd.id,
        "name": sd.name,
        "day": sd.day,
        "slot": sd.slot,
        "start_local": sd.start_local,
        "start_hour": sd.start_hour,
        "difficulty": 3,
        "nDrivers": len(taxis),
        "orders": orders,
        "taxis": taxis,
        "ranking": ranking,
        "ghost": {
            "taxi": 0,
            "total": ranking[0] if ranking else 0.0,
            "orders": [i for i, o in enumerate(orders) if o[11] == 0],
        },
        "median": median(ranking),
        "top10": top10_of(ranking),
        "speed_by_hour": speeds,
        "detour": detour_of(inside),
        "hot": [],
        "surges": [],
        "_trips": inside,
    }


def percentile_ranks(values: Sequence[float]) -> list[float]:
    """Return the percentile rank 0..1 of each value (ties share the average rank)."""
    n = len(values)
    if n < 2:
        return [0.5] * n
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 / (n - 1)
        i = j + 1
    return ranks


def assign_difficulty(shifts: list[dict]) -> None:
    """Set ``difficulty`` 1..5: quintile of the mean percentile of three hardness features."""
    ratio, per_driver, spread = [], [], []
    for s in shifts:
        med = s["median"]
        ratio.append(s["ghost"]["total"] / med if med else 1.0)
        per_driver.append(-len(s["orders"]) / s["nDrivers"] if s["nDrivers"] else 0.0)
        spread.append(pickup_spread(s["_trips"]))
    cols = [percentile_ranks(c) for c in (ratio, per_driver, spread)]
    score = [sum(c[i] for c in cols) / 3 for i in range(len(shifts))]
    order = sorted(range(len(shifts)), key=lambda i: (score[i], i))
    for rank, i in enumerate(order):
        shifts[i]["difficulty"] = 1 + rank * 5 // len(shifts)


def build_data(trips: Sequence[Trip], unit_m: int = UNIT_M) -> dict:
    """Build the whole game_data structure from valid trips."""
    speeds = speed_by_hour(trips)
    shifts = [build_shift(sd, trips, speeds, unit_m) for sd in shift_defs()]
    assign_difficulty(shifts)
    for s in shifts:
        s["hot"], s["surges"] = places.hot_and_surges(s["orders"], unit_m)
        del s["_trips"]
    return {
        "version": 1,
        "unit_m": unit_m,
        "bounds": [0, 0, geo.MAP_W_M // unit_m, geo.MAP_H_M // unit_m],
        "generated": GENERATED,
        "shifts": shifts,
    }


def dump_json(data: dict) -> str:
    """Serialise deterministically: sorted keys, compact, one line, UTF-8 text."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build_text(trips: Sequence[Trip]) -> str:
    """Return the JSON text; falls back to 10 m units if the file would exceed 5 MB."""
    text = dump_json(build_data(trips, UNIT_M))
    if len(text.encode("utf-8")) > MAX_BYTES:
        text = dump_json(build_data(trips, UNIT_M_FALLBACK))
    return text


def table_rows(data: dict) -> list[str]:
    """Return printable table lines: id, name, orders, drivers, ghost, median, top10, difficulty."""
    head = f"{'id':<11}{'name':<26}{'orders':>7}{'drivers':>8}{'ghost':>9}{'median':>8}"
    lines = [head + f"{'top10':>8}{'diff':>5}"]
    for s in data["shifts"]:
        lines.append(
            f"{s['id']:<11}{s['name']:<26}{len(s['orders']):>7}{s['nDrivers']:>8}"
            f"{s['ghost']['total']:>9.2f}{s['median']:>8.2f}{s['top10']:>8.2f}"
            f"{s['difficulty']:>5}"
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: week.csv to game_data.json; prints the shift table."""
    ap = argparse.ArgumentParser(description="Build game/game_data.json from week.csv")
    ap.add_argument("--week", type=Path, required=True, help="path to data/work/week.csv")
    ap.add_argument("--out", type=Path, default=Path("game/game_data.json"))
    args = ap.parse_args(argv)
    trips = load_trips(args.week)
    text = build_text(trips)
    data = json.loads(text)
    for s in data["shifts"]:
        if len(s["orders"]) < MIN_ORDERS_WARN:
            print(f"warning: {s['id']} has only {len(s['orders'])} orders", file=sys.stderr)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print("\n".join(table_rows(data)))
    print(f"{len(trips)} valid trips, {len(text.encode('utf-8'))} bytes -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
