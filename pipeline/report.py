"""Data report for the jury and the demo: docs/STATS.md and three PNG charts.

CLI: ``python -m pipeline.report [--week data/work/week.csv] [--data game/game_data.json]
[--out docs]``.

Everything is computed from the real week (``week.csv``) and from ``game_data.json``. Units: money
in EUR (kept as integer cents while summing), distances in km, map coordinates in metres of the
CONTRACT section 3 frame, hours are Europe/Lisbon local hours of the pickup. Text of the report is
Ukrainian; text inside the charts is ASCII (the bundled Pillow font has no Cyrillic), which keeps
the output identical on every machine.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import gaussian_filter

from pipeline import geo, places, shifts

DEFAULT_WEEK = Path("data/work/week.csv")
DEFAULT_DATA = Path("game/game_data.json")
DEFAULT_OUT = Path("docs")
STATS_NAME = "STATS.md"
IMG_DIR = "img"
HOURS_PNG = "hours.png"
SHIFTS_PNG = "shifts.png"
HEATMAP_PNG = "heatmap.png"

HOURS_PER_DAY = 24
CENTS_PER_EUR = 100
M_PER_KM = 1000.0
PERCENT = 100.0
TOP_HOURS = 5  # busiest hours listed in the demand section
CALL_LETTERS = ("A", "B", "C")
CALL_TITLES = ("A: виклик диспетчера", "B: стоянка", "C: з вулиці")
TOP_N = 10

# Filter rules in the order geo.trip_ok checks them; the first failed rule is reported.
RULE_BAD_JSON = "bad_json"
RULE_POINTS = "points"
RULE_BOUNDS = "bounds"
RULE_STEP = "step"
RULE_LENGTH = "length"
RULE_STRAIGHT = "straight"
RULE_MISSING = "missing"
RULE_ORDER = (
    RULE_MISSING,
    RULE_BAD_JSON,
    RULE_POINTS,
    RULE_BOUNDS,
    RULE_STEP,
    RULE_LENGTH,
    RULE_STRAIGHT,
)
MIN_PATH_TXT = str(geo.MIN_PATH_KM).replace(".", ",")  # decimal comma, as in the text
MIN_STRAIGHT_TXT = str(geo.MIN_STRAIGHT_KM).replace(".", ",")
RULE_TEXT = {
    RULE_MISSING: "у GPS-потоці є пропуски (MISSING_DATA)",
    RULE_BAD_JSON: "трек не читається",
    RULE_POINTS: f"менше {geo.MIN_POINTS} або більше {geo.MAX_POINTS} точок (45 с … 60 хв)",
    RULE_BOUNDS: "точка зіпсована або поза рамкою мапи",
    RULE_STEP: f"стрибок між точками понад {geo.MAX_STEP_M:.0f} м за 15 с",
    RULE_LENGTH: f"довжина шляху поза {MIN_PATH_TXT}…{geo.MAX_PATH_KM:.0f} км",
    RULE_STRAIGHT: f"по прямій від початку до кінця менше {MIN_STRAIGHT_TXT} км (петля)",
}

# Dark theme (CONTRACT section 14).
BG = (7, 11, 20)
PANEL = (14, 20, 36)
TEXT = (232, 238, 252)
MUTED = (138, 150, 179)
GHOST = (180, 140, 255)
MINT = (61, 245, 176)
AMBER = (255, 200, 87)
CYAN = (94, 230, 255)
IMG_W = 720
FONT_PX = 22
FONT_SMALL_PX = 18
MARGIN = 24

HOURS_H = 464
HOURS_PLOT_TOP = 70
HOURS_PLOT_BOTTOM = 56
HOURS_LABEL_STEP = 3
HOURS_TITLE_Y = 14  # chart coordinates, pixels
HOURS_PEAK_Y = 18
HOURS_BAR_INSET = 2  # gap at each side of a bar slot
HOURS_LABEL_GAP = 10  # distance of the hour labels below the axis
HOURS_FOOTER_UP = 28  # footer baseline distance from the bottom edge

SHIFT_LABEL_W = 150
SHIFT_BAR_H = 9
SHIFT_ROW_GAP = 8
SHIFT_HEADER_H = 64
SHIFT_TITLE_Y = 12  # chart coordinates, pixels
SHIFT_LEGEND_BOX_Y = (46, 58)  # top and bottom of a legend swatch
SHIFT_LEGEND_BOX_W = 14
SHIFT_LEGEND_TEXT_X = 20  # text offset from the swatch's left edge
SHIFT_LEGEND_TEXT_Y = 41
SHIFT_LEGEND_GAP = 22
SHIFT_VALUE_W = 70  # room at the right for the ghost's value text
SHIFT_TEXT_DY = 2  # text offset below the row's top edge
SHIFT_VALUE_DX = 8  # gap between the ghost bar and its value
SHIFT_SERIES = 3  # bars per shift: ghost, top 10 %, median

HEAT_CELL_M = 100.0
HEAT_SCALE = 4
HEAT_MARK_R = 4  # landmark circle radius, pixels
HEAT_MARK_W = 2  # landmark circle line width, pixels
HEAT_LABEL_DX, HEAT_LABEL_DY = 8, -10  # label offset from the landmark, pixels
SCALE_BAR_M = 5000  # length of the scale bar, metres
SCALE_BAR_W = 3  # scale bar line width, pixels
SCALE_LABEL_UP = 26  # distance of the scale label above the bar, pixels
PALETTE_LEVELS = 256  # entries of the heat palette (uint8 levels)
LEVEL_MAX = 255
RGB_CHANNELS = 3
HEAT_BLUR_CELLS = 1.2
HEAT_LANDMARKS = (
    "Aeroporto",
    "Matosinhos",
    "Foz",
    "Boavista",
    "Aliados",
    "Campanhã",
    "Gaia (Cais)",
    "Hospital São João",
)
HEAT_RAMP = (
    (7, 11, 20),
    (24, 40, 110),
    (61, 130, 230),
    (94, 230, 255),
    (255, 200, 87),
    (255, 255, 255),
)


class StandRow(NamedTuple):
    """One taxi stand: id, trips from it, share of all stand trips, nearest place name."""

    stand: int
    trips: int
    share: float
    name: str


class HotRow(NamedTuple):
    """One hotspot name: shifts where it is hot and the estimated pickups in them."""

    name: str
    shifts: int
    pickups: int


# --------------------------------------------------------------------------------------------
# Filter rules
# --------------------------------------------------------------------------------------------


def valid_point(p: object) -> bool:
    """Tell whether a value is a usable lon/lat point.

    Args:
        p: Any value.

    Returns:
        True if ``p`` is a 2-element list or tuple of finite numbers (degrees).
    """
    if not isinstance(p, list | tuple) or len(p) != 2:
        return False
    return all(
        isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) for v in p
    )


def reject_reason(pts: object) -> str | None:
    """Find the first ``trip_ok`` rule that a lon/lat polyline breaks.

    Mirrors ``geo.trip_ok`` rule by rule and in the same order. Geometry rules (step, length,
    straight) are only evaluated when there are at least two valid in-map points.

    Args:
        pts: Parsed POLYLINE value, expected ``[[lon, lat], ...]`` in degrees.

    Returns:
        The key of the first failed rule (steps in metres, length in km), None if it passes.
    """
    if not isinstance(pts, list):
        return RULE_BAD_JSON
    if not geo.MIN_POINTS <= len(pts) <= geo.MAX_POINTS:
        return RULE_POINTS
    if not all(valid_point(p) and geo.in_map(p[0], p[1]) for p in pts):
        return RULE_BOUNDS
    steps_m = [
        geo.haversine(a[0], a[1], b[0], b[1]) * M_PER_KM for a, b in zip(pts, pts[1:], strict=False)
    ]
    if max(steps_m) > geo.MAX_STEP_M:
        return RULE_STEP
    if not geo.MIN_PATH_KM <= sum(steps_m) / M_PER_KM <= geo.MAX_PATH_KM:
        return RULE_LENGTH
    straight_km = geo.haversine(pts[0][0], pts[0][1], pts[-1][0], pts[-1][1])
    return RULE_STRAIGHT if straight_km < geo.MIN_STRAIGHT_KM else None


def row_reason(row: Mapping[str, str]) -> str | None:
    """Find the reject rule of a week.csv row (missing flag, bad JSON, then the trip rules).

    Args:
        row: CSV row with ``MISSING_DATA`` and ``POLYLINE`` columns.

    Returns:
        The key of the first failed rule, None if the row passes.
    """
    if row["MISSING_DATA"].strip().lower() == "true":
        return RULE_MISSING
    try:
        pts = json.loads(row["POLYLINE"])
    except ValueError:
        return RULE_BAD_JSON
    return reject_reason(pts)


def filter_table(total: int, rejected: Mapping[str, int]) -> list[tuple[str, int, float]]:
    """Tabulate how many rows each filter rule rejected.

    Args:
        total: Number of rows read.
        rejected: Rows rejected first by each rule key.

    Returns:
        ``(rule key, rows rejected first by it, share of all rows in %)`` in rule order.
    """
    return [
        (rule, rejected.get(rule, 0), PERCENT * rejected.get(rule, 0) / total if total else 0.0)
        for rule in RULE_ORDER
    ]


def scan_week(week: Path) -> tuple[list[shifts.Trip], int, Counter[str]]:
    """Read week.csv and sort its rows into valid trips and rejects.

    Args:
        week: Path of ``week.csv``.

    Returns:
        ``(valid trips, number of rows read, rejected rows per rule key)``.
    """
    csv.field_size_limit(sys.maxsize)
    trips: list[shifts.Trip] = []
    rejected: Counter[str] = Counter()
    rows = 0
    with week.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rows += 1
            reason = row_reason(row)
            trip = shifts.parse_row(row) if reason is None else None
            if trip is not None:
                trips.append(trip)
            else:
                rejected[reason or RULE_MISSING] += 1
    return trips, rows, rejected


# --------------------------------------------------------------------------------------------
# Computations (pure)
# --------------------------------------------------------------------------------------------


def trip_cents(trip: shifts.Trip) -> int:
    """Price a trip like the game does.

    Args:
        trip: One valid trip (``km`` kilometres, ``hour`` local pickup hour).

    Returns:
        The game fare in integer EUR cents (same rounding as the ranking).
    """
    return round(geo.fare(round(trip.km, 2), geo.night_hour(trip.hour)) * CENTS_PER_EUR)


def week_totals(trips: Sequence[shifts.Trip]) -> dict[str, float]:
    """Sum up the week.

    Args:
        trips: Valid trips.

    Returns:
        Dict with ``trips`` (count), ``taxis`` (distinct), ``km`` (kilometres) and ``cents``
        (EUR cents, game fare).
    """
    return {
        "trips": len(trips),
        "taxis": len({t.taxi for t in trips}),
        "km": sum(t.km for t in trips),
        "cents": sum(trip_cents(t) for t in trips),
    }


def demand_by_hour(trips: Iterable[shifts.Trip]) -> list[int]:
    """Count trips per local pickup hour.

    Args:
        trips: Valid trips.

    Returns:
        24 counts, index = local hour 0..23.
    """
    counts = [0] * HOURS_PER_DAY
    for t in trips:
        counts[t.hour] += 1
    return counts


def call_mix(trips: Sequence[shifts.Trip]) -> list[dict[str, float]]:
    """Describe each call type A/B/C.

    Args:
        trips: Valid trips.

    Returns:
        One dict per call type with ``trips`` (count), ``share`` (% of all trips), ``km`` (mean
        kilometres) and ``eur`` (mean game fare, EUR).
    """
    out = []
    for call in range(len(CALL_LETTERS)):
        sel = [t for t in trips if t.call == call]
        n = len(sel)
        out.append(
            {
                "trips": n,
                "share": PERCENT * n / len(trips) if trips else 0.0,
                "km": sum(t.km for t in sel) / n if n else 0.0,
                "eur": sum(trip_cents(t) for t in sel) / n / CENTS_PER_EUR if n else 0.0,
            }
        )
    return out


def top_stands(trips: Sequence[shifts.Trip], n: int = TOP_N) -> list[StandRow]:
    """Find the busiest taxi stands.

    Args:
        trips: Valid trips.
        n: How many stands to return.

    Returns:
        Up to ``n`` rows, by trips descending and then stand id; the name is that of the place
        nearest to the median pickup (map metres).
    """
    by_stand: dict[int, list[shifts.Trip]] = defaultdict(list)
    for t in trips:
        if t.stand > 0:
            by_stand[t.stand].append(t)
    total = sum(len(v) for v in by_stand.values())
    order = sorted(by_stand, key=lambda s: (-len(by_stand[s]), s))[:n]
    rows = []
    for stand in order:
        xy = [geo.proj(t.pts[0][0], t.pts[0][1]) for t in by_stand[stand]]
        mx = statistics.median(p[0] for p in xy)
        my = statistics.median(p[1] for p in xy)
        rows.append(StandRow(stand, len(xy), PERCENT * len(xy) / total, places.place_name(mx, my)))
    return rows


def top_hotspots(shift_list: Sequence[Mapping[str, Any]], n: int = TOP_N) -> list[HotRow]:
    """Rank the hotspot names by estimated pickups (hot ``w`` share x shift orders).

    ``shifts`` counts each shift once per name even if the name is hot at two places.

    Args:
        shift_list: The ``shifts`` of ``game_data.json``.
        n: How many names to return.

    Returns:
        Up to ``n`` rows, by pickups descending and then name.
    """
    count: Counter[str] = Counter()
    pickups: dict[str, float] = defaultdict(float)
    for sh in shift_list:
        orders = len(sh["orders"])
        for hot in sh["hot"]:
            pickups[hot["name"]] += hot["w"] * orders
        count.update({hot["name"] for hot in sh["hot"]})
    names = sorted(count, key=lambda k: (-pickups[k], k))[:n]
    return [HotRow(k, count[k], round(pickups[k])) for k in names]


def shift_rows(shift_list: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Pick the per-shift numbers that the report shows.

    Args:
        shift_list: The ``shifts`` of ``game_data.json``.

    Returns:
        One dict per shift: id, name, orders (count), drivers (count), ghost, median and top10
        (EUR), difficulty (1..5).
    """
    return [
        {
            "id": sh["id"],
            "name": sh["name"],
            "orders": len(sh["orders"]),
            "drivers": sh["nDrivers"],
            "ghost": sh["ghost"]["total"],
            "median": sh["median"],
            "top10": sh["top10"],
            "difficulty": sh["difficulty"],
        }
        for sh in shift_list
    ]


