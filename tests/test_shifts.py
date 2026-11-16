import csv
import json
import math

import pytest

from pipeline import geo, shifts

HEADER = [
    "TRIP_ID",
    "CALL_TYPE",
    "ORIGIN_CALL",
    "ORIGIN_STAND",
    "TAXI_ID",
    "TIMESTAMP",
    "DAY_TYPE",
    "MISSING_DATA",
    "POLYLINE",
]
DEFS = shifts.shift_defs()
ID = {d.id: d for d in DEFS}


def polyline(n=12, step_m=100.0, lon=-8.61, lat=41.15):
    """West-to-east straight polyline, n points, step_m apart (about (n-1)*step_m metres)."""
    dlon = step_m / geo.M_LON
    return [[round(lon + i * dlon, 6), lat] for i in range(n)]


def row(i, taxi, ts, call="C", stand="", missing="False", pts=None, lat=41.15):
    pts = polyline(lat=lat) if pts is None else pts
    return [str(1000 + i), call, "", stand, str(taxi), str(ts), "A", missing, json.dumps(pts)]


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, quoting=csv.QUOTE_ALL)
        w.writerow(HEADER)
        w.writerows(rows)
    return path


def sample_rows():
    """A small week: mon-am has 3 drivers, a night trip, junk rows and out-of-window rows."""
    t0 = ID["mon-am"].start
    n0 = ID["mon-night"].start
    return [
        row(1, 7, t0 + 10),
        row(2, 7, t0 + 600, call="A"),
        row(3, 5, t0 + 700, call="B", stand="12", pts=polyline(20)),
        row(4, 9, t0 + 800, lat=41.16),
        row(5, 9, t0 + 7199),
        row(6, 5, t0 + 7200),  # first second after mon-am: not in the shift
        row(7, 5, t0 - 1),  # last second before
        row(8, 7, t0 + 900, missing="True"),
        row(9, 7, t0 + 950, pts=polyline(3)),
        row(10, 8, n0 + 60),  # night trip
    ]


def test_shift_defs_ids_names_and_times():
    assert len(DEFS) == 28
    assert DEFS[0].id == "mon-am" and DEFS[3].id == "mon-night" and DEFS[27].id == "sun-night"
    assert [d.slot for d in DEFS[:4]] == ["am", "lunch", "pm", "night"]
    assert DEFS[0].name == "Понеділковий ранок"
    assert DEFS[0].day == "понеділок, 12 травня 2014"
    assert DEFS[0].start_local == "2014-05-12 08:00"
    assert DEFS[0].start == 1399878000  # 07:00 UTC, Lisbon is UTC+1 in May
    assert DEFS[10].day == "середа, 14 травня 2014"
    assert DEFS[27].day == "неділя, 18 травня 2014"
    assert len({d.id for d in DEFS}) == 28


def test_saturday_night_is_real_sunday_start():
    sat = ID["sat-night"]
    assert sat.start_hour == 0
    assert sat.start_local == "2014-05-18 00:00"
    assert sat.day == "з суботи на неділю, 18 травня 2014"
    assert sat.name == "Ніч на неділю"
    assert sat.start == 1400367600  # 2014-05-17 23:00 UTC
    assert ID["sun-am"].start - sat.start == 8 * 3600


def test_parse_row_filters():
    good = shifts.parse_row(dict(zip(HEADER, row(1, 7, 1399878010), strict=True)))
    assert good is not None and good.taxi == 7 and good.call == 2 and good.stand == 0
    for bad in (row(2, 7, 1399878010, missing="True"), row(3, 7, 1399878010, pts=polyline(3))):
        assert shifts.parse_row(dict(zip(HEADER, bad, strict=True))) is None
    broken = row(4, 7, 1399878010)
    broken[-1] = "[[-8.6"
    assert shifts.parse_row(dict(zip(HEADER, broken, strict=True))) is None


