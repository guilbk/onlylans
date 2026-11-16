"""Headless balance check: bots play every shift by the contract rules (CONTRACT §4, §9-§11).

A human-like bot (it notices a pin only ``lag`` game seconds after it appears) plays each shift of
``game/game_data.json`` and the result is compared with the medal thresholds. AI rivals, passenger
kinds and tips are out of scope. Units: metres, game seconds, euros.
"""

from __future__ import annotations

import argparse
import json
import math
from bisect import bisect_right
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from itertools import product
from pathlib import Path
from typing import Any

SHIFT_S = 7200.0
BOARD_S = 30.0
PTS_STEP_S = 15.0
LEAD_S = (720.0, 540.0, 420.0)
RADIUS_M = (5000.0, 3500.0, 2500.0)
DIFF_K = {"easy": 1.25, "normal": 1.0, "hard": 0.85}
HOME = (9110.0, 12443.0)
LEGEND_FACTOR = 1.25
DEFAULT_DATA = "game/game_data.json"
MEDAL_NAMES = ("none", "bronze", "silver", "gold", "legend")


@dataclass(frozen=True)
class Order:
    """One taxi order; positions in metres, times in game seconds."""

    i: int
    t: float
    x0: float
    y0: float
    xs: tuple[float, ...]
    ys: tuple[float, ...]
    d: float
    fare: float
    c: int

    @property
    def x1(self) -> float:
        """Drop-off x in metres."""
        return self.xs[-1]

    @property
    def y1(self) -> float:
        """Drop-off y in metres."""
        return self.ys[-1]


@dataclass(frozen=True)
class Shift:
    """One 2-hour shift with its real-driver thresholds."""

    id: str
    start_hour: int
    ranking: tuple[float, ...]
    median: float
    top10: float
    ghost: float
    speed_by_hour: tuple[float, ...]
    detour: float
    orders: tuple[Order, ...]
    times: tuple[float, ...] = field(default=(), repr=False)


@dataclass(frozen=True)
class Params:
    """Bot settings: difficulty name, strategy name and reaction lag (game s)."""

    diff: str
    strategy: str
    lag: float


@dataclass
class BotState:
    """Where the bot is: at (x, y) at time t, then riding ``ride`` (if any) from time t."""

    x: float
    y: float
    t: float
    ride: Order | None = None
    money: float = 0.0
    rides: int = 0
    taken: set[int] = field(default_factory=set)


@dataclass(frozen=True)
class Result:
    """Outcome of one bot shift."""

    shift_id: str
    earned: float
    median: float
    top10: float
    ghost: float
    medal: int
    rank: int
    n_drivers: int


def parse_order(i: int, raw: list[Any], unit_m: float) -> Order:
    """Turn a compact order array (CONTRACT §4) into an `Order` in metres.

    Args:
        i: Index of the order in its shift.
        raw: ``[t, x0, y0, x1, y1, pts, d, km, fare, c, stand, taxi]``, positions in map units.
        unit_m: Metres per map unit.

    Returns:
        The order with the full polyline (one point per 15 s of ride).
    """
    x, y = raw[1] * unit_m, raw[2] * unit_m
    xs, ys = [x], [y]
    pts = raw[5]
    for k in range(0, len(pts), 2):
        x += pts[k] * unit_m
        y += pts[k + 1] * unit_m
        xs.append(x)
        ys.append(y)
    return Order(i, float(raw[0]), xs[0], ys[0], tuple(xs), tuple(ys), float(raw[6]),
                 float(raw[8]), int(raw[9]))


