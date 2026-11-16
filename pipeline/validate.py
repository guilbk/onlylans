"""Validate the game files against the contract: data (section 4), roads (5), built HTML (6).

Units used in the checks: map units of ``unit_m`` metres for ``game_data.json`` coordinates, 2.5 m
units for ``roads.json``, game seconds for times, EUR for money, bytes for file sizes. Every check
is a small pure function that returns a list of violation strings; ``main`` prints the report.
A violation reads ``[rule] where: detail``.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pipeline import geo

EXIT_OK = 0
EXIT_VIOLATIONS = 1

DATA_DEFAULT = Path("game/game_data.json")
ROADS_DEFAULT = Path("game/roads.json")
HTML_DEFAULT = Path("game/index.html")

DATA_VERSION = 1
DATA_MAX_BYTES = 5_000_000  # section 4: "<= 5 MB", counted in decimal megabytes
ROADS_MAX_BYTES = 400_000  # section 5: "<= 400 KB", counted in decimal kilobytes
ROADS_UNIT_M = 2.5
SHIFT_COUNT = 28
SHIFT_S = 7200  # game seconds per shift
RIDE_STEP_S = 15  # seconds between GPS points
HOUR_S = 3600
ORDER_LEN = 12
MIN_RIDE_POINTS = geo.MIN_POINTS
MAX_RIDE_POINTS = geo.MAX_POINTS
SURGE_T0_MIN = 150  # game s
SURGE_T1_MAX = SHIFT_S  # game s
CALL_TYPES = (0, 1, 2)
DIFFICULTY_RANGE = (1, 5)
HOURS_PER_DAY = 24
MEDIAN_TOLERANCE_EUR = 0.005  # half a cent: a producer may round the median to cents
EXACT_TOLERANCE_EUR = 1e-9
TOP10_SHARE = 0.10
MAX_PER_RULE = 8  # violations listed per rule in the report

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
SLOTS = ("am", "lunch", "pm", "night")
SLOT_START_HOUR = {"am": 8, "lunch": 12, "pm": 17, "night": 22}
START_LOCAL_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
TOP_KEYS = frozenset({"version", "unit_m", "bounds", "generated", "shifts"})
SHIFT_FIELDS = {
    "id": "str",
    "name": "str",
    "day": "str",
    "slot": "str",
    "start_local": "str",
    "start_hour": "int",
    "difficulty": "int",
    "nDrivers": "int",
    "orders": "list",
    "taxis": "list",
    "ranking": "list",
    "ghost": "dict",
    "median": "num",
    "top10": "num",
    "speed_by_hour": "list",
    "detour": "num",
    "hot": "list",
    "surges": "list",
}
GHOST_KEYS = frozenset({"taxi", "total", "orders"})
ORDER_KINDS = ("int", "int", "int", "int", "int", "list", "int", "num", "num", "int", "int", "int")
HOT_KEYS = frozenset({"x", "y", "w", "name"})
SURGE_KEYS = frozenset({"x", "y", "r", "t0", "t1", "n", "name"})
ROADS_KEYS = frozenset({"v", "unit_m", "nodes", "edges"})
HTML_PLACEHOLDERS = ("/*__CSS__*/", "<!--__DATA__-->", "<!--__JS__-->")
RULE_RE = re.compile(r"^\[([^\]]+)\]")

Bounds = tuple[int, int, int, int]


def viol(rule: str, where: str, detail: str) -> str:
    """Format one violation.

    Args:
        rule: Short rule name.
        where: Place in the file, e.g. ``shift mon-am order 3``.
        detail: What is wrong.

    Returns:
        The text ``[rule] where: detail``.
    """
    return f"[{rule}] {where}: {detail}"


def is_int(value: Any) -> bool:
    """Tell whether a JSON value is an integer (a bool is not).

    Args:
        value: Parsed JSON value.

    Returns:
        True for ``int`` that is not ``bool``.
    """
    return isinstance(value, int) and not isinstance(value, bool)


def is_num(value: Any) -> bool:
    """Tell whether a JSON value is a number (a bool is not).

    Args:
        value: Parsed JSON value.

    Returns:
        True for ``int`` or ``float`` that is not ``bool``.
    """
    return isinstance(value, int | float) and not isinstance(value, bool)


def kind_ok(value: Any, kind: str) -> bool:
    """Check a value against a kind name.

    Args:
        value: Parsed JSON value.
        kind: One of ``str``, ``int``, ``num``, ``list``, ``dict``.

    Returns:
        True if the value has that kind.
    """
    if kind == "int":
        return is_int(value)
    if kind == "num":
        return is_num(value)
    if kind == "str":
        return isinstance(value, str)
    if kind == "list":
        return isinstance(value, list)
    return isinstance(value, dict)


def in_bounds(x: float, y: float, bounds: Bounds) -> bool:
    """Tell whether a point lies inside the bounds, edges included.

    Args:
        x: East coordinate, map units.
        y: South coordinate, map units.
        bounds: ``(x0, y0, x1, y1)`` in map units.

    Returns:
        True if ``x0 <= x <= x1`` and ``y0 <= y <= y1``.
    """
    return bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]


def expected_shift_ids() -> list[str]:
    """List the 28 shift ids in campaign order.

    Returns:
        ``mon-am, mon-lunch, mon-pm, mon-night, tue-am, ...``.
    """
    return [f"{day}-{slot}" for day in DAYS for slot in SLOTS]


def check_top_level(data: Any) -> list[str]:
    """Check the top-level keys and header values of ``game_data.json``.

    Args:
        data: Parsed JSON document.

    Returns:
        Violations of the top-level contract (section 4).
    """
    if not isinstance(data, dict):
        return [viol("top", "document", "is not a JSON object")]
    out: list[str] = []
    if set(data) != TOP_KEYS:
        out.append(viol("top", "keys", f"expected {sorted(TOP_KEYS)}, got {sorted(data)}"))
    if data.get("version") != DATA_VERSION or not is_int(data.get("version")):
        out.append(viol("top", "version", f"must be the integer {DATA_VERSION}"))
    unit = data.get("unit_m")
    if not is_int(unit) or unit <= 0:
        out.append(viol("top", "unit_m", "must be a positive integer (metres per unit)"))
    elif data.get("bounds") != [0, 0, geo.MAP_W_M / unit, geo.MAP_H_M / unit]:
        out.append(
            viol("top", "bounds", f"must be [0, 0, W/{unit}, H/{unit}], got {data.get('bounds')}")
        )
    if not isinstance(data.get("generated"), str):
        out.append(viol("top", "generated", "must be a string"))
    if not isinstance(data.get("shifts"), list):
        out.append(viol("top", "shifts", "must be an array"))
    return out


def check_shift_ids(shifts: Sequence[Any]) -> list[str]:
    """Check that there are 28 shifts with the expected ids in order.

    Args:
        shifts: The ``shifts`` array.

    Returns:
        Violations of the shift count and id order.
    """
    ids = [s.get("id") if isinstance(s, dict) else None for s in shifts]
    expected = expected_shift_ids()
    if len(ids) != SHIFT_COUNT:
        return [viol("shift-ids", "shifts", f"expected {SHIFT_COUNT} shifts, got {len(ids)}")]
    return [
        viol("shift-ids", f"shift #{i}", f"expected id {want!r}, got {got!r}")
        for i, (got, want) in enumerate(zip(ids, expected, strict=True))
        if got != want
    ]


def check_shift_fields(shift: dict[str, Any]) -> list[str]:
    """Check the field set and field types of one shift, and the simple header rules.

    Args:
        shift: One shift object.

    Returns:
        Violations of the field names, types, slot, hour, difficulty and speed table.
    """
    where = f"shift {shift.get('id')}"
    out: list[str] = []
    missing = sorted(set(SHIFT_FIELDS) - set(shift))
    extra = sorted(set(shift) - set(SHIFT_FIELDS))
    if missing or extra:
        out.append(viol("shift-fields", where, f"missing {missing}, unexpected {extra}"))
    for name, kind in SHIFT_FIELDS.items():
        if name in shift and not kind_ok(shift[name], kind):
            out.append(viol("shift-types", where, f"{name} must be {kind}"))
    return out + check_shift_values(shift, where)


def check_shift_values(shift: dict[str, Any], where: str) -> list[str]:
    """Check value ranges of the header fields (only those with the right type).

    Args:
        shift: One shift object.
        where: Location text for the messages.

    Returns:
        Violations of slot, start hour, difficulty, counts and the speed table.
    """
    out: list[str] = []
    ok = {name: kind_ok(shift.get(name), kind) for name, kind in SHIFT_FIELDS.items()}
    if ok["slot"] and shift["slot"] not in SLOTS:
        out.append(viol("shift-values", where, f"slot {shift['slot']!r} not in {SLOTS}"))
    if ok["start_local"] and not START_LOCAL_RE.match(shift["start_local"]):
        out.append(viol("shift-values", where, "start_local must be 'YYYY-MM-DD HH:MM'"))
    if ok["difficulty"] and not DIFFICULTY_RANGE[0] <= shift["difficulty"] <= DIFFICULTY_RANGE[1]:
        out.append(viol("shift-values", where, f"difficulty {shift['difficulty']} not in 1..5"))
    if ok["start_hour"] and not 0 <= shift["start_hour"] < HOURS_PER_DAY:
        out.append(viol("shift-values", where, f"start_hour {shift['start_hour']} not in 0..23"))
    if ok["speed_by_hour"]:
        speeds = shift["speed_by_hour"]
        if len(speeds) != HOURS_PER_DAY or not all(is_num(v) for v in speeds):
            out.append(viol("shift-values", where, "speed_by_hour needs 24 numbers (km/h)"))
    return out


def check_order_shape(order: Any, where: str = "order") -> list[str]:
    """Check that an order array has 12 fields of the right kinds.

    Args:
        order: One order array.
        where: Location text for the messages.

    Returns:
        Violations of the arity and the field kinds; empty if the order is well-formed.
    """
    if not isinstance(order, list) or len(order) != ORDER_LEN:
        size = len(order) if isinstance(order, list) else "not an array"
        return [viol("order-arity", where, f"needs {ORDER_LEN} fields, got {size}")]
    out = [
        viol("order-types", where, f"field {i} must be {kind}")
        for i, kind in enumerate(ORDER_KINDS)
        if not kind_ok(order[i], kind)
    ]
    pts = order[5]
    if isinstance(pts, list) and not all(is_int(v) for v in pts):
        out.append(viol("order-types", where, "pts must hold integers only"))
    return out


def check_order_units(
    order: list[Any], bounds: Bounds, taxi_count: int, where: str = "order"
) -> list[str]:
    """Check the ranges of one well-formed order.

    Args:
        order: Order array ``[t, x0, y0, x1, y1, pts, d, km, fare, c, stand, taxi]``.
        bounds: Map bounds in map units.
        taxi_count: Number of real drivers of the shift.
        where: Location text for the messages.

    Returns:
        Violations of ``t`` (game s), pickup and drop-off bounds, ``km``, ``c``, ``stand``,
        ``taxi``.
    """
    out: list[str] = []
    if not 0 <= order[0] < SHIFT_S:
        out.append(viol("order-t", where, f"t={order[0]} must be in 0..{SHIFT_S - 1} game s"))
    for label, (x, y) in (("pickup", order[1:3]), ("drop-off", order[3:5])):
        if not in_bounds(x, y, bounds):
            out.append(viol("order-bounds", where, f"{label} ({x}, {y}) outside {list(bounds)}"))
    if not order[7] > 0:
        out.append(viol("order-km", where, f"km={order[7]} must be positive"))
    if order[9] not in CALL_TYPES:
        out.append(viol("order-call", where, f"c={order[9]} must be 0, 1 or 2"))
    if order[10] < 0:
        out.append(viol("order-stand", where, f"stand={order[10]} must be >= 0"))
    if not 0 <= order[11] < taxi_count:
        out.append(viol("order-taxi", where, f"taxi={order[11]} not in 0..{taxi_count - 1}"))
    return out


def check_order_path(order: list[Any], bounds: Bounds, where: str = "order") -> list[str]:
    """Check the delta path of one well-formed order.

    Args:
        order: Order array (``pts`` are integer deltas in map units).
        bounds: Map bounds in map units.
        where: Location text for the messages.

    Returns:
        Violations of the point count, ``d = 15 * (n - 1)`` s, bounds of every point and the
        reconstructed end point against ``(x1, y1)``.
    """
    pts = order[5]
    if len(pts) % 2:
        return [viol("order-pts", where, "pts has an odd length")]
    n = len(pts) // 2 + 1
    out: list[str] = []
    if not MIN_RIDE_POINTS <= n <= MAX_RIDE_POINTS:
        out.append(
            viol("order-pts", where, f"{n} points, expected {MIN_RIDE_POINTS}..{MAX_RIDE_POINTS}")
        )
    if order[6] != RIDE_STEP_S * (n - 1):
        out.append(viol("order-d", where, f"d={order[6]} s, expected {RIDE_STEP_S * (n - 1)} s"))
    x, y = order[1], order[2]
    for i in range(0, len(pts), 2):
        x, y = x + pts[i], y + pts[i + 1]
        if not in_bounds(x, y, bounds):
            out.append(viol("order-bounds", where, f"path point {i // 2 + 1} ({x}, {y}) outside"))
            break
    if (x, y) != (order[3], order[4]):
        out.append(
            viol("order-pts", where, f"path ends at ({x}, {y}), x1/y1 is ({order[3]}, {order[4]})")
        )
    return out


def check_order_fare(order: list[Any], start_hour: int, where: str = "order") -> list[str]:
    """Check the fare of one well-formed order against section 3.

    Args:
        order: Order array; ``t`` is game s, ``km`` kilometres, ``fare`` EUR.
        start_hour: Local hour (0..23) at which the shift starts.
        where: Location text for the messages.

    Returns:
        A violation if ``fare != fare(km, night)`` for the local pickup hour.
    """
    hour = (start_hour + order[0] // HOUR_S) % HOURS_PER_DAY
    want = geo.fare(order[7], geo.night_hour(hour))
    if not math.isclose(order[8], want, abs_tol=EXACT_TOLERANCE_EUR):
        return [
            viol("order-fare", where, f"fare={order[8]} EUR, expected {want} EUR for km={order[7]}")
        ]
    return []


def check_orders(shift: dict[str, Any], bounds: Bounds) -> tuple[list[str], bool]:
    """Run every per-order check on a shift, and check that orders are sorted by ``t``.

    Args:
        shift: One shift object whose ``orders`` is a list.
        bounds: Map bounds in map units.

    Returns:
        Violations (each names the shift id and the order index), and whether every order
        has a well-formed shape (so that deeper checks on the orders are safe).
    """
    out: list[str] = []
    taxi_count = len(shift["taxis"]) if isinstance(shift.get("taxis"), list) else 0
    start_hour = shift["start_hour"] if is_int(shift.get("start_hour")) else 0
    shapes_ok = True
    last_t = -1
    for i, order in enumerate(shift["orders"]):
        where = f"shift {shift.get('id')} order {i}"
        found = check_order_shape(order, where)
        if found:
            shapes_ok = False
            out += found
            continue
        out += check_order_units(order, bounds, taxi_count, where)
        out += check_order_path(order, bounds, where)
        out += check_order_fare(order, start_hour, where)
        if order[0] < last_t:
            out.append(viol("order-sorted", where, f"t={order[0]} comes after t={last_t}"))
        last_t = order[0]
    return out, shapes_ok


def check_ranking_order(shift: dict[str, Any]) -> list[str]:
    """Check that ranking and taxis are parallel and sorted.

    Args:
        shift: One shift object with list ``ranking`` and ``taxis`` (EUR, TAXI_ID).

    Returns:
        Violations of the lengths, the descending order and the tie order by taxi id.
    """
    where = f"shift {shift.get('id')}"
    ranking, taxis = shift["ranking"], shift["taxis"]
    n = shift.get("nDrivers")
    out: list[str] = []
    if not len(ranking) == len(taxis) == n:
        out.append(
            viol("ranking", where, f"nDrivers={n}, ranking {len(ranking)}, taxis {len(taxis)}")
        )
    if not all(is_num(v) for v in ranking) or not all(is_int(v) for v in taxis):
        return out + [viol("ranking", where, "ranking must be numbers and taxis integers")]
    cents = [round(v * 100) for v in ranking]
    for i in range(1, min(len(cents), len(taxis))):
        if cents[i] > cents[i - 1] or (cents[i] == cents[i - 1] and taxis[i] <= taxis[i - 1]):
            out.append(viol("ranking", where, f"position {i} breaks 'total desc, ties by TAXI_ID'"))
            break
    return out


def check_ranking_totals(shift: dict[str, Any]) -> list[str]:
    """Check that each driver's total equals the sum of that driver's order fares.

    Args:
        shift: One shift object whose orders are well-formed.

    Returns:
        Violations where ``ranking[i]`` differs from the fares of taxi ``i`` (compared in cents).
    """
    where = f"shift {shift.get('id')}"
    sums: Counter[int] = Counter()
    for order in shift["orders"]:
        sums[order[11]] += round(order[8] * 100)
    out = [
        viol(
            "ranking-total",
            where,
            f"taxi index {i}: ranking {value} EUR, orders sum {sums[i] / 100} EUR",
        )
        for i, value in enumerate(shift["ranking"])
        if sums[i] != round(value * 100)
    ]
    extra = sorted(set(sums) - set(range(len(shift["ranking"]))))
    if extra:
        out.append(
            viol("ranking-total", where, f"orders use taxi indices without ranking: {extra}")
        )
    return out


def check_ghost(shift: dict[str, Any]) -> list[str]:
    """Check the ghost against the ranking and the orders.

    Args:
        shift: One shift object with non-empty ranking and well-formed orders.

    Returns:
        Violations: ghost keys, ``taxi == 0``, ``total == ranking[0]``, order indices.
    """
    where = f"shift {shift.get('id')}"
    ghost = shift["ghost"]
    if set(ghost) != GHOST_KEYS:
        return [viol("ghost", where, f"keys must be {sorted(GHOST_KEYS)}")]
    out: list[str] = []
    if ghost["taxi"] != 0:
        out.append(viol("ghost", where, f"taxi={ghost['taxi']}, the best driver is index 0"))
    if not is_num(ghost["total"]) or not math.isclose(
        ghost["total"], shift["ranking"][0], abs_tol=EXACT_TOLERANCE_EUR
    ):
        out.append(
            viol(
                "ghost", where, f"total={ghost['total']} EUR, ranking[0]={shift['ranking'][0]} EUR"
            )
        )
    mine = [i for i, o in enumerate(shift["orders"]) if o[11] == 0]
    if ghost["orders"] != mine:
        out.append(viol("ghost", where, "orders must be the ascending indices of taxi 0's orders"))
    return out


def check_summary(shift: dict[str, Any]) -> list[str]:
    """Check ``median`` and ``top10`` against the ranking.

    Args:
        shift: One shift object with non-empty numeric ranking (EUR).

    Returns:
        Violations of the median (half a cent tolerance) and of the 10 % mark.
    """
    where = f"shift {shift.get('id')}"
    ranking = shift["ranking"]
    out: list[str] = []
    median = statistics.median(ranking)
    if not is_num(shift["median"]) or abs(shift["median"] - median) > MEDIAN_TOLERANCE_EUR:
        out.append(viol("median", where, f"median={shift['median']} EUR, expected {median} EUR"))
    mark = ranking[max(0, math.ceil(TOP10_SHARE * len(ranking)) - 1)]
    if not is_num(shift["top10"]) or not math.isclose(
        shift["top10"], mark, abs_tol=EXACT_TOLERANCE_EUR
    ):
        out.append(viol("top10", where, f"top10={shift['top10']} EUR, expected {mark} EUR"))
    return out


def check_places(shift: dict[str, Any], bounds: Bounds) -> list[str]:
    """Check ``hot`` and ``surges`` entries.

    Args:
        shift: One shift object whose ``hot`` and ``surges`` are lists.
        bounds: Map bounds in map units.

    Returns:
        Violations of keys, kinds, bounds, ``w`` in 0..1 and ``150 <= t0 < t1 <= 7200`` game s.
    """
    where = f"shift {shift.get('id')}"
    out: list[str] = []
    for i, hot in enumerate(shift["hot"]):
        pos = f"{where} hot {i}"
        if not isinstance(hot, dict) or set(hot) != HOT_KEYS:
            out.append(viol("hot", pos, f"keys must be {sorted(HOT_KEYS)}"))
        elif not (is_int(hot["x"]) and is_int(hot["y"]) and in_bounds(hot["x"], hot["y"], bounds)):
            out.append(viol("hot", pos, "x, y must be integers inside the bounds"))
        elif not (is_num(hot["w"]) and 0 <= hot["w"] <= 1 and isinstance(hot["name"], str)):
            out.append(viol("hot", pos, "w must be 0..1 and name a string"))
    for i, surge in enumerate(shift["surges"]):
        out += check_surge(surge, f"{where} surge {i}", bounds)
    return out


def check_surge(surge: Any, where: str, bounds: Bounds) -> list[str]:
    """Check one demand wave.

    Args:
        surge: One ``surges`` entry (``x, y, r`` map units; ``t0, t1`` game s; ``n`` pickups).
        where: Location text for the messages.
        bounds: Map bounds in map units.

    Returns:
        Violations of keys, integer kinds, centre in bounds, ``t0 >= 150``, ``t1 <= 7200`` and
        ``t0 < t1`` (game s).
    """
    if not isinstance(surge, dict) or set(surge) != SURGE_KEYS:
        return [viol("surge", where, f"keys must be {sorted(SURGE_KEYS)}")]
    if not all(is_int(surge[k]) for k in ("x", "y", "r", "t0", "t1", "n")):
        return [viol("surge", where, "x, y, r, t0, t1, n must be integers")]
    out: list[str] = []
    if not in_bounds(surge["x"], surge["y"], bounds) or surge["r"] <= 0:
        out.append(viol("surge", where, "centre must be inside the bounds and r > 0"))
    if surge["t0"] < SURGE_T0_MIN or surge["t1"] > SURGE_T1_MAX or surge["t0"] >= surge["t1"]:
        out.append(
            viol(
                "surge-time",
                where,
                f"t0={surge['t0']}, t1={surge['t1']} game s, need 150 <= t0 < t1 <= 7200",
            )
        )
    return out


def check_shift(shift: Any, bounds: Bounds) -> list[str]:
    """Run all checks on one shift.

    Args:
        shift: One entry of ``shifts``.
        bounds: Map bounds in map units.

    Returns:
        All violations of that shift; the deeper checks run only if the field kinds are right.
    """
    if not isinstance(shift, dict):
        return [viol("shift-types", "shift", "must be an object")]
    out = check_shift_fields(shift)
    if any(not kind_ok(shift.get(n), k) for n, k in SHIFT_FIELDS.items()):
        return out
    found, shapes_ok = check_orders(shift, bounds)
    out += found + check_places(shift, bounds)
    where = f"shift {shift.get('id')}"
    if not shift["orders"] or not shift["ranking"]:
        return [*out, viol("shift-values", where, "has no orders or no ranking")]
    out += check_ranking_order(shift)
    if shapes_ok and all(is_num(v) for v in shift["ranking"]):
        out += check_ranking_totals(shift) + check_ghost(shift) + check_summary(shift)
    return out


def validate_data(data: Any) -> list[str]:
    """Validate a parsed ``game_data.json`` against section 4.

    Args:
        data: Parsed JSON document.

    Returns:
        All violations; empty if the document follows the contract.
    """
    out = check_top_level(data)
    if out or not isinstance(data["shifts"], list):
        return out
    unit = data["unit_m"]
    bounds: Bounds = (0, 0, geo.MAP_W_M // unit, geo.MAP_H_M // unit)
    out += check_shift_ids(data["shifts"])
    for shift in data["shifts"]:
        out += check_shift(shift, bounds)
    return out


def check_file_size(size: int, limit: int, label: str) -> list[str]:
    """Check a file size against its limit.

    Args:
        size: File size in bytes.
        limit: Largest allowed size in bytes.
        label: File name for the message.

    Returns:
        A violation if ``size > limit``.
    """
    if size > limit:
        return [viol("size", label, f"{size} bytes exceeds the limit of {limit} bytes")]
    return []


def check_roads_header(roads: Any) -> list[str]:
    """Check the top-level shape of ``roads.json`` (section 5).

    Args:
        roads: Parsed JSON document.

    Returns:
        Violations of the keys, ``v``, ``unit_m`` (2.5 m), and the node and edge arrays.
    """
    if not isinstance(roads, dict) or set(roads) != ROADS_KEYS:
        return [
            viol("roads-header", "document", f"must be an object with keys {sorted(ROADS_KEYS)}")
        ]
    out: list[str] = []
    if roads["v"] != 1 or not is_int(roads["v"]):
        out.append(viol("roads-header", "v", "must be the integer 1"))
    if roads["unit_m"] != ROADS_UNIT_M or not is_num(roads["unit_m"]):
        out.append(viol("roads-header", "unit_m", f"must be {ROADS_UNIT_M} (metres per unit)"))
    nodes, edges = roads["nodes"], roads["edges"]
    if not isinstance(nodes, list) or not all(is_int(v) for v in nodes) or len(nodes) % 2:
        out.append(viol("roads-header", "nodes", "must be a flat integer array of x, y pairs"))
    if not isinstance(edges, list):
        out.append(viol("roads-header", "edges", "must be an array"))
    return out


def roads_bounds() -> Bounds:
    """Give the map bounds in roads units (2.5 m).

    Returns:
        ``(0, 0, W, H)`` in 2.5 m units.
    """
    return (0, 0, int(geo.MAP_W_M / ROADS_UNIT_M), int(geo.MAP_H_M / ROADS_UNIT_M))


def check_roads_nodes(nodes: Sequence[int]) -> list[str]:
    """Check node coordinates and the (y, x) ordering.

    Args:
        nodes: Flat ``[x0, y0, x1, y1, ...]`` in 2.5 m units.

    Returns:
        Violations of the bounds and of the sort order by ``(y, x)``.
    """
    bounds = roads_bounds()
    pairs = list(zip(nodes[0::2], nodes[1::2], strict=True))
    out = [
        viol("roads-bounds", f"node {i}", f"({x}, {y}) outside {list(bounds)}")
        for i, (x, y) in enumerate(pairs)
        if not in_bounds(x, y, bounds)
    ]
    keys = [(y, x) for x, y in pairs]
    if keys != sorted(keys):
        out.append(viol("roads-sorted", "nodes", "must be sorted by (y, x)"))
    return out


def check_roads_edges(edges: Sequence[Any], node_count: int) -> list[str]:
    """Check edge shape, node indices, interior points and the (a, b) ordering.

    Args:
        edges: ``[[a, b, [x, y, ...]], ...]``.
        node_count: Number of nodes.

    Returns:
        Violations of the edge arity, index ranges, interior points in bounds and sort order.
    """
    bounds = roads_bounds()
    out: list[str] = []
    for i, edge in enumerate(edges):
        where = f"edge {i}"
        if not (isinstance(edge, list) and len(edge) == 3 and isinstance(edge[2], list)):
            out.append(viol("roads-edge", where, "must be [a, b, [x, y, ...]]"))
            continue
        a, b, inner = edge
        if not (is_int(a) and is_int(b) and 0 <= a < node_count and 0 <= b < node_count):
            out.append(viol("roads-index", where, f"a={a}, b={b} not in 0..{node_count - 1}"))
        if len(inner) % 2 or not all(is_int(v) for v in inner):
            out.append(viol("roads-edge", where, "interior points must be an even integer array"))
        elif any(
            not in_bounds(x, y, bounds) for x, y in zip(inner[0::2], inner[1::2], strict=True)
        ):
            out.append(viol("roads-bounds", where, "interior point outside the map"))
    keys = [(e[0], e[1]) for e in edges if isinstance(e, list) and len(e) == 3]
    if keys != sorted(keys):
        out.append(viol("roads-sorted", "edges", "must be sorted by (a, b)"))
    return out


def count_components(node_count: int, edges: Sequence[Sequence[Any]]) -> int:
    """Count connected components of the undirected graph, isolated nodes included.

    Args:
        node_count: Number of nodes.
        edges: Edges whose first two items are valid node indices.

    Returns:
        Number of components (0 for an empty graph).
    """
    parent = list(range(node_count))

    def find(i: int) -> int:
        """Return the root of node ``i`` with path halving."""
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for edge in edges:
        parent[find(edge[0])] = find(edge[1])
    return len({find(i) for i in range(node_count)})


def validate_roads(roads: Any) -> list[str]:
    """Validate a parsed ``roads.json`` against section 5.

    Args:
        roads: Parsed JSON document.

    Returns:
        All violations; empty if the document follows the contract.
    """
    out = check_roads_header(roads)
    if out:
        return out
    nodes, edges = roads["nodes"], roads["edges"]
    count = len(nodes) // 2
    out += check_roads_nodes(nodes) + check_roads_edges(edges, count)
    if any(o.startswith(("[roads-index]", "[roads-edge]")) for o in out):
        return out
    components = count_components(count, edges)
    if components != 1:
        out.append(viol("roads-connected", "graph", f"{components} components, expected 1"))
    return out


def extract_script(html: str, element_id: str) -> str | None:
    """Cut the text of ``<script ... id="element_id">...</script>`` out of the HTML.

    Args:
        html: Built HTML.
        element_id: The element's ``id``.

    Returns:
        The element's content, or None if there is no such script element.
    """
    pattern = rf'<script[^>]*\bid="{re.escape(element_id)}"[^>]*>(.*?)</script'
    found = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
    return found.group(1) if found else None


def check_json_block(html: str, element_id: str, required: bool) -> tuple[list[str], Any]:
    """Check one inline JSON script element.

    Args:
        html: Built HTML.
        element_id: ``game-data`` or ``roads-data``.
        required: Whether a missing element is a violation.

    Returns:
        Violations, and the parsed JSON (None if absent or invalid).
    """
    text = extract_script(html, element_id)
    if text is None:
        return (
            [viol("html-data", element_id, "script element not found")] if required else []
        ), None
    out: list[str] = []
    if "</" in text:
        out.append(viol("html-escape", element_id, "contains an unescaped '</' (must be '<\\/')"))
    try:
        return out, json.loads(text)
    except ValueError as err:
        out.append(
            viol("html-data", element_id, f"content is not valid JSON ({err}); '</script' inside?")
        )
        return out, None


def check_html(html: str, data: Any = None) -> list[str]:
    """Validate the built HTML against section 6.

    Args:
        html: Built HTML text.
        data: Parsed ``game_data.json`` to compare with the inline copy; None skips the comparison.

    Returns:
        Violations: placeholders left, missing or invalid ``#game-data``, ``</script`` inside data,
        unbalanced script tags, inline data differing from ``data``.
    """
    out = [
        viol("html-placeholder", "html", f"{ph} is still in the file")
        for ph in HTML_PLACEHOLDERS
        if ph in html
    ]
    found, inline = check_json_block(html, "game-data", True)
    out += found
    out += check_json_block(html, "roads-data", False)[0]
    lowered = html.lower()
    opens, closes = lowered.count("<script"), lowered.count("</script")
    if opens != closes:
        out.append(viol("html-script", "html", f"{opens} '<script' but {closes} '</script'"))
    if data is not None and inline is not None and inline != data:
        out.append(viol("html-data", "game-data", "inline copy differs from the --data file"))
    return out


def load_json(path: Path) -> tuple[Any, list[str]]:
    """Read and parse a JSON file.

    Args:
        path: File path.

    Returns:
        The parsed document (None on failure) and the violations that explain a failure.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8")), []
    except (OSError, ValueError) as err:
        return None, [viol("file", str(path), f"cannot read as JSON: {err}")]


