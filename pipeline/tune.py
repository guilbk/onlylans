"""Sweep the balance levers with the Python twin (``pipeline.sim``) and pick the closest setting.

Levers: ``LEAD`` per call type, ``DIFF_K`` per difficulty and the rivals' ``DIFF`` numbers. The
medal thresholds and the data are not levers (CONTRACT section 0). Every candidate is played on
all shifts with the 200 s bot of ``tools/engine_test.mjs`` and scored against the medal-share
targets.

Two picks are printed per run: the best point anywhere in the grid, and the best point that obeys
the *reachability floor*. The bot can only take a pin once it has waited ``delay`` s and needs at
least the boarding time to arrive, so a call type whose ``lead * DIFF_K`` is below
``delay + BOARD_S + margin`` is invisible to the bot, and a result reached that way says nothing
about a player who reacts faster.

Usage::

    python -m pipeline.tune [--data game/game_data.json] [--workers N] [--top N]
"""

from __future__ import annotations

import argparse
import itertools
import math
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

from pipeline import sim

FLOOR_MARGIN_S = 30.0  # slack above delay + boarding for the reachability floor
SHIFT_STEP = 1 / 28  # one shift flipping moves a share by this much
LOSS_SCALE = 100.0  # weight of a missed band against the design-change cost
HARDER_MARGIN_EUR = 1.0  # a harder difficulty must earn at least this much less
LEAD_GRID_A = tuple(range(310, 791, 40))
LEAD_GRID_B = tuple(range(310, 591, 20))
LEAD_GRID_C = tuple(range(310, 431, 10))
LEAD_GRID_FREE = tuple(range(180, 781, 30))  # the grid without the reachability floor
RADIUS_SCALES = (1.0, 0.4)  # RADIUS (A, B, C together) as a share of the design values
K_EASY_GRID = (1.0, 1.05, 1.1, 1.25, 1.4, 1.6, 1.8)
K_HARD_GRID = (0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 1.0)
HARD_NEAR_GRID = (3200.0, 5000.0)
HARD_ATTN_GRID = (0.28, 0.5)
HARD_DUTY_GRID = (0.5, 0.9)
HARD_SPEED_GRID = (1.3, 1.6)


@dataclass(frozen=True)
class Band:
    """An allowed range of a share or a mean.

    Attributes:
        lo: Lower end, inclusive.
        hi: Upper end, inclusive.
    """

    lo: float
    hi: float


@dataclass(frozen=True)
class Target:
    """Medal-share targets of one difficulty (shares of the 28 shifts, 0..1).

    Attributes:
        bronze: Band for the share with bronze or better.
        gold: Band for the share with gold or better.
        legend: Band for the share with legend.
    """

    bronze: Band
    gold: Band
    legend: Band


TARGETS = {
    "easy": Target(Band(1.0, 1.0), Band(0.50, 0.70), Band(0.0, 1.0)),
    "normal": Target(Band(0.85, 1.0), Band(0.35, 0.50), Band(0.0, 0.15)),
    "hard": Target(Band(0.70, 1.0), Band(0.15, 0.30), Band(0.0, 1.0)),
}


@dataclass(frozen=True)
class Candidate:
    """One evaluated setting.

    Attributes:
        settings: The levers.
        summaries: Result summary per difficulty that was played.
        miss: Squared distance of the shares to their bands (0 = all inside).
        change: Distance of the levers from the current design (log scale).
    """

    settings: sim.Settings
    summaries: dict[str, sim.Summary]
    miss: float
    change: float


def band_miss(value: float, band: Band) -> float:
    """Distance of a value outside a band.

    Args:
        value: Measured value.
        band: Allowed range.

    Returns:
        0 inside the band, else the distance to the nearest end.
    """
    return max(band.lo - value, value - band.hi, 0.0)


def target_miss(sm: sim.Summary, target: Target) -> float:
    """Squared distance of one difficulty's shares to its target bands.

    Args:
        sm: Summary of the difficulty.
        target: Its targets.

    Returns:
        Sum of squared misses (0 when every share is inside its band).
    """
    parts = (
        band_miss(sm.bronze, target.bronze),
        band_miss(sm.gold, target.gold),
        band_miss(sm.legend, target.legend),
    )
    return sum(p * p for p in parts)


def harder_miss(summaries: dict[str, sim.Summary]) -> float:
    """Penalty when a harder difficulty is not strictly harder (bot euros and gold share).

    Args:
        summaries: Summaries for any of easy, normal, hard.

    Returns:
        0 when the order easy > normal > hard holds with a margin, else a positive number.
    """
    miss = 0.0
    for easier, harder in (("easy", "normal"), ("normal", "hard")):
        if easier in summaries and harder in summaries:
            a, b = summaries[easier], summaries[harder]
            miss += max(0.0, b.bot_eur - (a.bot_eur - HARDER_MARGIN_EUR)) / a.bot_eur
            miss += max(0.0, b.gold - (a.gold - SHIFT_STEP / 2))
    return miss