def parse_shift(raw: dict[str, Any], unit_m: float) -> Shift:
    """Turn one JSON shift object into a `Shift`.

    Args:
        raw: Shift object of ``game_data.json``.
        unit_m: Metres per map unit.

    Returns:
        The parsed shift (orders sorted by ``t`` as in the file).
    """
    orders = tuple(parse_order(i, o, unit_m) for i, o in enumerate(raw["orders"]))
    ranking = tuple(float(v) for v in raw["ranking"])
    return Shift(raw["id"], int(raw["start_hour"]), ranking, float(raw["median"]),
                 float(raw["top10"]), ranking[0], tuple(float(v) for v in raw["speed_by_hour"]),
                 float(raw["detour"]), orders, tuple(o.t for o in orders))


def load_shifts(path: Path) -> list[Shift]:
    """Read all shifts of a ``game_data.json`` file.

    Args:
        path: Path to the file.

    Returns:
        Shifts in campaign order.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    return [parse_shift(s, float(data["unit_m"])) for s in data["shifts"]]


def speed_kmh(shift: Shift, t: float) -> float:
    """Speed at game time ``t`` by local hour of day (CONTRACT §11).

    Args:
        shift: The shift.
        t: Game seconds from shift start.

    Returns:
        km/h.
    """
    return shift.speed_by_hour[(shift.start_hour + int(t // 3600)) % 24]


def eta_s(shift: Shift, x: float, y: float, t: float, o: Order) -> float:
    """Seconds to drive from (x, y) to the pickup of ``o`` incl. boarding (CONTRACT §11).

    Args:
        shift: The shift (detour and speeds).
        x: Start x in metres.
        y: Start y in metres.
        t: Game time of departure.
        o: Order to pick up.

    Returns:
        Seconds.
    """
    straight_km = math.hypot(o.x0 - x, o.y0 - y) / 1000
    return straight_km * shift.detour / speed_kmh(shift, t) * 3600 + BOARD_S


def ride_position(o: Order, rel: float) -> tuple[float, float]:
    """Car position ``rel`` seconds into the ride of ``o`` (linear between 15 s points).

    Args:
        o: The order being ridden.
        rel: Seconds since pickup; clamped to the ride.

    Returns:
        (x, y) in metres.
    """
    k = min(max(rel, 0.0) / PTS_STEP_S, len(o.xs) - 1.0)
    i = min(int(k), len(o.xs) - 2) if len(o.xs) > 1 else 0
    f = k - i if len(o.xs) > 1 else 0.0
    j = min(i + 1, len(o.xs) - 1)
    return o.xs[i] + (o.xs[j] - o.xs[i]) * f, o.ys[i] + (o.ys[j] - o.ys[i]) * f


def cruise_position(shift: Shift, st: BotState, goal: tuple[float, float], t: float
                    ) -> tuple[float, float]:
    """Position at time ``t`` when cruising from the state's anchor toward ``goal``.

    Args:
        shift: The shift (speed, detour).
        st: Anchor position and time (no ride in progress at ``t``).
        goal: Cruise target in metres.
        t: Game time, >= ``st.t``.

    Returns:
        (x, y) in metres.
    """
    dist = math.hypot(goal[0] - st.x, goal[1] - st.y)
    if dist == 0:
        return st.x, st.y
    moved = (t - st.t) / 3600 * speed_kmh(shift, st.t) / shift.detour * 1000
    f = min(1.0, moved / dist)
    return st.x + (goal[0] - st.x) * f, st.y + (goal[1] - st.y) * f


def origin_at(shift: Shift, st: BotState, goal: tuple[float, float], tau: float
              ) -> tuple[float, float, float]:
    """Where and when a booking made at ``tau`` starts driving.

    While riding the origin is the drop-off at ride end (CONTRACT §11); otherwise the cruising car.

    Args:
        shift: The shift.
        st: Bot state.
        goal: Cruise target in metres.
        tau: Decision time.

    Returns:
        (x, y, fromT) with fromT >= tau.
    """
    if st.ride is not None and tau < st.t + st.ride.d:
        return st.ride.x1, st.ride.y1, st.t + st.ride.d
    if st.ride is not None:
        base = BotState(st.ride.x1, st.ride.y1, st.t + st.ride.d)
        x, y = cruise_position(shift, base, goal, tau)
        return x, y, tau
    x, y = cruise_position(shift, st, goal, tau)
    return x, y, tau


def car_position(shift: Shift, st: BotState, goal: tuple[float, float], tau: float
                 ) -> tuple[float, float]:
    """Actual car position at ``tau`` (on the ride polyline while riding).

    Args:
        shift: The shift.
        st: Bot state.
        goal: Cruise target in metres.
        tau: Game time.

    Returns:
        (x, y) in metres.
    """
    if st.ride is not None and tau < st.t + st.ride.d:
        return ride_position(st.ride, tau - st.t)
    x, y, _ = origin_at(shift, st, goal, tau)
    return x, y


def scan_pins(shift: Shift, st: BotState, goal: tuple[float, float], tau: float, p: Params
              ) -> tuple[list[tuple[Order, float, float]], float]:
    """Pins the bot knows at ``tau`` and can still reach, plus the next moment a pin gets noticed.

    Args:
        shift: The shift.
        st: Bot state.
        goal: Cruise target in metres.
        tau: Decision time.
        p: Bot settings.

    Returns:
        (list of (order, eta, pickup time), next notice time or infinity).
    """
    k = DIFF_K[p.diff]
    cx, cy = car_position(shift, st, goal, tau)
    ox, oy, from_t = origin_at(shift, st, goal, tau)
    found: list[tuple[Order, float, float]] = []
    nxt = math.inf
    for o in shift.orders[bisect_right(shift.times, tau):]:
        lead = LEAD_S[o.c] * k
        notice = o.t - lead + p.lag
        if o.t - LEAD_S[0] * k + p.lag > tau and o.t - LEAD_S[0] * k + p.lag >= nxt:
            break
        if o.i in st.taken or notice >= o.t:
            continue
        if notice > tau:
            nxt = min(nxt, notice)
        elif math.hypot(o.x0 - cx, o.y0 - cy) <= RADIUS_M[o.c] * k:
            eta = eta_s(shift, ox, oy, from_t, o)
            if from_t + eta <= o.t:
                found.append((o, eta, from_t + eta))
    return found, nxt


def score_value(o: Order, eta: float) -> float:
    """Value strategy score: fare per second of pickup plus ride."""
    return o.fare / (eta + o.d)


def score_nearest(o: Order, eta: float) -> float:
    """Nearest strategy score: the smaller eta wins."""
    return -eta


STRATEGIES: dict[str, Callable[[Order, float], float]] = {
    "value": score_value,
    "nearest": score_nearest,
}


def choose(found: list[tuple[Order, float, float]], strategy: str) -> tuple[Order, float, float]:
    """Pick the best pin; ties go to the earlier order.

    Args:
        found: Non-empty candidates (order, eta, pickup time).
        strategy: Key of `STRATEGIES`.

    Returns:
        The chosen candidate.
    """
    score = STRATEGIES[strategy]
    return max(found, key=lambda c: (score(c[0], c[1]), -c[0].i))


def next_booking(shift: Shift, st: BotState, goal: tuple[float, float], p: Params
                 ) -> tuple[Order, float] | None:
    """Find the next order the bot books, scanning decision moments in event order.

    Args:
        shift: The shift.
        st: Bot state (decisions start at ``st.t``, the pickup of the current ride).
        goal: Cruise target in metres.
        p: Bot settings.

    Returns:
        (order, pickup time) or None if nothing more is ever booked.
    """
    tau = st.t
    while tau < SHIFT_S:
        found, nxt = scan_pins(shift, st, goal, tau, p)
        if found:
            o, _, pickup = choose(found, p.strategy)
            return o, pickup
        tau = nxt
    return None


def demand_centre(shift: Shift) -> tuple[float, float]:
    """Mean pickup point of the shift: where an idle bot cruises."""
    n = max(len(shift.orders), 1)
    return (sum(o.x0 for o in shift.orders) / n, sum(o.y0 for o in shift.orders) / n)


def play_shift(shift: Shift, p: Params) -> float:
    """Play one shift with the bot.

    Args:
        shift: The shift.
        p: Bot settings.

    Returns:
        Money earned in euros (rounded to cents at each pickup).
    """
    goal = demand_centre(shift)
    st = BotState(HOME[0], HOME[1], 0.0)
    while (booking := next_booking(shift, st, goal, p)) is not None:
        o, pickup = booking
        taken = st.taken | {o.i}
        st = BotState(o.x0, o.y0, pickup, o, round(st.money + o.fare, 2), st.rides + 1, taken)
    return st.money


def medal_for(earned: float, shift: Shift) -> int:
    """Medal 0..4 by CONTRACT §11 (4: >= 1.25 x ghost, 3: > ghost, 2: >= top10, 1: >= median)."""
    if earned >= LEGEND_FACTOR * shift.ghost:
        return 4
    if earned > shift.ghost:
        return 3
    if earned >= shift.top10:
        return 2
    return 1 if earned >= shift.median else 0


def rank_among(earned: float, shift: Shift) -> int:
    """Rank among the real drivers: 1 + number of drivers with more money."""
    return 1 + sum(1 for r in shift.ranking if r > earned)


def evaluate(shift: Shift, p: Params) -> Result:
    """Play a shift and grade it.

    Args:
        shift: The shift.
        p: Bot settings.

    Returns:
        The graded result.
    """
    earned = play_shift(shift, p)
    return Result(shift.id, earned, shift.median, shift.top10, shift.ghost,
                  medal_for(earned, shift), rank_among(earned, shift), len(shift.ranking))


def summarize(results: list[Result]) -> dict[str, float]:
    """Share of shifts with at least bronze, silver, gold and legend.

    Args:
        results: Results of one run.

    Returns:
        Shares 0..1 keyed by medal name.
    """
    n = max(len(results), 1)
    return {name: sum(r.medal >= m for r in results) / n
            for m, name in enumerate(MEDAL_NAMES) if m > 0}


def format_table(p: Params, results: list[Result]) -> str:
    """Render one run as a text table plus the summary line.

    Args:
        p: Bot settings of the run.
        results: Results of the run.

    Returns:
        Multi-line text.
    """
    lines = [f"== diff={p.diff} strategy={p.strategy} lag={p.lag:g}",
             f"{'shift':<12}{'bot EUR':>9}{'median':>9}{'top10':>9}{'ghost':>9}  {'medal':<7}rank"]
    for r in results:
        lines.append(f"{r.shift_id:<12}{r.earned:>9.2f}{r.median:>9.2f}{r.top10:>9.2f}"
                     f"{r.ghost:>9.2f}  {MEDAL_NAMES[r.medal]:<7}{r.rank}/{r.n_drivers}")
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
    ap.add_argument("--strategy", default="value,nearest")
    ap.add_argument("--lag", default="120,200,300", help="reaction lag, game s")
    ap.add_argument("--diff", default="easy,normal,hard")
    ap.add_argument("--shifts", default="", help="campaign indices, default all")
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
    shifts = load_shifts(args.data)
    if args.shifts:
        shifts = [shifts[i] for i in parse_list(args.shifts, int)]
    runs = []
    for diff, strategy, lag in product(parse_list(args.diff, str), parse_list(args.strategy, str),
                                       parse_list(args.lag, float)):
        if diff not in DIFF_K or strategy not in STRATEGIES:
            raise SystemExit(f"unknown diff/strategy: {diff}/{strategy}")
        p = Params(diff, strategy, lag)
        results = [evaluate(s, p) for s in shifts]
        print(format_table(p, results))
        runs.append({"params": asdict(p), "results": [asdict(r) for r in results],
                     "summary": summarize(results)})
    if args.json:
        args.json.write_text(json.dumps(runs, sort_keys=True, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
