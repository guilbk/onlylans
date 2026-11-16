"""Tests for pipeline.report on tiny synthetic data."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from pipeline import geo, places, report, shifts

LON0, LAT0 = -8.61, 41.15
DLAT = 0.0027  # about 300 m, below the 625 m step limit
TS_MON_08 = 1399878000  # 2014-05-12 08:00 Europe/Lisbon (07:00 UTC)


def line(n: int = 8, lon: float = LON0, lat: float = LAT0) -> list[list[float]]:
    """Return a straight north-going polyline of n points, about 300 m apart."""
    return [[lon, lat + i * DLAT] for i in range(n)]


def make_trip(
    taxi: int = 1,
    call: int = 0,
    stand: int = 0,
    hour: int = 9,
    pts: list[list[float]] | None = None,
    ts: int = TS_MON_08,
) -> shifts.Trip:
    """Build a Trip with km from its points."""
    pts = pts or line()
    return shifts.Trip(f"id{taxi}{ts}{hour}", taxi, ts, call, stand, pts, geo.path_km(pts), hour)


def make_shift(sid: str, orders: int, ghost: float, median: float, hot: list[dict]) -> dict:
    """Build the part of a game_data shift that the report reads."""
    return {
        "id": sid,
        "name": f"name {sid}",
        "orders": [[0] * 12 for _ in range(orders)],
        "nDrivers": 10,
        "ghost": {"taxi": 0, "total": ghost, "orders": []},
        "median": median,
        "top10": ghost / 2,
        "difficulty": 3,
        "hot": hot,
    }


# --- filter rules --------------------------------------------------------------------------


def test_row_reason() -> None:
    """Missing flag wins, then bad JSON, then the geometry rules."""
    base = {"MISSING_DATA": "False", "POLYLINE": json.dumps(line())}
    assert report.row_reason(base) is None
    assert report.row_reason({**base, "MISSING_DATA": "True"}) == report.RULE_MISSING
    assert report.row_reason({**base, "POLYLINE": "[[1,"}) == report.RULE_BAD_JSON
    assert report.row_reason({**base, "POLYLINE": "[]"}) == report.RULE_POINTS


def test_filter_table_order_and_shares() -> None:
    """The table follows RULE_ORDER, fills missing rules with zeros and gives % of all rows."""
    table = report.filter_table(200, {report.RULE_STEP: 50, report.RULE_POINTS: 10})
    assert [r[0] for r in table] == list(report.RULE_ORDER)
    shares = {rule: share for rule, _n, share in table}
    assert shares[report.RULE_STEP] == 25.0
    assert shares[report.RULE_POINTS] == 5.0
    assert shares[report.RULE_BAD_JSON] == 0.0
    assert all(s == 0.0 for _r, _n, s in report.filter_table(0, {}))


# --- computations --------------------------------------------------------------------------


def test_trip_cents_day_and_night() -> None:
    """A 2.1 km trip costs 3.25 + 0.5 km by day and x1.2 at night, in cents."""
    day = make_trip(hour=9)
    night = make_trip(hour=23)
    km = round(day.km, 2)
    assert report.trip_cents(day) == round(geo.fare(km, False) * 100)
    assert report.trip_cents(night) == round(geo.fare(km, True) * 100)
    assert report.trip_cents(night) > report.trip_cents(day)


def test_week_totals() -> None:
    """Totals count trips, distinct taxis, km and cents."""
    trips = [make_trip(taxi=1), make_trip(taxi=1, ts=TS_MON_08 + 5), make_trip(taxi=2, hour=2)]
    totals = report.week_totals(trips)
    assert totals["trips"] == 3
    assert totals["taxis"] == 2
    assert totals["km"] == pytest.approx(sum(t.km for t in trips))
    assert totals["cents"] == sum(report.trip_cents(t) for t in trips)
    assert report.week_totals([])["taxis"] == 0


def test_demand_by_hour() -> None:
    """Trips are counted per local hour; the list has 24 slots."""
    counts = report.demand_by_hour([make_trip(hour=9), make_trip(hour=9), make_trip(hour=0)])
    assert len(counts) == 24
    assert counts[9] == 2
    assert counts[0] == 1
    assert sum(counts) == 3


def test_call_mix() -> None:
    """Shares add up to 100 and empty call types give zeros."""
    trips = [make_trip(call=0), make_trip(call=0), make_trip(call=1), make_trip(call=1)]
    mix = report.call_mix(trips)
    assert [m["trips"] for m in mix] == [2, 2, 0]
    assert mix[0]["share"] == 50.0
    assert mix[2]["km"] == 0.0
    assert mix[0]["eur"] == pytest.approx(report.trip_cents(trips[0]) / 100.0)
    assert report.call_mix([])[0]["share"] == 0.0


def test_top_stands() -> None:
    """Stands are ranked by trips, ties by id; stand 0 is ignored; shares are of stand trips."""
    trips = (
        [make_trip(stand=7) for _ in range(3)]
        + [make_trip(stand=3) for _ in range(2)]
        + [make_trip(stand=5) for _ in range(2)]
        + [make_trip(stand=0) for _ in range(9)]
    )
    rows = report.top_stands(trips, n=2)
    assert [(r.stand, r.trips) for r in rows] == [(7, 3), (3, 2)]
    assert rows[0].share == pytest.approx(100.0 * 3 / 7)
    assert isinstance(rows[0].name, str)
    assert report.top_stands([]) == []


def test_top_stands_name_uses_median_pickup() -> None:
    """The stand is named after the place nearest to its median pickup."""
    lon, lat = places_lonlat("Aliados")
    trips = [make_trip(stand=1, pts=line(8, lon, lat)) for _ in range(3)]
    assert report.top_stands(trips)[0].name == "Aliados"


def places_lonlat(name: str) -> tuple[float, float]:
    """Return lon/lat of a named place from pipeline.places."""
    return next((lon, lat) for n, lon, lat in places.PLACES if n == name)


def test_top_hotspots() -> None:
    """Pickups are w x orders summed over shifts; shifts counts each shift once per name."""
    sh = [
        make_shift("a", 100, 10, 5, [{"name": "X", "w": 0.5}, {"name": "X", "w": 0.1}]),
        make_shift("b", 200, 10, 5, [{"name": "X", "w": 0.25}, {"name": "Y", "w": 0.4}]),
        make_shift("c", 10, 10, 5, []),
    ]
    rows = report.top_hotspots(sh)
    assert [(r.name, r.shifts, r.pickups) for r in rows] == [("X", 2, 110), ("Y", 1, 80)]
    assert len(report.top_hotspots(sh, n=1)) == 1


def test_shift_rows() -> None:
    """Shift rows carry the numbers the table needs."""
    rows = report.shift_rows([make_shift("mon-am", 12, 30.0, 10.0, [])])
    assert rows[0] == {
        "id": "mon-am",
        "name": "name mon-am",
        "orders": 12,
        "drivers": 10,
        "ghost": 30.0,
        "median": 10.0,
        "top10": 15.0,
        "difficulty": 3,
    }


def test_ghost_lead() -> None:
    """Ratio and gap are means over shifts; a zero median is skipped; empty input is safe."""
    rows = report.shift_rows(
        [
            make_shift("a", 1, 30.0, 10.0, []),
            make_shift("b", 1, 20.0, 10.0, []),
            make_shift("c", 1, 5.0, 0.0, []),
        ]
    )
    lead = report.ghost_lead(rows)
    assert lead["n"] == 2
    assert lead["mean"] == pytest.approx(2.5)
    assert lead["gap"] == pytest.approx(15.0)
    assert (lead["best"], lead["worst"]) == ("a", "b")
    assert (lead["max"], lead["min"]) == (3.0, 2.0)
    assert report.ghost_lead([])["n"] == 0


def test_pickup_grid() -> None:
    """Pickups land in the cell of their projected first point; shape covers the whole map."""
    x, y = geo.proj(LON0, LAT0)
    grid = report.pickup_grid([make_trip(), make_trip()], cell_m=100.0)
    assert grid.shape == (geo.MAP_H_M // 100, geo.MAP_W_M // 100)
    assert grid.sum() == 2.0
    assert grid[int(y // 100), int(x // 100)] == 2.0


# --- formatting ----------------------------------------------------------------------------


def test_formatting() -> None:
    """Numbers use spaces for thousands and a decimal comma."""
    assert report.fmt_int(32829) == "32 829"
    assert report.fmt_int(0) == "0"
    assert report.fmt_eur(12.4) == "€12,40"
    assert report.fmt_eur(162938.7) == "€162 938,70"
    assert report.fmt_num(3.256, 2) == "3,26"
    assert report.ascii_fold("São Bento Campanhã") == "Sao Bento Campanha"
    assert report.md_table(["a", "b"], [("1", "2")]) == ["| a | b |", "|---|---|", "| 1 | 2 |"]


def test_build_markdown_sections() -> None:
    """The report has every required section, image links and no English placeholders."""
    trips = [make_trip(call=i % 3, stand=i % 2, hour=i % 24) for i in range(30)]
    shift_table = report.shift_rows([make_shift("mon-am", 5, 30.0, 10.0, [])])
    text = report.build_markdown(
        totals=report.week_totals(trips),
        rows=40,
        rejected={report.RULE_STEP: 10},
        counts=report.demand_by_hour(trips),
        mix=report.call_mix(trips),
        stands=report.top_stands(trips),
        hot=[report.HotRow("X", 1, 5)],
        shift_table=shift_table,
    )
    for needle in (
        "## Тиждень у цифрах",
        "## Зміни",
        "## Наскільки привид випереджає медіану",
        "## Попит за годинами доби",
        "## Типи викликів",
        "## Топ-10 стоянок",
        "## Гарячі точки",
        "## Що відсіяв фільтр",
        "img/hours.png",
        "img/shifts.png",
        "img/heatmap.png",
        "`mon-am`",
    ):
        assert needle in text
    assert text.endswith("\n")


# --- charts --------------------------------------------------------------------------------


def test_render_hours() -> None:
    """The hours chart is an RGB image of phone width with dark background."""
    img = report.render_hours(list(range(24)))
    assert img.mode == "RGB"
    assert img.size == (report.IMG_W, report.HOURS_H)
    assert img.getpixel((0, 0)) == report.BG
    assert report.render_hours([0] * 24).size == img.size


def test_render_shifts() -> None:
    """The shifts chart grows with the number of shifts and keeps the width."""
    rows = report.shift_rows([make_shift(f"s{i}", 5, 30.0 + i, 10.0, []) for i in range(5)])
    img = report.render_shifts(rows)
    assert img.mode == "RGB"
    assert img.width == report.IMG_W
    assert img.height == report.render_shifts(rows[:2]).height + 3 * (
        3 * report.SHIFT_BAR_H + report.SHIFT_ROW_GAP
    )
    assert report.render_shifts([]).width == report.IMG_W


def test_heat_palette_and_levels() -> None:
    """The palette has 256 colours from the ramp ends; levels peak at 255 and empty is zeros."""
    pal = report.heat_palette()
    assert len(pal) == 256
    assert pal[0] == report.HEAT_RAMP[0]
    assert pal[-1] == report.HEAT_RAMP[-1]
    grid = np.zeros((20, 20))
    grid[10, 10] = 50.0
    levels = report.heat_levels(grid)
    assert levels.dtype == np.uint8
    assert levels.max() == 255
    assert levels[10, 10] == 255
    assert report.heat_levels(np.zeros((4, 4))).max() == 0


def test_render_heatmap() -> None:
    """The heatmap covers the whole map frame at HEAT_SCALE px per cell."""
    grid = report.pickup_grid([make_trip()], cell_m=report.HEAT_CELL_M)
    img = report.render_heatmap(grid)
    assert img.mode == "RGB"
    assert img.size == (grid.shape[1] * report.HEAT_SCALE, grid.shape[0] * report.HEAT_SCALE)


def test_save_png(tmp_path: Path) -> None:
    """save_png creates folders and writes a readable PNG."""
    path = tmp_path / "a" / "b.png"
    report.save_png(Image.new("RGB", (5, 4), report.BG), path)
    with Image.open(path) as back:
        assert back.format == "PNG"
        assert back.size == (5, 4)


# --- CLI -----------------------------------------------------------------------------------


def write_week(path: Path) -> None:
    """Write a tiny week.csv: 3 valid trips, one too short, one with broken JSON."""
    header = [
        "TRIP_ID", "CALL_TYPE", "ORIGIN_CALL", "ORIGIN_STAND", "TAXI_ID", "TIMESTAMP",
        "DAY_TYPE", "MISSING_DATA", "POLYLINE",
    ]  # fmt: skip
    rows = [
        ["1", "A", "5", "", "11", str(TS_MON_08 + 10), "A", "False", json.dumps(line())],
        ["2", "B", "", "4", "12", str(TS_MON_08 + 20), "A", "False", json.dumps(line(9))],
        ["3", "C", "", "", "11", str(TS_MON_08 + 30), "A", "False", json.dumps(line(10))],
        ["4", "C", "", "", "13", str(TS_MON_08 + 40), "A", "False", json.dumps(line(2))],
        ["5", "C", "", "", "13", str(TS_MON_08 + 50), "A", "False", "[[1,"],
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def write_data(path: Path) -> None:
    """Write a tiny game_data.json with two shifts."""
    data = {
        "shifts": [
            make_shift("mon-am", 3, 30.0, 10.0, [{"name": "Aliados", "w": 0.5}]),
            make_shift("mon-lunch", 2, 20.0, 8.0, []),
        ]
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def test_scan_week(tmp_path: Path) -> None:
    """scan_week returns the valid trips, the row count and rejects per rule."""
    week = tmp_path / "week.csv"
    write_week(week)
    trips, rows, rejected = report.scan_week(week)
    assert [t.taxi for t in trips] == [11, 12, 11]
    assert rows == 5
    assert rejected == {report.RULE_POINTS: 1, report.RULE_BAD_JSON: 1}
    assert [t.trip_id for t in trips] == [t.trip_id for t in shifts.load_trips(week)]


def test_main_writes_report_and_is_deterministic(tmp_path: Path) -> None:
    """main writes STATS.md and three PNGs; a second run gives identical bytes."""
    week, data = tmp_path / "week.csv", tmp_path / "game_data.json"
    write_week(week)
    write_data(data)
    names = ["STATS.md", "img/hours.png", "img/shifts.png", "img/heatmap.png"]
    runs = []
    for k in range(2):
        out = tmp_path / f"out{k}"
        assert report.main(["--week", str(week), "--data", str(data), "--out", str(out)]) == 0
        runs.append([(out / n).read_bytes() for n in names])
    assert runs[0] == runs[1]
    text = (tmp_path / "out0" / "STATS.md").read_text(encoding="utf-8")
    assert "| Різних таксистів | 2 |" in text
    assert "| `mon-am` |" in text


def test_main_missing_input(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A missing input file gives exit code 1 and a message on stderr."""
    rc = report.main(["--week", str(tmp_path / "no.csv"), "--out", str(tmp_path)])
    assert rc == 1
    assert "missing input file" in capsys.readouterr().err
