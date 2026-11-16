"""Headless balance check: a thin command line over the exact engine port in ``pipeline/sim.py``.

The bot of ``sim.py`` plays every shift of ``game/game_data.json`` by the game rules (CONTRACT
sections 4 and 9 to 11) against the 7 rivals, and the result is graded with the medal thresholds.
All numbers come from ``sim.py`` (levers LEAD, RADIUS, DIFF_K, rivals, combo, tips), so this
tool cannot drift from the game. ``--lag`` is the reaction time of the bot in game seconds.
Units: euros and game seconds.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from itertools import product
from pathlib import Path
from typing import Any

from pipeline import sim

DEFAULT_DATA = "game/game_data.json"
MEDAL_NAMES = ("none", "bronze", "silver", "gold", "legend")
STRATEGIES = ("value",)  # the one rule of the sim bot: best fare per second among reachable pins


@dataclass(frozen=True)
class Result:
    """Outcome of one bot shift as the table shows it."""

    shift_id: str
    earned: float
    median: float
    top10: float
    ghost: float
    medal: int
    rank: int
    n_drivers: int


def rank_among(earned: float, ranking: list[float]) -> int:
    """Rank among the real drivers: 1 + number of drivers with more money."""
    return 1 + sum(1 for r in ranking if r > earned)


def evaluate(data: Path, diff: str, lag: float, workers: int) -> list[Result]:
    """Play every shift with the sim bot and grade it.

    Args:
        data: Path of ``game_data.json``.
        diff: ``easy``, ``normal`` or ``hard``.
        lag: Reaction time of the bot, game s.
        workers: Worker processes for the sim (1 = this process).

    Returns:
        One result per shift in campaign order.
    """
    shifts = sim.load_shifts(data)
    rankings = [s["ranking"] for s in json.loads(data.read_text(encoding="utf-8"))["shifts"]]
    jobs = [(i, diff, sim.Settings(delay=lag)) for i in range(len(shifts))]
    played = sim.play_many(jobs, data, workers)
    return [
        Result(sh.id, r.earned, sh.median, sh.top10, sh.ghost, r.medal,
               rank_among(r.earned, rk), len(rk))
        for sh, r, rk in zip(shifts, played, rankings, strict=True)
    ]  # fmt: skip


def summarize(results: list[Result]) -> dict[str, float]:
    """Share of shifts with at least bronze, silver, gold and legend.

    Args:
        results: Results of one run.

    Returns:
        Shares 0..1 keyed by medal name.
    """
    n = max(len(results), 1)
    return {name: sum(r.medal >= m for r in results) / n
            for m, name in enumerate(MEDAL_NAMES) if m > 0}  # fmt: skip


def format_table(diff: str, strategy: str, lag: float, results: list[Result]) -> str:
    """Render one run as a text table plus the summary line.

    Args:
        diff: Difficulty of the run.
        strategy: Bot strategy name.
        lag: Reaction lag of the run.
        results: Results of the run.

    Returns:
        Multi-line text.
    """
    lines = [
        f"== diff={diff} strategy={strategy} lag={lag:g}",
        f"{'shift':<12}{'bot EUR':>9}{'median':>9}{'top10':>9}{'ghost':>9}  {'medal':<7}rank",
    ]
    for r in results:
        lines.append(
            f"{r.shift_id:<12}{r.earned:>9.2f}{r.median:>9.2f}{r.top10:>9.2f}"
            f"{r.ghost:>9.2f}  {MEDAL_NAMES[r.medal]:<7}{r.rank}/{r.n_drivers}"
        )
    s = summarize(results)
    lines.append("summary: " + "  ".join(f"{k}+ {v:.0%}" for k, v in s.items()))
    return "\n".join(lines)


def parse_list(text: str, cast: Callable[[str], Any]) -> list[Any]:
    """Split a comma separated CLI list and cast each item."""
    return [cast(x) for x in text.split(",") if x.strip()]


def build_parser() -> argparse.ArgumentParser:
    """Build the command line parser."""
    ap = argparse.ArgumentParser(prog="pipeline.balance", description=__doc__)
    ap.add_argument("--data", type=Path, default=Path(DEFAULT_DATA))
    ap.add_argument("--strategy", default="value", help="only 'value' (the sim bot's rule)")
    ap.add_argument("--lag", default="120,200,300", help="reaction lag, game s")
    ap.add_argument("--diff", default="easy,normal,hard")
    ap.add_argument("--shifts", default="", help="campaign indices to show, default all")
    ap.add_argument("--workers", type=int, default=4, help="sim worker processes")
    ap.add_argument("--json", type=Path, default=None, help="also write results here")
    return ap


def main(argv: list[str] | None = None) -> int:
    """Run the balance check from the command line.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        Exit code.
    """
    args = build_parser().parse_args(argv)
    keep = parse_list(args.shifts, int) if args.shifts else None
    runs = []
    for diff, strategy, lag in product(
        parse_list(args.diff, str), parse_list(args.strategy, str), parse_list(args.lag, float)
    ):
        if diff not in sim.DIFFICULTIES or strategy not in STRATEGIES:
            raise SystemExit(f"unknown diff/strategy: {diff}/{strategy}")
        results = evaluate(args.data, diff, lag, args.workers)
        if keep is not None:
            results = [results[i] for i in keep]
        print(format_table(diff, strategy, lag, results))
        runs.append(
            {
                "params": {"diff": diff, "strategy": strategy, "lag": lag},
                "results": [asdict(r) for r in results],
                "summary": summarize(results),
            }
        )
    if args.json:
        args.json.write_text(json.dumps(runs, sort_keys=True, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