def test_build_shift_ranking_ghost_and_orders(tmp_path):
    trips = shifts.load_trips(write_csv(tmp_path / "w.csv", sample_rows()))
    assert len(trips) == 8  # missing-data and 3-point trips dropped
    sd = ID["mon-am"]
    s = shifts.build_shift(sd, trips, [30.0] * 24, 5)
    # trips in window: taxi 7 x2, taxi 5 x1 (20 points), taxi 9 x2
    assert len(s["orders"]) == 5
    assert [o[0] for o in s["orders"]] == sorted(o[0] for o in s["orders"])
    assert s["orders"][0][0] == 10 and s["orders"][-1][0] == 7199
    assert s["nDrivers"] == 3 == len(s["taxis"]) == len(s["ranking"])
    assert s["ranking"] == sorted(s["ranking"], reverse=True)
    # taxi 5: one long trip (1.9 km) = 3.25 + 0.95 = 4.2 ; taxi 7 and 9: two 1.1 km trips
    km_short = round(geo.path_km(polyline(12)), 2)
    f_short = geo.fare(km_short, False)
    assert s["ranking"][0] == pytest.approx(2 * f_short)
    assert s["taxis"][:2] == [7, 9]  # equal totals, ties by TAXI_ID
    assert s["ghost"]["taxi"] == 0 and s["ghost"]["total"] == s["ranking"][0]
    assert s["ghost"]["orders"] == [i for i, o in enumerate(s["orders"]) if o[11] == 0]
    assert s["median"] == s["ranking"][1]
    assert s["top10"] == s["ranking"][0]  # ceil(0.3) - 1 = 0
    assert s["hot"] == [] and s["surges"] == []


def test_order_array_fields_and_delta_reconstruction(tmp_path):
    pts = polyline(20)
    path = write_csv(tmp_path / "w.csv", [row(1, 3, ID["mon-am"].start + 5, "B", "12", pts=pts)])
    trips = shifts.load_trips(path)
    o = shifts.make_order(trips[0], ID["mon-am"].start, 0, 5)
    t, x0, y0, x1, y1, deltas, d, km, fare, c, stand, taxi = o
    assert (t, c, stand, taxi) == (5, 1, 12, 0)
    assert len(deltas) == 2 * (len(pts) - 1) and d == 15 * (len(pts) - 1)
    x, y = x0, y0
    for i in range(0, len(deltas), 2):
        x, y = x + deltas[i], y + deltas[i + 1]
    assert (x, y) == (x1, y1)
    ex, ey = geo.proj(*pts[0])
    assert abs(x0 * 5 - ex) <= 2.5 and abs(y0 * 5 - ey) <= 2.5
    assert km == round(geo.path_km(pts), 2) and fare == geo.fare(km, False)


def test_night_fare_uses_local_pickup_hour(tmp_path):
    trips = shifts.load_trips(write_csv(tmp_path / "w.csv", sample_rows()))
    night = next(t for t in trips if t.taxi == 8)
    assert night.hour == 22
    s = shifts.build_shift(ID["mon-night"], trips, [30.0] * 24, 5)
    km = round(geo.path_km(polyline(12)), 2)
    assert s["orders"][0][8] == geo.fare(km, True) > geo.fare(km, False)
    assert s["ranking"] == [geo.fare(km, True)]


def test_empty_shift_is_valid(tmp_path):
    trips = shifts.load_trips(write_csv(tmp_path / "w.csv", sample_rows()))
    s = shifts.build_shift(ID["sun-pm"], trips, [30.0] * 24, 5)
    assert s["orders"] == [] and s["ranking"] == [] and s["nDrivers"] == 0
    assert s["ghost"] == {"taxi": 0, "total": 0.0, "orders": []}
    assert s["median"] == 0.0 and s["top10"] == 0.0


