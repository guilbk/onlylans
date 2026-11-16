"""Short Ukrainian facts about each shift, from its real data (CONTRACT section 17).

The result screen shows 3 or 4 of them next to the replay of the player's shift. Every fact is a
pure function of the shift's compact data, so the output is the same on every run.

Run ``python -m pipeline.facts`` to write ``game/facts.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pipeline import missions, places

DATA_DEFAULT = Path("game/game_data.json")
OUT_DEFAULT = Path("game/facts.json")

NBSP = " "  # keeps «1 234» and «23,4 км» on one line
DISTRICT_PREFIX = "район "
FAR_FROM = "околиці"  # «з околиці» (the data name is «околиця»)


def plural(n: int, one: str, few: str, many: str) -> str:
    """Pick the Ukrainian plural form: 1 / 2-4 / 5-20 (21 is «one», 12 is «many»).

    Args:
        n: The number.
        one: Form for 1, 21, 31 ...
        few: Form for 2-4, 22-24 ...
        many: Form for 0, 5-20, 25-30 ...

    Returns:
        The matching form.
    """
    n = abs(n)
    if n % 100 in range(11, 15):
        return many
    return one if n % 10 == 1 else few if n % 10 in (2, 3, 4) else many


def thousands(n: int) -> str:
    """Write an integer with a no-break space between thousands: ``1234`` becomes ``1 234``.

    Args:
        n: The integer.

    Returns:
        The text.
    """
    return f"{n:,}".replace(",", NBSP)


def km_text(km: float) -> str:
    """Write kilometres with one decimal and a comma: ``23.4`` becomes ``23,4 км``.

    Args:
        km: Kilometres.

    Returns:
        The text.
    """
    return f"{km:.1f}".replace(".", ",") + NBSP + "км"


def trips_fact(orders: Sequence[Sequence[Any]]) -> str:
    """Count the trips of the real drivers.

    Args:
        orders: Compact orders of the shift.

    Returns:
        The fact text.
    """
    n = len(orders)
    word = plural(n, "поїздку", "поїздки", "поїздок")
    return f"Справжні водії цієї зміни зробили {thousands(n)} {word}"


def longest_fact(orders: Sequence[Sequence[Any]], unit_m: float) -> str | None:
    """Name the longest trip and where it started.

    Args:
        orders: Compact orders of the shift.
        unit_m: Metres per map unit.

    Returns:
        The fact text, or ``None`` when the shift has no orders.
    """
    if not orders:
        return None
    o = max(orders, key=lambda r: (r[7], -r[0]))  # longest; the earlier one on a tie
    name = places.place_name(o[1] * unit_m, o[2] * unit_m)
    start = FAR_FROM if name == places.NAME_FAR else missions.genitive(name)
    return f"Найдовша поїздка — {km_text(o[7])} з {start.replace(' ', NBSP, 1)}"


def district_fact(hot: Sequence[dict[str, Any]]) -> str | None:
    """Name the district with the largest share of pickups.

    Args:
        hot: Hotspots of the shift (``name``, ``w``).

    Returns:
        The fact text, or ``None`` when there are no hotspots.
    """
    if not hot:
        return None
    top = max(hot, key=lambda h: h["w"])
    name = top["name"].removeprefix(DISTRICT_PREFIX)
    return f"Найзавантаженіший район — {name}"


def ghost_fact(sh: dict[str, Any]) -> str:
    """Tell how many trips the ghost (the best real driver) made and what he earned.

    Args:
        sh: One shift of the game data.

    Returns:
        The fact text.
    """
    n = len(sh["ghost"]["orders"])
    word = plural(n, "поїздку", "поїздки", "поїздок")
    return f"Привид зробив {n} {word}, заробив {missions.eur(sh['ghost']['total'])}"


def shift_facts(sh: dict[str, Any], unit_m: float) -> list[str]:
    """Build the 3-4 facts of one shift, in the order shown.

    Args:
        sh: One shift of the game data.
        unit_m: Metres per map unit.

    Returns:
        The facts (the ones the data cannot support are left out).
    """
    parts = [
        trips_fact(sh["orders"]),
        longest_fact(sh["orders"], unit_m),
        district_fact(sh.get("hot", [])),
        ghost_fact(sh),
    ]
    return [p for p in parts if p]


def build_facts(data: dict[str, Any]) -> dict[str, Any]:
    """Build the facts of every shift.

    Args:
        data: Parsed ``game_data.json``.

    Returns:
        ``{"version": 1, "shifts": {shift id: [fact, ...]}}``.
    """
    unit_m = data["unit_m"]
    return {"version": 1, "shifts": {sh["id"]: shift_facts(sh, unit_m) for sh in data["shifts"]}}


def main(argv: list[str] | None = None) -> int:
    """Command line entry point: write ``game/facts.json``.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        0 on success, 1 if the data file is missing.
    """
    ap = argparse.ArgumentParser(description="Compute the result facts of each shift")
    ap.add_argument("--data", type=Path, default=DATA_DEFAULT)
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = ap.parse_args(argv)
    if not args.data.is_file():
        print(f"data file not found: {args.data}", file=sys.stderr)
        return 1
    doc = build_facts(json.loads(args.data.read_text(encoding="utf-8")))
    text = json.dumps(doc, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({len(text)} bytes, {len(doc['shifts'])} shifts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
