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
SHIFT_S = 7200  # shift length, game seconds
UNIT_M = 5  # metres per map unit
UNIT_M_FALLBACK = 10  # metres per map unit if the 5 m file is too big
MAX_BYTES = 5_000_000  # size budget of game_data.json, bytes
GENERATED = "2014-05-12/2014-05-19 UCI339"  # the ``generated`` stamp (no timestamps: determinism)
MONDAY = (2014, 5, 12)  # year, month, day of the first campaign day
SUNDAY_DAY = 18  # day of May on which Saturday's night shift starts (Sun 00:00)
MIN_ORDERS_WARN = 150  # a shift with fewer orders prints a warning
GPS_STEP_S = 15  # seconds between two GPS points of a trip
HOURS_PER_DAY = 24  # local hours in a day
S_PER_HOUR = 3600.0  # seconds in an hour
SPEED_MIN, SPEED_MAX = 12.0, 60.0  # clamp of the median speed per hour, km/h
SPEED_MIN_TRIPS = 30  # an hour with fewer trips uses the overall median
DETOUR_MIN, DETOUR_MAX, DETOUR_DEFAULT = 1.1, 1.8, 1.3  # clamp and fallback of road/straight
DETOUR_MIN_STRAIGHT_KM = 0.5  # shorter trips are left out of the detour median, km
TOP_SHARE = 0.10  # the ``top10`` mark is this share of the ranking
DIFFICULTY_LEVELS = 5  # difficulty is 1..5 (quintiles)
DIFFICULTY_FEATURES = 3  # hardness features averaged into the difficulty score
CALL_INDEX = {"A": 0, "B": 1, "C": 2}  # ORIGIN call type letter to its index

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
    """Convert a timestamp to the local hour.

    Args:
        ts: Unix time, seconds.

    Returns:
        Europe/Lisbon hour of day, 0..23.
    """
    return datetime.fromtimestamp(ts, tz=TZ).hour


def shift_defs() -> list[ShiftDef]:
    """Build the shift definitions of the campaign.

    Returns:
        28 definitions in campaign order (mon-am ... sun-night); ``start`` in unix seconds.
    """
    defs: list[ShiftDef] = []
    for d, day_id in enumerate(DAY_IDS):
        for s, (slot, hour) in enumerate(SLOTS):
            day_n = MONDAY[2] + d
            sat_night = day_id == "sat" and slot == "night"
            if sat_night:
                local = datetime(*MONDAY[:2], SUNDAY_DAY, 0, 0, tzinfo=TZ)
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
    """Parse one row of week.csv.

    Args:
        row: CSV row as a dict (TRIP_ID, TAXI_ID, TIMESTAMP, CALL_TYPE, ORIGIN_STAND, POLYLINE,
            MISSING_DATA).

    Returns:
        A :class:`Trip` (km along the polyline, timestamp in unix seconds), or None if the row
        is flagged missing, has no valid polyline or fails :func:`geo.trip_ok`.
    """
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
    """Read week.csv.

    Args:
        week: Path of the CSV file.

    Returns:
        All trips passing the game filters, in file order.
    """
    csv.field_size_limit(sys.maxsize)
    trips: list[Trip] = []
    with week.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            trip = parse_row(row)
            if trip is not None:
                trips.append(trip)
    return trips


def median(values: Sequence[float]) -> float:
    """Compute a median.

    Args:
        values: Numbers in any unit.

    Returns:
        The median (mean of the two middle values for an even count), in the unit of the inputs;
        0.0 if empty.
    """
    return float(statistics.median(values)) if values else 0.0