def summarize(violations: Sequence[str], limit: int = MAX_PER_RULE) -> list[str]:
    """Group violations by rule and cut the list per rule.

    Args:
        violations: Violation strings.
        limit: Most lines to keep for each rule.

    Returns:
        Report lines; a rule over the limit ends with a ``... and N more`` line.
    """
    seen: Counter[str] = Counter()
    lines: list[str] = []
    total = Counter(RULE_RE.match(v).group(1) if RULE_RE.match(v) else "?" for v in violations)
    for v in violations:
        match = RULE_RE.match(v)
        rule = match.group(1) if match else "?"
        seen[rule] += 1
        if seen[rule] <= limit:
            lines.append(v)
        elif seen[rule] == limit + 1:
            lines.append(f"[{rule}] ... and {total[rule] - limit} more")
    return lines


def run_data(path: Path) -> tuple[Any, list[str]]:
    """Validate the data file, including its size.

    Args:
        path: Path of ``game_data.json``.

    Returns:
        The parsed document (for the HTML comparison) and the violations.
    """
    data, out = load_json(path)
    if out:
        return None, out
    out = check_file_size(path.stat().st_size, DATA_MAX_BYTES, str(path)) + validate_data(data)
    return data, out


def run_roads(path: Path) -> list[str]:
    """Validate the roads file, including its size.

    Args:
        path: Path of ``roads.json``.

    Returns:
        The violations.
    """
    roads, out = load_json(path)
    if out:
        return out
    return check_file_size(path.stat().st_size, ROADS_MAX_BYTES, str(path)) + validate_roads(roads)


