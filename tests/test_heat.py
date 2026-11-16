import json
from pathlib import Path

from pipeline import heat

UNIT = 5


def order(x_m: float, y_m: float, t: int = 0, fare: float = 10.0):
    return [t, x_m / UNIT, y_m / UNIT, 0, 0, [], 60, 1.0, fare, 0, 0, 0]


def test_grid_size_rounds_up() -> None:
    assert heat.grid_size([0, 0, 3000, 3800], UNIT, 400) == (38, 48)
    assert heat.grid_size([0, 0, 3000, 3800], UNIT, 250) == (60, 76)


def test_hour_of_clamps() -> None:
    assert [heat.hour_of(t) for t in (0, 3599, 3600, 7199, 9000, -5)] == [0, 0, 1, 1, 1, 0]


def test_bin_fares_sums_by_pickup_cell_and_hour() -> None:
    orders = [order(100, 100, 0, 4.0), order(300, 300, 10, 6.0), order(100, 100, 4000, 9.0)]
    g0 = heat.bin_fares(orders, 0, 5, 5, UNIT)
    g1 = heat.bin_fares(orders, 1, 5, 5, UNIT)
    assert g0[0][0] == 10.0
    assert sum(map(sum, g0)) == 10.0
    assert g1[0][0] == 9.0


def test_bin_fares_clamps_outside_points() -> None:
    g = heat.bin_fares([order(99999, 99999)], 0, 3, 3, UNIT)
    assert g[2][2] == 10.0


def test_blur_keeps_total_inside_and_spreads() -> None:
    g = [[0.0] * 5 for _ in range(5)]
    g[2][2] = 16.0
    b = heat.blur(g)
    assert abs(sum(map(sum, b)) - 16.0) < 1e-9
    assert b[2][2] < 16.0
    assert b[2][3] > 0
    assert b[2][3] == b[3][2]


def test_pack_normalises_and_delta_codes() -> None:
    g = [[0.0, 10.0, 0.0], [0.0, 0.0, 5.0]]
    assert heat.pack(g) == [1, 99, 4, 50]


def test_pack_drops_cold_cells_and_empty_grid() -> None:
    assert heat.pack([[100.0, 1.0]]) == [0, 99]
    assert heat.pack([[0.0, 0.0]]) == []
    assert heat.pack([]) == []


def test_build_heat_shape_and_determinism() -> None:
    sh = {"id": "mon-am", "orders": [order(1000, 1000, 5), order(1100, 1000, 4000)]}
    data = {"unit_m": UNIT, "bounds": [0, 0, 600, 600], "shifts": [sh]}
    doc = heat.build_heat(data)
    assert (doc["cols"], doc["rows"], doc["cell_m"]) == (8, 8, heat.CELL_M)
    assert len(doc["shifts"]["mon-am"]) == heat.HOURS
    assert all(max(h[1::2]) == 99 for h in doc["shifts"]["mon-am"])
    assert heat.build_heat(data) == doc


def test_main_writes_file_and_reports_missing(tmp_path: Path) -> None:
    sh = {"id": "a", "orders": [order(500, 500)]}
    src = tmp_path / "d.json"
    src.write_text(json.dumps({"unit_m": UNIT, "bounds": [0, 0, 300, 300], "shifts": [sh]}))
    out = tmp_path / "o" / "heat.json"
    assert heat.main(["--data", str(src), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["shifts"]["a"]
    assert heat.main(["--data", str(tmp_path / "none.json"), "--out", str(out)]) == 1