def ghost_lead(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Measure how far the ghost is ahead of the median.

    Shifts with a zero median are skipped. ``best`` and ``worst`` are shift ids (ties: first).

    Args:
        rows: Per-shift numbers from ``shift_rows`` (money in EUR).

    Returns:
        Dict with ``mean``, ``min`` and ``max`` of ghost/median (ratios), ``gap`` (mean
        ghost minus median, EUR), ``best``, ``worst`` (shift ids) and ``n`` (shifts counted).
    """
    ok = [r for r in rows if r["median"] > 0]
    if not ok:
        return {"mean": 0.0, "min": 0.0, "max": 0.0, "gap": 0.0, "best": "", "worst": "", "n": 0}
    ratio = {r["id"]: r["ghost"] / r["median"] for r in ok}
    best = max(ok, key=lambda r: ratio[r["id"]])["id"]
    worst = min(ok, key=lambda r: ratio[r["id"]])["id"]
    return {
        "mean": sum(ratio.values()) / len(ok),
        "min": ratio[worst],
        "max": ratio[best],
        "gap": sum(r["ghost"] - r["median"] for r in ok) / len(ok),
        "best": best,
        "worst": worst,
        "n": len(ok),
    }


def pickup_grid(trips: Iterable[shifts.Trip], cell_m: float = HEAT_CELL_M) -> np.ndarray:
    """Count pickups per square cell of the map frame.

    Args:
        trips: Valid trips.
        cell_m: Cell side, metres.

    Returns:
        Float array of shape (rows y, cols x) with pickup counts.
    """
    cols = math.ceil(geo.MAP_W_M / cell_m)
    rows = math.ceil(geo.MAP_H_M / cell_m)
    grid = np.zeros((rows, cols), dtype=np.float64)
    for t in trips:
        x, y = geo.proj(t.pts[0][0], t.pts[0][1])
        grid[min(rows - 1, int(y // cell_m)), min(cols - 1, int(x // cell_m))] += 1.0
    return grid


# --------------------------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------------------------


def fmt_int(n: float) -> str:
    """Format an integer with spaces between thousands: 32829 -> '32 829'.

    Args:
        n: Number, rounded to an integer.

    Returns:
        The text.
    """
    return f"{round(n):,}".replace(",", " ")


def fmt_eur(eur: float) -> str:
    """Format EUR like the game does: comma decimal, two digits, e.g. '€12,40'.

    Args:
        eur: Amount in euro.

    Returns:
        The text.
    """
    return f"€{eur:,.2f}".replace(",", " ").replace(".", ",")


def fmt_num(value: float, digits: int = 1) -> str:
    """Format a plain number with a decimal comma and spaces between thousands.

    Args:
        value: The number.
        digits: Digits after the comma.

    Returns:
        The text.
    """
    return f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")


def ascii_fold(text: str) -> str:
    """Strip accents so the label can be drawn with the bundled font: 'São' -> 'Sao'.

    Args:
        text: Any text.

    Returns:
        The text with accents dropped and non-ASCII characters removed.
    """
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def md_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    """Build a Markdown table.

    Args:
        headers: Column titles.
        rows: Cell texts, one sequence per row.

    Returns:
        The header line, the separator line and one line per row.
    """
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return lines


# --------------------------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------------------------


def md_week(totals: Mapping[str, float], rows: int, in_shifts: int) -> list[str]:
    """Write the section 'the week in numbers'.

    Args:
        totals: Result of ``week_totals``.
        rows: Rows read from week.csv.
        in_shifts: Orders in the 28 game shifts.

    Returns:
        Markdown lines, ending with an empty line.
    """
    n = totals["trips"]
    table = [
        ("Рядків у тижневих даних", fmt_int(rows)),
        ("Поїздок, що проходять фільтр гри", fmt_int(n)),
        ("з них у 28 змінах гри (замовлення)", fmt_int(in_shifts)),
        ("Різних таксистів", fmt_int(totals["taxis"])),
        ("Пройдено, км", fmt_int(totals["km"])),
        ("Середня поїздка, км", fmt_num(totals["km"] / n if n else 0.0, 2)),
        ("Виторг за тарифом гри", fmt_eur(totals["cents"] / CENTS_PER_EUR)),
        ("Середній чек", fmt_eur(totals["cents"] / CENTS_PER_EUR / n if n else 0.0)),
    ]
    head = ["## Тиждень у цифрах", "", "Тариф гри: €3,25 + €0,50 за км, ×1,2 вночі (22:00–05:59)."]
    return [*head, "", *md_table(["Показник", "Значення"], [(a, b) for a, b in table]), ""]


def md_shifts(rows: Sequence[Mapping[str, Any]], lead: Mapping[str, Any]) -> list[str]:
    """Write the per-shift table and the summary of the ghost's lead.

    Args:
        rows: Result of ``shift_rows`` (money in EUR).
        lead: Result of ``ghost_lead``.

    Returns:
        Markdown lines.
    """
    body = [
        (
            f"`{r['id']}`",
            str(r["name"]),
            fmt_int(r["orders"]),
            fmt_int(r["drivers"]),
            fmt_eur(r["ghost"]),
            fmt_eur(r["median"]),
            fmt_eur(r["top10"]),
            str(r["difficulty"]),
        )
        for r in rows
    ]
    head = ["Зміна", "Назва", "Замовлень", "Водіїв", "Привид", "Медіана", "Топ-10 %", "Складність"]
    return [
        "## Зміни",
        "",
        "Привид — найкращий реальний водій зміни; медіана й топ-10 % — по всіх водіях зміни.",
        "",
        *md_table(head, body),
        "",
        f"![Привид, топ-10 % і медіана по змінах]({IMG_DIR}/{SHIFTS_PNG})",
        "",
        *md_ghost_lead(lead),
    ]


def md_ghost_lead(lead: Mapping[str, Any]) -> list[str]:
    """Write the lines about how far the ghost is ahead of the median.

    Args:
        lead: Result of ``ghost_lead``.

    Returns:
        Markdown lines; a one-line note if no shift could be counted.
    """
    if not lead["n"]:
        return ["Привид проти медіани: немає даних.", ""]
    return [
        "## Наскільки привид випереджає медіану",
        "",
        f"- У середньому привид заробляє в **{fmt_num(lead['mean'], 2)}** раза більше за медіану "
        f"водія (різниця {fmt_eur(lead['gap'])} за зміну).",
        f"- Найменший відрив: ×{fmt_num(lead['min'], 2)} (`{lead['worst']}`); "
        f"найбільший: ×{fmt_num(lead['max'], 2)} (`{lead['best']}`).",
        f"- Рахунок по {lead['n']} змінах.",
        "",
    ]


def md_demand(counts: Sequence[int]) -> list[str]:
    """Write the demand-by-hour section (table of the busiest hours plus the chart link).

    Args:
        counts: Trips per local hour 0..23.

    Returns:
        Markdown lines.
    """
    total = sum(counts)
    busiest = sorted(range(HOURS_PER_DAY), key=lambda h: (-counts[h], h))[:TOP_HOURS]
    rows = [
        (f"{h:02d}:00", fmt_int(counts[h]), fmt_num(PERCENT * counts[h] / total if total else 0.0))
        for h in busiest
    ]
    return [
        "## Попит за годинами доби",
        "",
        f"![Поїздки за годинами]({IMG_DIR}/{HOURS_PNG})",
        "",
        "П'ять найзавантаженіших годин (місцевий час початку поїздки):",
        "",
        *md_table(["Година", "Поїздок", "Частка, %"], rows),
        "",
    ]


def md_calls(mix: Sequence[Mapping[str, float]]) -> list[str]:
    """Write the call-type mix table.

    Args:
        mix: Result of ``call_mix``.

    Returns:
        Markdown lines.
    """
    rows = [
        (
            CALL_TITLES[i],
            fmt_int(m["trips"]),
            fmt_num(m["share"]),
            fmt_num(m["km"], 2),
            fmt_eur(m["eur"]),
        )
        for i, m in enumerate(mix)
    ]
    head = ["Тип виклику", "Поїздок", "Частка, %", "Середній км", "Середній чек"]
    return ["## Типи викликів", "", *md_table(head, rows), ""]


def md_stands(stands: Sequence[StandRow]) -> list[str]:
    """Write the top-stands table.

    Args:
        stands: Result of ``top_stands``.

    Returns:
        Markdown lines.
    """
    rows = [(str(s.stand), fmt_int(s.trips), fmt_num(s.share), s.name) for s in stands]
    head = ["Стоянка №", "Поїздок", "Частка стоянок, %", "Де (за мапою гри)"]
    return ["## Топ-10 стоянок", "", *md_table(head, rows), ""]


def md_hotspots(hot: Sequence[HotRow]) -> list[str]:
    """Write the top-hotspots table and the heatmap link.

    Args:
        hot: Result of ``top_hotspots``.

    Returns:
        Markdown lines.
    """
    rows = [(h.name, str(h.shifts), fmt_int(h.pickups)) for h in hot]
    head = ["Гаряча точка", "У скількох змінах", "Посадок (оцінка)"]
    return [
        "## Гарячі точки",
        "",
        "Гарячі точки гри — скупчення посадок у зміні; тут вони зведені по всіх 28 змінах.",
        "",
        *md_table(head, rows),
        "",
        f"![Де сідають пасажири]({IMG_DIR}/{HEATMAP_PNG})",
        "",
    ]


def md_filter(total: int, table: Sequence[tuple[str, int, float]], kept: int) -> list[str]:
    """Write the section about trips dropped by the game filter, per rule.

    Args:
        total: Rows read from week.csv.
        table: Result of ``filter_table``.
        kept: Trips that passed the filter.

    Returns:
        Markdown lines.
    """
    rows = [(RULE_TEXT[rule], fmt_int(n), fmt_num(share)) for rule, n, share in table]
    dropped = total - kept
    return [
        "## Що відсіяв фільтр",
        "",
        f"З {fmt_int(total)} рядків гра залишила {fmt_int(kept)}; відсіяно **{fmt_int(dropped)}** "
        f"({fmt_num(PERCENT * dropped / total if total else 0.0)} %). Кожна поїздка зарахована до "
        "першого правила, яке вона порушила.",
        "",
        *md_table(["Правило", "Відсіяно", "Частка всіх, %"], rows),
        "",
    ]


def build_markdown(
    *,
    totals: Mapping[str, float],
    rows: int,
    rejected: Mapping[str, int],
    counts: Sequence[int],
    mix: Sequence[Mapping[str, float]],
    stands: Sequence[StandRow],
    hot: Sequence[HotRow],
    shift_table: Sequence[Mapping[str, Any]],
) -> str:
    """Assemble STATS.md (Ukrainian, tables, image links) from the computed pieces.

    Args:
        totals: Result of ``week_totals``.
        rows: Rows read from week.csv.
        rejected: Rows rejected first by each rule key.
        counts: Trips per local hour.
        mix: Result of ``call_mix``.
        stands: Result of ``top_stands``.
        hot: Result of ``top_hotspots``.
        shift_table: Result of ``shift_rows``.

    Returns:
        The whole file text, ending with one newline.
    """
    in_shifts = sum(r["orders"] for r in shift_table)
    lead = ghost_lead(shift_table)
    lines = [
        "# 7 ланосів: дані тижня",
        "",
        "Зведення з реальних поїздок Порту (UCI 339, CC BY 4.0), 12–18 травня 2014. "
        "Усе тут пораховано з даних; тариф, час ×40 та інше — вигадка гри. "
        "Файл створює `python -m pipeline.report`.",
        "",
        *md_week(totals, rows, in_shifts),
        *md_shifts(shift_table, lead),
        *md_demand(counts),
        *md_calls(mix),
        *md_stands(stands),
        *md_hotspots(hot),
        *md_filter(rows, filter_table(rows, rejected), int(totals["trips"])),
    ]
    return "\n".join(lines).rstrip("\n") + "\n"


# --------------------------------------------------------------------------------------------
# Charts (Pillow, dark theme, ASCII text)
# --------------------------------------------------------------------------------------------


def font(px: int) -> ImageFont.FreeTypeFont:
    """Load the bundled Pillow font.

    Args:
        px: Font size, pixels.

    Returns:
        The font.
    """
    return ImageFont.load_default(px)


def text_w(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont) -> int:
    """Measure a text.

    Args:
        draw: Drawing context.
        text: The text.
        fnt: The font.

    Returns:
        Width in pixels, rounded up.
    """
    return math.ceil(draw.textlength(text, font=fnt))


def render_hours(counts: Sequence[int]) -> Image.Image:
    """Draw demand by local hour of day as 24 vertical bars; return an RGB image (720 x 440 px)."""
    img = Image.new("RGB", (IMG_W, HOURS_H), BG)
    d = ImageDraw.Draw(img)
    big, small = font(FONT_PX), font(FONT_SMALL_PX)
    peak = max(max(counts, default=0), 1)
    d.text((MARGIN, 14), "Trips by hour of day", font=big, fill=TEXT)
    d.text(
        (IMG_W - MARGIN - text_w(d, f"max {peak}", small), 18),
        f"max {peak}",
        font=small,
        fill=MUTED,
    )
    left, right = MARGIN, IMG_W - MARGIN
    top, bottom = HOURS_PLOT_TOP, HOURS_H - HOURS_PLOT_BOTTOM
    slot = (right - left) / 24
    busiest = counts.index(max(counts)) if counts else -1
    for h, n in enumerate(counts):
        x0 = left + h * slot + 2
        y0 = bottom - (bottom - top) * n / peak
        d.rectangle((x0, y0, x0 + slot - 4, bottom), fill=AMBER if h == busiest else CYAN)
        if h % HOURS_LABEL_STEP == 0:
            label = f"{h:02d}"
            d.text(
                (x0 + (slot - 4 - text_w(d, label, small)) / 2, bottom + 10),
                label,
                font=small,
                fill=MUTED,
            )
    d.line((left, bottom, right, bottom), fill=MUTED, width=1)
    d.text((MARGIN, HOURS_H - 28), "local hour of pickup", font=small, fill=MUTED)
    return img


def render_shifts(rows: Sequence[Mapping[str, Any]]) -> Image.Image:
    """Draw ghost / top 10 % / median totals per shift as grouped horizontal bars (RGB, 720 px)."""
    row_h = 3 * SHIFT_BAR_H + SHIFT_ROW_GAP
    height = SHIFT_HEADER_H + row_h * len(rows) + MARGIN
    img = Image.new("RGB", (IMG_W, height), BG)
    d = ImageDraw.Draw(img)
    big, small = font(FONT_PX), font(FONT_SMALL_PX)
    d.text((MARGIN, 12), "Shift totals, EUR", font=big, fill=TEXT)
    x = MARGIN
    for label, colour in (("ghost", GHOST), ("top 10%", MINT), ("median", MUTED)):
        d.rectangle((x, 46, x + 14, 58), fill=colour)
        d.text((x + 20, 41), label, font=small, fill=colour)
        x += 20 + text_w(d, label, small) + 22
    left = MARGIN + SHIFT_LABEL_W
    span = IMG_W - MARGIN - 70 - left
    peak = max((max(r["ghost"], r["top10"], r["median"]) for r in rows), default=1.0) or 1.0
    for i, r in enumerate(rows):
        y = SHIFT_HEADER_H + i * row_h
        d.text((MARGIN, y + 2), str(r["id"]), font=small, fill=TEXT)
        for j, (key, colour) in enumerate((("ghost", GHOST), ("top10", MINT), ("median", MUTED))):
            y0 = y + j * SHIFT_BAR_H
            d.rectangle(
                (left, y0, left + max(1, span * r[key] / peak), y0 + SHIFT_BAR_H - 2), fill=colour
            )
        d.text(
            (left + span * r["ghost"] / peak + 8, y + 2),
            f"{r['ghost']:.0f}",
            font=small,
            fill=GHOST,
        )
    return img


def heat_palette() -> list[tuple[int, int, int]]:
    """Return 256 RGB colours interpolated along HEAT_RAMP (dark blue, cyan, amber, white)."""
    out = []
    segs = len(HEAT_RAMP) - 1
    for i in range(256):
        pos = i / 255 * segs
        k = min(int(pos), segs - 1)
        f = pos - k
        a, b = HEAT_RAMP[k], HEAT_RAMP[k + 1]
        out.append(tuple(round(a[c] + (b[c] - a[c]) * f) for c in range(3)))
    return out


def heat_levels(grid: np.ndarray) -> np.ndarray:
    """Blur a count grid and return uint8 levels 0..255 on a log scale (max cell = 255)."""
    blurred = gaussian_filter(grid, HEAT_BLUR_CELLS)
    top = float(blurred.max())
    if top <= 0.0:
        return np.zeros(grid.shape, dtype=np.uint8)
    return np.round(255.0 * np.log1p(blurred) / math.log1p(top)).astype(np.uint8)


def render_heatmap(grid: np.ndarray) -> Image.Image:
    """Draw the pickup heatmap over the map frame (RGB, 1 grid cell = HEAT_SCALE px)."""
    levels = heat_levels(grid)
    lut = np.array(heat_palette(), dtype=np.uint8)
    small = Image.fromarray(lut[levels], "RGB")
    size = (grid.shape[1] * HEAT_SCALE, grid.shape[0] * HEAT_SCALE)
    img = small.resize(size, Image.Resampling.BICUBIC)
    d = ImageDraw.Draw(img)
    fnt = font(FONT_SMALL_PX)
    px_per_m = HEAT_SCALE / HEAT_CELL_M
    for name, x, y in places.place_points():
        if name not in HEAT_LANDMARKS:
            continue
        cx, cy = x * px_per_m, y * px_per_m
        d.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), outline=TEXT, width=2)
        d.text((cx + 8, cy - 10), ascii_fold(name), font=fnt, fill=TEXT)
    bar = 5000 * px_per_m
    d.line((MARGIN, size[1] - MARGIN, MARGIN + bar, size[1] - MARGIN), fill=TEXT, width=3)
    d.text((MARGIN, size[1] - MARGIN - 26), "5 km", font=fnt, fill=TEXT)
    return img


def save_png(img: Image.Image, path: Path) -> None:
    """Write an image as an optimised PNG, creating the folder; no timestamps are stored."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG", optimize=True)


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------