def speed_by_hour(trips: Iterable[Trip]) -> list[float]:
    """Estimate the driving speed of each local hour.

    Per trip the speed is km / (duration / 3600); an hour with fewer than 30 trips uses the
    overall median.

    Args:
        trips: Valid trips (km, 15 s GPS step).

    Returns:
        24 values in km/h, one per local hour 0..23: the median, clamped to 12..60, 1 decimal.
    """
    by_hour: dict[int, list[float]] = defaultdict(list)
    for t in trips:
        dur = GPS_STEP_S * (len(t.pts) - 1)
        by_hour[t.hour].append(round(t.km, 2) / (dur / S_PER_HOUR))
    overall = median([v for vals in by_hour.values() for v in vals])
    out = []
    for h in range(HOURS_PER_DAY):
        vals = by_hour.get(h, [])
        v = median(vals) if len(vals) >= SPEED_MIN_TRIPS else overall
        out.append(round(min(SPEED_MAX, max(SPEED_MIN, v)), 1))
    return out


def to_units(x_m: float, y_m: float, unit_m: int) -> tuple[int, int]:
    """Convert map metres to integer map units.

    Args:
        x_m: Map x, metres.
        y_m: Map y, metres.
        unit_m: Metres per map unit.

    Returns:
        ``(x, y)`` rounded to whole map units.
    """
    return round(x_m / unit_m), round(y_m / unit_m)


def make_order(trip: Trip, start: int, taxi_idx: int, unit_m: int) -> list[Any]:
    """Build the compact order array of CONTRACT section 4.

    Args:
        trip: The trip.
        start: Shift start, unix seconds.
        taxi_idx: Rank index of the driver in the shift's ``taxis`` list.
        unit_m: Metres per map unit.

    Returns:
        ``[t, x0, y0, x1, y1, deltas, duration, km, fare, call, stand, taxi_idx]``: t and
        duration in game seconds, coordinates and the polyline ``deltas`` in map units, km in
        kilometres, fare in EUR.
    """
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
    """Rank the drivers of a shift by their total fares.

    Args:
        trips: Trips of the shift.

    Returns:
        ``(taxi ids, totals)`` sorted by total descending, ties by TAXI_ID; totals in EUR.
    """
    cents: dict[int, int] = defaultdict(int)
    for t in trips:
        km = round(t.km, 2)
        cents[t.taxi] += round(geo.fare(km, geo.night_hour(t.hour)) * geo.CENTS)
    order = sorted(cents, key=lambda k: (-cents[k], k))
    return order, [cents[k] / geo.CENTS for k in order]


def detour_of(trips: Sequence[Trip]) -> float:
    """Estimate how much longer roads are than straight lines.

    Args:
        trips: Trips of the shift.

    Returns:
        Median of path km / straight km over trips with straight distance >= 0.5 km, clamped to
        1.1..1.8 and rounded to 3 decimals; a dimensionless ratio.
    """
    ratios = []
    for t in trips:
        straight = geo.haversine(t.pts[0][0], t.pts[0][1], t.pts[-1][0], t.pts[-1][1])
        if straight >= DETOUR_MIN_STRAIGHT_KM:
            ratios.append(t.km / straight)
    value = median(ratios) if ratios else DETOUR_DEFAULT
    return round(min(DETOUR_MAX, max(DETOUR_MIN, value)), 3)


def top10_of(ranking: Sequence[float]) -> float:
    """Find the ranking value at the 10 % mark.

    Args:
        ranking: Driver totals in EUR, best first.

    Returns:
        Total in EUR of the driver at the top 10 % mark; 0.0 for an empty ranking.
    """
    if not ranking:
        return 0.0
    return ranking[max(0, math.ceil(TOP_SHARE * len(ranking)) - 1)]


def pickup_spread(trips: Sequence[Trip]) -> float:
    """Measure how spread out the pickups are.

    Args:
        trips: Trips of the shift.

    Returns:
        Mean distance of the pickups to their centroid, in metres; 0.0 if no trips.
    """
    if not trips:
        return 0.0
    pts = [geo.proj(t.pts[0][0], t.pts[0][1]) for t in trips]
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    return sum(math.hypot(p[0] - cx, p[1] - cy) for p in pts) / len(pts)