def change_cost(settings: sim.Settings) -> float:
    """How far the levers are from the current design (sum of absolute log ratios).

    Args:
        settings: Candidate levers.

    Returns:
        0 for the current numbers, growing with every change.
    """
    cost = sum(abs(math.log(a / b)) for a, b in zip(settings.lead, sim.DEFAULT_LEAD, strict=True))
    for d in sim.DIFFICULTIES:
        cost += abs(math.log(settings.diff_k[d] / sim.DEFAULT_DIFF_K[d]))
    cost += sum(
        abs(math.log(a / b)) for a, b in zip(settings.radius, sim.DEFAULT_RADIUS, strict=True)
    )
    return cost


def reach_floor(settings: sim.Settings) -> float:
    """The shortest non-rush pin window the bot can still use, per difficulty.

    Args:
        settings: Candidate levers.

    Returns:
        ``min(lead[c] * DIFF_K[d]) - delay - BOARD_S`` over call types and difficulties, s.
        Negative or tiny values mean some call type is invisible to the bot.
    """
    short = min(v * k for v in settings.lead for k in settings.diff_k.values())
    return short - settings.delay - sim.BOARD_S


def obeys_floor(settings: sim.Settings) -> bool:
    """Does every call type stay reachable for the bot on every difficulty?

    Args:
        settings: Candidate levers.

    Returns:
        True when :func:`reach_floor` is at least the margin.
    """
    return reach_floor(settings) >= FLOOR_MARGIN_S


def evaluate(
    settings: sim.Settings,
    difficulties: tuple[str, ...],
    data: Path,
    n_shifts: int,
    pool: ProcessPoolExecutor | None,
) -> Candidate:
    """Play all shifts on the given difficulties and score the result.

    Args:
        settings: Levers.
        difficulties: Difficulties to play.
        data: Path of ``game_data.json``.
        n_shifts: Number of shifts.
        pool: Open worker pool or None.

    Returns:
        The scored candidate.
    """
    runs = sim.run_difficulties(data, settings, difficulties, 1, n_shifts, pool)
    sums = {d: sim.summarise(runs[d]) for d in difficulties}
    miss = sum(target_miss(sums[d], TARGETS[d]) for d in difficulties) + harder_miss(sums)
    return Candidate(settings, sums, miss, change_cost(settings))


def _rival_eur(c: Candidate) -> float:
    """Mean rival euros over the played difficulties (stronger rivals make a better race)."""
    sums = list(c.summaries.values())
    if not sums:
        return 0.0
    return sum(sum(sm.rival_eur) / len(sm.rival_eur) for sm in sums) / len(sums)


def rank(cands: list[Candidate]) -> list[Candidate]:
    """Order candidates: smaller band miss, then smaller change of the design, then stronger rivals.

    Args:
        cands: Evaluated candidates.

    Returns:
        A new sorted list.
    """
    return sorted(cands, key=lambda c: (round(c.miss * LOSS_SCALE, 3), c.change, -_rival_eur(c)))


def normal_grid(base: sim.Settings, floor_only: bool = False) -> list[sim.Settings]:
    """Settings that vary LEAD for the three call types (monotone A >= B >= C) and RADIUS.

    Args:
        base: Settings to start from.
        floor_only: Keep only the points that obey the reachability floor.

    Returns:
        One settings object per grid point.
    """
    out = []
    grids = (LEAD_GRID_A, LEAD_GRID_B, LEAD_GRID_C) if floor_only else (LEAD_GRID_FREE,) * 3
    for (a, b, c), k in itertools.product(itertools.product(*grids), RADIUS_SCALES):
        if a < b or b < c:
            continue
        radius = tuple(r * k for r in sim.DEFAULT_RADIUS)
        cand = replace(base, lead=(float(a), float(b), float(c)), radius=radius)
        if not floor_only or obeys_floor(cand):
            out.append(cand)
    return out


def easy_grid(base: sim.Settings) -> list[sim.Settings]:
    """Settings that vary ``DIFF_K['easy']``.

    Args:
        base: Settings to start from.

    Returns:
        One settings object per grid point.
    """
    return [replace(base, diff_k={**base.diff_k, "easy": k}) for k in K_EASY_GRID]


def hard_grid(base: sim.Settings) -> list[sim.Settings]:
    """Settings that vary ``DIFF_K['hard']`` and how hard the hard rivals contend.

    Args:
        base: Settings to start from.

    Returns:
        One settings object per grid point.
    """
    out = []
    for k, near, attn, duty, speed in itertools.product(
        K_HARD_GRID, HARD_NEAR_GRID, HARD_ATTN_GRID, HARD_DUTY_GRID, HARD_SPEED_GRID
    ):
        rv = replace(base.rivals["hard"], near=near, attn=attn, duty=duty, speed=speed)
        out.append(
            replace(base, diff_k={**base.diff_k, "hard": k}, rivals={**base.rivals, "hard": rv})
        )
    return out


