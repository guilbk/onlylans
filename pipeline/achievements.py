"""Achievements («Досягнення») with thresholds computed from the real data (CONTRACT section 18).

Twelve badges. Python decides the numbers (night shifts, the length of a «long» trip, the
districts, the airport); JS (``63_achievements.js``) only counts the player's progress.

Run ``python -m pipeline.achievements`` to write ``game/achievements.json``.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

DATA_DEFAULT = Path("game/game_data.json")
OUT_DEFAULT = Path("game/achievements.json")

AIRPORT = (3232.0, 1323.0)  # Aeroporto in the map frame, metres (same point as pipeline.missions)
AIRPORT_R_M = 1500.0  # a trip touches the airport within this radius, metres
AIRPORT_MIN = 3  # at least this many airport trips for the badge
DISTRICT_R_M = 600.0  # a point belongs to a district within this radius, metres
LONG_PCT = 0.95  # a trip longer than this percentile of the week's trips
GHOST_SHIFTS = 5  # shifts to beat the ghost on
TOP10_SHIFTS = 3  # shifts to finish among the top 10 real drivers
PASSENGERS = 100  # passengers in total
COMBO_N = 5  # trips in a row
MONEY_STEP = 50  # the earnings goal is rounded to this many euros
MONEY_SHIFTS = 10  # the goal is this many typical (median) shifts
WEEKEND = ("sat", "sun")  # day prefixes of shift ids


def percentile(values: Sequence[float], q: float) -> float:
    """Return the ``q`` percentile (nearest rank, ``0 <= q <= 1``) of a non-empty sequence.

    Args:
        values: The numbers.
        q: Share in 0..1.

    Returns:
        The value at that rank.
    """
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))]


def districts(shifts: Sequence[dict[str, Any]], unit_m: float) -> list[dict[str, Any]]:
    """List every distinct hotspot of the week (by name, first seen position), sorted by name.

    Args:
        shifts: Shift objects of ``game_data.json``.
        unit_m: Metres per map unit.

    Returns:
        ``[{"name", "x", "y"}]`` with x, y in metres.
    """
    seen: dict[str, dict[str, Any]] = {}
    for sh in shifts:
        for h in sh.get("hot", []):
            seen.setdefault(
                h["name"],
                {"name": h["name"], "x": round(h["x"] * unit_m), "y": round(h["y"] * unit_m)},
            )
    return [seen[k] for k in sorted(seen)]


def airport_trips(shifts: Sequence[dict[str, Any]], unit_m: float) -> list[int]:
    """Count the trips per shift that start or end within ``AIRPORT_R_M`` of the airport.

    Args:
        shifts: Shift objects.
        unit_m: Metres per map unit.

    Returns:
        One count per shift.
    """
    ax, ay = AIRPORT
    return [
        sum(
            1
            for o in sh["orders"]
            if math.hypot(o[1] * unit_m - ax, o[2] * unit_m - ay) <= AIRPORT_R_M
            or math.hypot(o[3] * unit_m - ax, o[4] * unit_m - ay) <= AIRPORT_R_M
        )
        for sh in shifts
    ]


def build_achievements(data: dict[str, Any]) -> dict[str, Any]:
    """Compute the 12 badges from the game data.

    Args:
        data: Parsed ``game_data.json``.

    Returns:
        ``{"version": 1, "badges": [...]}``; each badge has ``id``, ``icon``, ``title``, ``desc``,
        ``n`` (goal) and the fields of its kind (``km``, ``x``/``y``/``r``, ``spots``, ``eur``).
    """
    unit_m = float(data["unit_m"])
    shifts = data["shifts"]
    night = sum(1 for s in shifts if s["slot"] == "night")
    days = len({s["id"].split("-")[0] for s in shifts})
    kms = [o[7] for s in shifts for o in s["orders"]]
    km95 = round(percentile(kms, LONG_PCT) * 2) / 2 if kms else 0.0
    per_shift = [c for c in airport_trips(shifts, unit_m) if c > 0]
    air_n = max(AIRPORT_MIN, round(statistics.median(per_shift))) if per_shift else AIRPORT_MIN
    spots = districts(shifts, unit_m)
    typical = statistics.median([s["median"] for s in shifts]) if shifts else 0.0
    money = max(MONEY_STEP, round(typical * MONEY_SHIFTS / MONEY_STEP) * MONEY_STEP)
    night_n = max(1, math.ceil(night / 2))
    km_text = f"{km95:g}".replace(".", ",")
    badges: list[dict[str, Any]] = [
        {
            "id": "night",
            "icon": "🌙",
            "title": "Нічна зміна",
            "n": night_n,
            "desc": f"Заверши нічні зміни: {night_n}",
        },
        {
            "id": "airport",
            "icon": "✈️",
            "title": "Аеропорт",
            "n": air_n,
            "x": round(AIRPORT[0]),
            "y": round(AIRPORT[1]),
            "r": AIRPORT_R_M,
            "desc": f"Поїздки до аеропорту чи з нього: {air_n}",
        },
        {
            "id": "long",
            "icon": "🛣️",
            "title": "Далека дорога",
            "n": 1,
            "km": km95,
            "desc": f"Поїздка довша за {km_text} км: довша за 95% поїздок тижня",
        },
        {
            "id": "ghost",
            "icon": "👻",
            "title": "Обігнав привида",
            "n": GHOST_SHIFTS,
            "desc": f"Зміни, де ти обігнав привида: {GHOST_SHIFTS}",
        },
        {
            "id": "rivals",
            "icon": "🏁",
            "title": "Усі сім",
            "n": 1,
            "desc": "Обжени всіх 7 ланосів за одну зміну",
        },
        {
            "id": "pax",
            "icon": "🧍",
            "title": "Сотня пасажирів",
            "n": PASSENGERS,
            "desc": f"Відвези пасажирів: {PASSENGERS}",
        },
        {
            "id": "districts",
            "icon": "🗺️",
            "title": "Увесь Порту",
            "n": len(spots),
            "r": DISTRICT_R_M,
            "spots": spots,
            "desc": f"Побувай у гарячих районах: {len(spots)} з {len(spots)}",
        },
        {
            "id": "legend",
            "icon": "👑",
            "title": "Легенда вихідних",
            "n": 1,
            "desc": "Легенда на зміні в суботу чи неділю",
        },
        {
            "id": "top10",
            "icon": "🏆",
            "title": "Десятка найкращих",
            "n": TOP10_SHIFTS,
            "desc": f"Зміни в десятці справжніх водіїв: {TOP10_SHIFTS}",
        },
        {
            "id": "week",
            "icon": "📅",
            "title": "Тиждень за кермом",
            "n": days,
            "desc": f"Дні тижня, коли ти їздив: {days}",
        },
        {
            "id": "money",
            "icon": "💶",
            "title": "Гроші на столі",
            "n": money,
            "eur": money,
            "desc": f"Заробіток за всі зміни разом: €{money}",
        },
        {
            "id": "combo",
            "icon": "🔥",
            "title": "Серія",
            "n": COMBO_N,
            "desc": f"Поїздки підряд в одній серії: {COMBO_N}",
        },
    ]
    return {"version": 1, "weekend": list(WEEKEND), "badges": badges}


def main(argv: list[str] | None = None) -> int:
    """Command line entry point.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        0 on success, 1 on an unreadable data file.
    """
    ap = argparse.ArgumentParser(description="Write game/achievements.json")
    ap.add_argument("--data", type=Path, default=DATA_DEFAULT)
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = ap.parse_args(argv)
    try:
        data = json.loads(args.data.read_text(encoding="utf-8"))
        doc = build_achievements(data)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
            encoding="utf-8",
        )
    except (OSError, ValueError, KeyError) as err:
        print(f"achievements error: {err}", file=sys.stderr)
        return 1
    print(f"wrote {args.out} ({len(doc['badges'])} badges)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