def ghost_of(orders: Sequence[Sequence[Any]], ranking: Sequence[float]) -> dict[str, Any]:
    """Describe the ghost, the best driver of the shift.

    Args:
        orders: Compact orders of the shift (field 11 is the driver rank index).
        ranking: Driver totals in EUR, best first.

    Returns:
        ``{taxi, total, orders}``: taxi index 0, its total in EUR (0.0 if nobody drove) and the
        indexes of its orders.
    """
    return {
        "taxi": 0,
        "total": ranking[0] if ranking else 0.0,
        "orders": [i for i, o in enumerate(orders) if o[11] == 0],
    }


def build_shift(sd: ShiftDef, trips: Sequence[Trip], speeds: list[float], unit_m: int) -> dict:
    """Build one shift object (difficulty is a placeholder) from the trips inside its window.

    Args:
        sd: Shift definition.
        trips: All valid trips of the week.
        speeds: Speed per local hour, km/h.
        unit_m: Metres per map unit.

    Returns:
        The shift dict of CONTRACT section 4 plus the private key ``_trips`` (the shift's trips).
    """
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
        "ghost": ghost_of(orders, ranking),
        "median": median(ranking),
        "top10": top10_of(ranking),
        "speed_by_hour": speeds,
        "detour": detour_of(inside),
        "hot": [],
        "surges": [],
        "_trips": inside,
    }


def percentile_ranks(values: Sequence[float]) -> list[float]:
    """Compute percentile ranks.

    Args:
        values: Numbers in any unit.

    Returns:
        The rank 0..1 of each value (ties share the average rank); 0.5 each if fewer than two.
    """
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
    """Set ``difficulty`` 1..5 in place: quintile of the mean percentile of three hardness features.

    Args:
        shifts: Shift dicts from :func:`build_shift` (they carry ``_trips``).
    """
    ratio, per_driver, spread = [], [], []
    for s in shifts:
        med = s["median"]
        ratio.append(s["ghost"]["total"] / med if med else 1.0)
        per_driver.append(-len(s["orders"]) / s["nDrivers"] if s["nDrivers"] else 0.0)
        spread.append(pickup_spread(s["_trips"]))
    cols = [percentile_ranks(c) for c in (ratio, per_driver, spread)]
    score = [sum(c[i] for c in cols) / DIFFICULTY_FEATURES for i in range(len(shifts))]
    order = sorted(range(len(shifts)), key=lambda i: (score[i], i))
    for rank, i in enumerate(order):
        shifts[i]["difficulty"] = 1 + rank * DIFFICULTY_LEVELS // len(shifts)


def build_data(trips: Sequence[Trip], unit_m: int = UNIT_M) -> dict:
    """Build the whole game_data structure.

    Args:
        trips: All valid trips of the week.
        unit_m: Metres per map unit.

    Returns:
        The document of CONTRACT section 4 (28 shifts).
    """
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
    """Serialise deterministically.

    Args:
        data: JSON-compatible structure.

    Returns:
        Compact one-line text with sorted keys and non-ASCII characters kept.
    """
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build_text(trips: Sequence[Trip]) -> str:
    """Build the JSON text of game_data.

    Args:
        trips: All valid trips of the week.

    Returns:
        The text; rebuilt with 10 m units if the UTF-8 size would exceed 5 MB (5 000 000 bytes).
    """
    text = dump_json(build_data(trips, UNIT_M))
    if len(text.encode("utf-8")) > MAX_BYTES:
        text = dump_json(build_data(trips, UNIT_M_FALLBACK))
    return text


def table_rows(data: dict) -> list[str]:
    """Format the per-shift summary table.

    Args:
        data: The game_data structure.

    Returns:
        Header plus one line per shift: id, name, orders, drivers, ghost, median, top10 (EUR),
        difficulty.
    """
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
    """Run the week-to-shifts step: write game_data.json and print the shift table.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        0 on success.
    """
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