def sweep(
    grid: list[sim.Settings],
    difficulty: str,
    data: Path,
    n_shifts: int,
    pool: ProcessPoolExecutor | None,
) -> list[Candidate]:
    """Evaluate every grid point on one difficulty.

    Args:
        grid: Settings to try.
        difficulty: The difficulty the grid varies.
        data: Path of ``game_data.json``.
        n_shifts: Number of shifts.
        pool: Open worker pool or None.

    Returns:
        Candidates in grid order.
    """
    return [evaluate(s, (difficulty,), data, n_shifts, pool) for s in grid]


def format_row(label: str, difficulty: str, c: Candidate) -> str:
    """One table row for a candidate.

    Args:
        label: Row label.
        difficulty: Difficulty shown.
        c: The candidate.

    Returns:
        A line with the levers, the shares, bot euros, lost orders and rival euros.
    """
    st, sm = c.settings, c.summaries[difficulty]
    lead = "/".join(f"{v:.0f}" for v in st.lead)
    rad = "/".join(f"{v:.0f}" for v in st.radius)
    rv = st.rivals[difficulty]
    who = f"near {rv.near:.0f} attn {rv.attn:.2f} duty {rv.duty:.2f} speed {rv.speed:.1f}"
    riv = sum(sm.rival_eur) / len(sm.rival_eur)
    return (
        f"{label:<10} lead {lead:<11} rad {rad:<14} K {st.diff_k[difficulty]:.2f} | "
        f"bronze+ {sm.bronze:4.0%} "
        f"silver+ {sm.silver:4.0%} gold+ {sm.gold:4.0%} legend {sm.legend:4.0%} | "
        f"bot €{sm.bot_eur:5.1f} "
        f"lost {sm.lost:3.1f} rival €{riv:5.1f} | miss {c.miss:.4f} "
        f"floor {reach_floor(st):+.0f}s | rivals {who}"
    )


def report(title: str, difficulty: str, cands: list[Candidate], top: int) -> list[str]:
    """Table of the best candidates: the best anywhere and the best under the floor.

    Args:
        title: Heading.
        difficulty: Difficulty shown.
        cands: Evaluated candidates.
        top: Rows per table.

    Returns:
        Report lines.
    """
    lines = [f"== {title} ({len(cands)} points)"]
    ranked = rank(cands)
    lines += [format_row(f"any #{i + 1}", difficulty, c) for i, c in enumerate(ranked[:top])]
    floored = [c for c in ranked if obeys_floor(c.settings)]
    lines += [format_row(f"floor #{i + 1}", difficulty, c) for i, c in enumerate(floored[:top])]
    if not floored:
        lines.append("(no point obeys the reachability floor)")
    return lines


def _lead(text: str) -> tuple[float, float, float]:
    """Parse ``A,B,C`` into three lead times (argparse type)."""
    a, b, c = (float(v) for v in text.split(","))
    return a, b, c


def main(argv: list[str] | None = None) -> int:
    """CLI: sweep normal (LEAD), then easy and hard (DIFF_K, hard rivals) around the normal pick.

    Args:
        argv: Command-line arguments (default: ``sys.argv[1:]``).

    Returns:
        0 after the tables are printed, 1 if no normal point obeys the floor.
    """
    ap = argparse.ArgumentParser(description="Sweep the balance levers with the Python twin")
    ap.add_argument("--data", type=Path, default=Path("game/game_data.json"))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--floor", action="store_true", help="pick only among points obeying the floor")
    ap.add_argument(
        "--lead", type=_lead, default=None, metavar="A,B,C",
        help="skip the LEAD sweep and tune the other levers around these leads",
    )  # fmt: skip
    args = ap.parse_args(argv)
    n_shifts = len(sim.load_shifts(args.data))
    with sim.open_pool(args.data, args.workers) as pool:
        start = sim.Settings() if args.lead is None else replace(sim.Settings(), lead=args.lead)
        grid = normal_grid(start, args.floor) if args.lead is None else [start]
        normal = sweep(grid, "normal", args.data, n_shifts, pool)
        print("\n".join(report("normal: LEAD A/B/C", "normal", normal, args.top)))
        pool_c = [c for c in rank(normal) if not args.floor or obeys_floor(c.settings)]
        if not pool_c:
            print("no point of the normal sweep obeys the reachability floor: raise --lead")
            return 1
        base = pool_c[0].settings
        easy = sweep(easy_grid(base), "easy", args.data, n_shifts, pool)
        print("\n".join(report("easy: DIFF_K", "easy", easy, args.top)))
        hard = sweep(hard_grid(base), "hard", args.data, n_shifts, pool)
        print("\n".join(report("hard: DIFF_K and rivals", "hard", hard, args.top)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