def run_html(path: Path, data: Any) -> list[str]:
    """Validate the built HTML file.

    Args:
        path: Path of the built HTML.
        data: Parsed game data to compare with, or None.

    Returns:
        The violations.
    """
    try:
        html = path.read_text(encoding="utf-8")
    except (OSError, ValueError) as err:
        return [viol("file", str(path), f"cannot read: {err}")]
    return check_html(html, data)


def run_optional(
    given: Path | None, default: Path, data: Any, is_html: bool
) -> tuple[Path, list[str] | None]:
    """Run the roads or HTML check; a missing default file is skipped, a missing given one fails.

    Args:
        given: Path from the command line, or None.
        default: Path used when ``given`` is None.
        data: Parsed game data for the HTML comparison.
        is_html: True to check HTML, False to check roads.

    Returns:
        The path used, and the violations (None if the check was skipped).
    """
    path = given if given is not None else default
    if not path.is_file():
        if given is None:
            return path, None
        return path, [viol("file", str(path), "not found")]
    return path, run_html(path, data) if is_html else run_roads(path)


def format_report(results: Sequence[tuple[str, list[str] | None]]) -> list[str]:
    """Render the report lines.

    Args:
        results: ``(file name, violations)`` per file; None means the file was skipped.

    Returns:
        Lines: one per file, its listed violations, and a final ``RESULT`` line.
    """
    lines: list[str] = []
    total = 0
    for name, found in results:
        if found is None:
            lines.append(f"{name}: not found, skipped")
            continue
        total += len(found)
        lines.append(f"{name}: " + ("OK" if not found else f"{len(found)} violation(s)"))
        lines += [f"  {line}" for line in summarize(found)]
    lines.append("RESULT: OK" if total == 0 else f"RESULT: {total} violation(s)")
    return lines


def main(argv: list[str] | None = None) -> int:
    """Command line entry point.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        0 if the files follow the contract, 1 if there is any violation.
    """
    ap = argparse.ArgumentParser(description="Validate game files against CONTRACT sections 4-6")
    ap.add_argument("--data", type=Path, default=DATA_DEFAULT, help="game_data.json")
    ap.add_argument("--roads", type=Path, default=None, help=f"roads.json ({ROADS_DEFAULT})")
    ap.add_argument("--html", type=Path, default=None, help=f"built game HTML ({HTML_DEFAULT})")
    args = ap.parse_args(argv)
    if args.data.is_file():
        data, found = run_data(args.data)
    else:
        data, found = None, [viol("file", str(args.data), "not found")]
    roads_path, roads_found = run_optional(args.roads, ROADS_DEFAULT, data, False)
    html_path, html_found = run_optional(args.html, HTML_DEFAULT, data, True)
    lines = format_report(
        [(str(args.data), found), (str(roads_path), roads_found), (str(html_path), html_found)]
    )
    print("\n".join(lines))
    return EXIT_OK if lines[-1] == "RESULT: OK" else EXIT_VIOLATIONS


if __name__ == "__main__":
    raise SystemExit(main())