def load_game_data(path: Path) -> dict[str, Any]:
    """Read game_data.json and return the parsed dict."""
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def build_parser() -> argparse.ArgumentParser:
    """Return the command-line parser."""
    p = argparse.ArgumentParser(prog="pipeline.report", description=__doc__.splitlines()[0])
    p.add_argument("--week", type=Path, default=DEFAULT_WEEK, help="week.csv (default %(default)s)")
    p.add_argument("--data", type=Path, default=DEFAULT_DATA, help="game_data.json")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output folder (STATS.md, img/)")
    return p


def write_report(week: Path, data: Path, out: Path) -> list[Path]:
    """Compute everything and write STATS.md and the PNG charts; return the written paths."""
    trips, rows, rejected = scan_week(week)
    shift_list = load_game_data(data)["shifts"]
    shift_table = shift_rows(shift_list)
    text = build_markdown(
        totals=week_totals(trips),
        rows=rows,
        rejected=rejected,
        counts=demand_by_hour(trips),
        mix=call_mix(trips),
        stands=top_stands(trips),
        hot=top_hotspots(shift_list),
        shift_table=shift_table,
    )
    out.mkdir(parents=True, exist_ok=True)
    stats = out / STATS_NAME
    stats.write_text(text, encoding="utf-8", newline="\n")
    images = {
        out / IMG_DIR / HOURS_PNG: render_hours(demand_by_hour(trips)),
        out / IMG_DIR / SHIFTS_PNG: render_shifts(shift_table),
        out / IMG_DIR / HEATMAP_PNG: render_heatmap(pickup_grid(trips)),
    }
    for path, img in images.items():
        save_png(img, path)
    return [stats, *images]


def main(argv: list[str] | None = None) -> int:
    """Run the report CLI; exit 0 on success, 1 if an input file is missing."""
    args = build_parser().parse_args(argv)
    for path in (args.week, args.data):
        if not path.is_file():
            print(f"missing input file: {path}", file=sys.stderr)
            return 1
    for path in write_report(args.week, args.data, args.out):
        print(f"wrote {path} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