def test_top10_and_median_formulas():
    assert shifts.top10_of([9.0, 8.0, 7.0]) == 9.0
    ranking = [float(v) for v in range(30, 0, -1)]  # 30 drivers: ceil(3.0) - 1 = 2
    assert shifts.top10_of(ranking) == 28.0
    ranking = [float(v) for v in range(11, 0, -1)]  # 11 drivers: ceil(1.1) - 1 = 1
    assert shifts.top10_of(ranking) == 10.0
    assert shifts.median([1.0, 2.0, 3.0, 4.0]) == 2.5


def test_speed_by_hour_fallback_and_clamp(tmp_path):
    t0 = ID["mon-am"].start  # 08:00 local
    rows = [row(i, i, t0 + i) for i in range(40)]  # 40 trips at hour 8: 1.1 km in 165 s
    trips = shifts.load_trips(write_csv(tmp_path / "w.csv", rows))
    sp = shifts.speed_by_hour(trips)
    assert len(sp) == 24
    assert sp[8] == pytest.approx(round(1.1 / (165 / 3600), 1), abs=0.3)
    assert all(v == sp[8] for v in sp)  # other hours have < 30 trips: overall median
    for pts, want in ((polyline(4, 400.0), 60.0), (polyline(40, 30.0), 12.0)):
        rows = [row(i, i, t0 + i, pts=pts) for i in range(40)]
        out = shifts.speed_by_hour(shifts.load_trips(write_csv(tmp_path / "c.csv", rows)))
        assert out[8] == want


def test_detour_clamped():
    t = shifts.Trip("1", 1, 0, 2, 0, [[-8.61, 41.15], [-8.61, 41.151], [-8.60, 41.15]], 1.0, 8)
    assert 1.1 <= shifts.detour_of([t]) <= 1.8
    assert shifts.detour_of([]) == shifts.DETOUR_DEFAULT


def test_percentile_ranks_and_difficulty_range():
    assert shifts.percentile_ranks([5, 1, 3]) == [1.0, 0.0, 0.5]
    assert shifts.percentile_ranks([2, 2, 2]) == [0.5, 0.5, 0.5]
    fake = [
        {
            "median": 5.0 + i,
            "ghost": {"total": 20.0 + (i * 7) % 11},
            "orders": [0] * (100 + i),
            "nDrivers": 50,
            "_trips": [],
        }
        for i in range(28)
    ]
    shifts.assign_difficulty(fake)
    diffs = [s["difficulty"] for s in fake]
    assert set(diffs) == {1, 2, 3, 4, 5}
    assert all(4 <= diffs.count(k) <= 7 for k in range(1, 6))


def test_main_writes_valid_deterministic_file(tmp_path, capsys):
    week = write_csv(tmp_path / "w.csv", sample_rows())
    outs = []
    for name in ("a.json", "b.json"):
        assert shifts.main(["--week", str(week), "--out", str(tmp_path / name)]) == 0
        outs.append((tmp_path / name).read_bytes())
    assert outs[0] == outs[1]
    text = outs[0].decode("utf-8")
    assert "\n" not in text
    data = json.loads(text)
    assert data["version"] == 1 and data["unit_m"] == 5 and data["bounds"] == [0, 0, 3000, 3800]
    assert len(data["shifts"]) == 28 and [s["id"] for s in data["shifts"]] == [d.id for d in DEFS]
    assert list(data) == sorted(data)
    for s in data["shifts"]:
        assert len(s["speed_by_hour"]) == 24 and 1 <= s["difficulty"] <= 5
        assert all(len(o) == 12 for o in s["orders"])
    out = capsys.readouterr()
    assert "mon-am" in out.out and "warning: mon-am" in out.err
    assert math.isfinite(data["shifts"][0]["detour"])


def test_size_fallback_to_10m(tmp_path, monkeypatch):
    trips = shifts.load_trips(write_csv(tmp_path / "w.csv", sample_rows()))
    monkeypatch.setattr(shifts, "MAX_BYTES", 10)
    data = json.loads(shifts.build_text(trips))
    assert data["unit_m"] == 10 and data["bounds"] == [0, 0, 1500, 1900]
