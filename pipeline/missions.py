"""Shift missions computed from the real data of each shift (CONTRACT section 16).

Each of the 28 shifts gets three short missions. They give stars in the game (never money), so the
medals stay a fair race against the real drivers. The choice is deterministic and every threshold
comes from the shift's own data (percentiles of the trip lengths, the shift median, the busiest
hotspot, the trips that touch the airport, the rival who is on the level of a normal player).

Run ``python -m pipeline.missions`` to write ``game/missions.json``.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import zlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

DATA_DEFAULT = Path("game/game_data.json")
OUT_DEFAULT = Path("game/missions.json")

PER_SHIFT = 3  # missions per shift
SHIFT_S = 7200  # game s in a shift
HALF_S = SHIFT_S // 2  # «before half-time»
AIRPORT = (3232.0, 1323.0)  # Aeroporto in the map frame, metres (same point as pipeline.sim)
AIRPORT_R_M = 1500.0  # a trip touches the airport within this radius, metres
AIRPORT_MIN_TRIPS = 3  # the airport mission needs at least this many such trips in the shift
DISTRICT_R_M = 600.0  # a pickup belongs to a hotspot within this radius, metres
DISTRICT_MIN_PICKUPS = 10  # the busiest hotspot needs at least this many pickups
DISTRICT_N = 3  # passengers to take from the hotspot
LONG_PCT = 0.85  # a long trip is at or above this percentile of the shift's km
LONG_MIN_KM = 4.0  # but never shorter than this
COMBO_N = 3  # three trips in a row = ×1.2 (CONTRACT section 13)
NO_PLACE = "околиця"  # data name of a point far from every place

# The 7 rivals (CONTRACT section 13): id -> (name, nick, short name).
RIVALS: dict[str, tuple[str, str, str]] = {
    "ze": ("Зé", "Акула", "Зé"),
    "fatima": ("Дона Фатіма", "Королева стоянки", "Фатіму"),
    "rui": ("Руй", "Сова", "Руя"),
    "ines": ("Інеш", "Блискавка", "Інеш"),
    "tiago": ("Тіаго", "Снайпер", "Тіаго"),
    "lurdes": ("Лурдеш", "Хвиля", "Лурдеш"),
    "nuno": ("Нуну", "Новачок", "Нуну"),
}

KINDS = ("airport", "district", "long", "combo", "rival", "median")


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


def eur(x: float) -> str:
    """Format money like ``PG.util.eur``: ``€12,40``.

    Args:
        x: Euros.

    Returns:
        The text with a comma decimal and two digits.
    """
    return "€" + f"{x:.2f}".replace(".", ",")


def genitive(place: str) -> str:
    """Put a data place name after «з»: ``район X`` becomes ``району X``.

    Args:
        place: Hotspot name from the data.

    Returns:
        The name ready for «з <name>».
    """
    return "району " + place[len("район ") :] if place.startswith("район ") else place


def rank_key(shift_id: str, kind: str) -> int:
    """Return a stable pseudo-random key of a kind in a shift (crc32, same on every run).

    Args:
        shift_id: The shift id.
        kind: A mission kind.

    Returns:
        An integer used only for ordering.
    """
    return zlib.crc32(f"{shift_id}/{kind}".encode())


def airport_mission(orders: Sequence[Sequence[Any]], unit_m: float) -> dict[str, Any] | None:
    """Build the airport mission if enough trips of the shift touch the airport.

    Args:
        orders: Compact orders of the shift (CONTRACT section 4).
        unit_m: Metres per map unit.

    Returns:
        The mission, or ``None`` when the shift has fewer than ``AIRPORT_MIN_TRIPS`` such trips.
    """
    ax, ay = AIRPORT
    near = sum(
        1
        for o in orders
        if math.hypot(o[1] * unit_m - ax, o[2] * unit_m - ay) <= AIRPORT_R_M
        or math.hypot(o[3] * unit_m - ax, o[4] * unit_m - ay) <= AIRPORT_R_M
    )
    if near < AIRPORT_MIN_TRIPS:
        return None
    return {
        "kind": "airport",
        "title": "Поїздка до аеропорту або з нього",
        "short": "Аеропорт",
        "n": 1,
        "x": ax,
        "y": ay,
        "r": AIRPORT_R_M,
    }


def district_mission(
    orders: Sequence[Sequence[Any]], hot: Sequence[dict[str, Any]], unit_m: float
) -> dict[str, Any] | None:
    """Build the hotspot mission for the hotspot with the most pickups.

    Args:
        orders: Compact orders of the shift.
        hot: Hotspots ``{x, y, w, name}`` in map units.
        unit_m: Metres per map unit.

    Returns:
        The mission, or ``None`` if no named hotspot has ``DISTRICT_MIN_PICKUPS`` pickups.
    """
    best: tuple[int, dict[str, Any]] | None = None
    for h in hot:
        if h["name"] == NO_PLACE:
            continue
        hx, hy = h["x"] * unit_m, h["y"] * unit_m
        count = sum(
            1 for o in orders if math.hypot(o[1] * unit_m - hx, o[2] * unit_m - hy) <= DISTRICT_R_M
        )
        if count >= DISTRICT_MIN_PICKUPS and (best is None or count > best[0]):
            best = (count, h)
    if best is None:
        return None
    h = best[1]
    place = genitive(h["name"])
    return {
        "kind": "district",
        "title": f"Відвези {DISTRICT_N} пасажирів з {place}",
        "short": f"З {place}",
        "n": DISTRICT_N,
        "x": round(h["x"] * unit_m),
        "y": round(h["y"] * unit_m),
        "r": DISTRICT_R_M,
    }


def long_mission(orders: Sequence[Sequence[Any]]) -> dict[str, Any] | None:
    """Build the long-trip mission from the km distribution of the shift.

    Args:
        orders: Compact orders of the shift.

    Returns:
        The mission with ``km`` = the 85th percentile rounded to 0.5 km (at least 4 km), or
        ``None`` for a shift without orders.
    """
    if not orders:
        return None
    km = max(LONG_MIN_KM, round(percentile([o[7] for o in orders], LONG_PCT) * 2) / 2)
    text = f"{km:g}".replace(".", ",")
    return {
        "kind": "long",
        "title": f"Довга поїздка від {text} км",
        "short": f"Від {text} км",
        "n": 1,
        "km": km,
    }


def combo_mission() -> dict[str, Any]:
    """Build the combo mission (three trips in a row, ×1.2).

    Returns:
        The mission.
    """
    return {
        "kind": "combo",
        "title": "Комбо ×1.2: три поїздки підряд",
        "short": "Комбо ×1.2",
        "n": COMBO_N,
    }


def rival_mission(
    rival_eur: dict[str, float] | None, player_eur: float, shift_id: str
) -> dict[str, Any] | None:
    """Build the «beat a rival» mission with a rival on the level of a normal player.

    The rival is the one with the highest total that does not exceed ``player_eur`` (the total of
    the measuring bot on this shift); if all are above, the weakest one.

    Args:
        rival_eur: Total of each rival on this shift, by id (``None`` = no data).
        player_eur: What a normal player earns on this shift.
        shift_id: The shift id (breaks ties deterministically).

    Returns:
        The mission, or ``None`` without rival data.
    """
    if not rival_eur:
        return None
    ids = sorted(rival_eur, key=lambda r: (rival_eur[r], rank_key(shift_id, r)))
    below = [r for r in ids if rival_eur[r] <= player_eur]
    rid = below[-1] if below else ids[0]
    name, nick, short = RIVALS[rid]
    return {
        "kind": "rival",
        "title": f"Обжени {name} «{nick}» за гроші",
        "short": f"Обжени {short}",
        "n": 1,
        "rival": rid,
    }


def median_mission(median: float) -> dict[str, Any]:
    """Build the «earn the shift median before half-time» mission.

    Args:
        median: Median total of the real drivers of the shift, euros.

    Returns:
        The mission (``eur`` rounded up to cents, ``by`` = half of the shift in game s).
    """
    value = math.ceil(round(median * 100, 6)) / 100
    return {
        "kind": "median",
        "title": f"Зароби {eur(value)} за першу годину зміни",
        "short": f"{eur(value)} за годину",
        "n": 1,
        "eur": value,
        "by": HALF_S,
    }


def pick_missions(
    shift: dict[str, Any],
    unit_m: float,
    rival_eur: dict[str, float] | None = None,
    player_eur: float = 0.0,
) -> list[dict[str, Any]]:
    """Pick the three missions of one shift.

    The airport mission, if the data supports it, always comes first (it is the rarest). The other
    kinds the data supports are ordered by a stable hash of shift id and kind.

    Args:
        shift: A shift object of ``game_data.json``.
        unit_m: Metres per map unit.
        rival_eur: Total of each rival on this shift, by id (``None`` skips the rival mission).
        player_eur: What a normal player earns on this shift (picks the rival).

    Returns:
        ``PER_SHIFT`` missions, each with ``id`` (``m1``..), ``kind``, ``title``, ``short``, ``n``
        and the fields of its kind.
    """
    sid, orders = shift["id"], shift["orders"]
    made = {
        "airport": airport_mission(orders, unit_m),
        "district": district_mission(orders, shift["hot"], unit_m),
        "long": long_mission(orders),
        "combo": combo_mission(),
        "rival": rival_mission(rival_eur, player_eur, sid),
        "median": median_mission(shift["median"]),
    }
    eligible = [k for k in KINDS if made[k] is not None]
    eligible.sort(key=lambda k: (k != "airport", rank_key(sid, k)))
    out = []
    for i, kind in enumerate(eligible[:PER_SHIFT], start=1):
        m = made[kind]
        out.append({"id": f"m{i}", **m})
    return out


def rival_totals(data_path: Path) -> dict[str, tuple[dict[str, float], float]]:
    """Play every shift in the Python twin and return rival totals and the bot total.

    Args:
        data_path: ``game_data.json``.

    Returns:
        Per shift id ``({rival id: total}, bot total)`` on normal difficulty.
    """
    from pipeline import sim  # heavy import, only the CLI needs it

    settings = sim.Settings()
    out = {}
    for sh in sim.load_shifts(data_path):
        r = sim.play_shift(sh, "normal", settings)
        out[sh.id] = (dict(zip(sim.RIVAL_IDS, r.rival_eur, strict=True)), r.earned)
    return out


def build_missions(data: dict[str, Any], totals: dict | None = None) -> dict[str, Any]:
    """Build the whole ``missions.json`` document.

    Args:
        data: Parsed ``game_data.json``.
        totals: Output of :func:`rival_totals` (``None`` = no rival missions).

    Returns:
        ``{"version": 1, "shifts": {shift id: [mission, ...]}}``.
    """
    unit_m = data["unit_m"]
    shifts = {}
    for sh in data["shifts"]:
        rivals, bot = (totals or {}).get(sh["id"], (None, 0.0))
        shifts[sh["id"]] = pick_missions(sh, unit_m, rivals, bot)
    return {"version": 1, "shifts": shifts}


def main(argv: list[str] | None = None) -> int:
    """Command line entry point: write ``game/missions.json``.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        0 on success, 1 if the data file is missing.
    """
    ap = argparse.ArgumentParser(description="Compute the shift missions")
    ap.add_argument("--data", type=Path, default=DATA_DEFAULT)
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    ap.add_argument("--no-rivals", action="store_true", help="skip the (slower) rival mission")
    args = ap.parse_args(argv)
    if not args.data.is_file():
        print(f"data file not found: {args.data}", file=sys.stderr)
        return 1
    data = json.loads(args.data.read_text(encoding="utf-8"))
    totals = None if args.no_rivals else rival_totals(args.data)
    doc = build_missions(data, totals)
    text = json.dumps(doc, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text + "\n", encoding="utf-8")
    counts: dict[str, int] = {}
    for ms in doc["shifts"].values():
        for m in ms:
            counts[m["kind"]] = counts.get(m["kind"], 0) + 1
    print(f"wrote {args.out} ({len(text)} bytes); kinds: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
