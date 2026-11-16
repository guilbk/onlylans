"""Tests for tools/make_fixture.py."""

import json
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import make_fixture as mf  # noqa: E402


def test_fare_rounds_half_up_to_cents() -> None:
    assert mf.fare(0.0) == 3.25
    assert mf.fare(10.0) == 8.25
    assert mf.fare(1.01) == 3.76  # 3.755 rounds up


def test_make_trip_fields_and_geometry() -> None:
    t, x0, y0, x1, y1, deltas, dur, km, fare, call, stand, taxi = mf.make_trip(
        random.Random(1), 600
    )
    assert t == 600 and taxi == 0
    n_pts = len(deltas) // 2 + 1
    assert mf.MIN_PTS <= n_pts <= mf.MAX_PTS and dur == mf.GPS_STEP_S * (n_pts - 1)
    assert (x1, y1) == (x0 + sum(deltas[0::2]), y0 + sum(deltas[1::2]))
    assert km > 0 and fare == mf.fare(km)
    assert call in (0, 1, 2) and (stand == 0) == (call != 1)


def test_schedule_trips_do_not_overlap_and_fit_the_shift() -> None:
    times = mf.schedule(random.Random(2), 5)
    longest = mf.GPS_STEP_S * (mf.MAX_PTS - 1)
    assert times == sorted(times) and len(times) == 5
    assert all(a + longest < b for a, b in zip(times, times[1:], strict=False))
    assert times[-1] + longest < mf.SHIFT_S


def test_build_orders_counts_and_order() -> None:
    orders, taxi_ids = mf.build_orders(random.Random(3))
    assert len(orders) == mf.N_TRIPS and len(taxi_ids) == mf.N_TAXIS
    assert len(set(taxi_ids)) == mf.N_TAXIS
    assert [o[0] for o in orders] == sorted(o[0] for o in orders)
    assert {o[11] for o in orders} == set(range(mf.N_TAXIS))


def test_rank_drivers_sorts_and_remaps_slots() -> None:
    orders = [[0] * 8 + [5.0, 0, 0, 1], [0] * 8 + [12.0, 0, 0, 0], [0] * 8 + [4.0, 0, 0, 1]]
    taxis, ranking = mf.rank_drivers(orders, [111, 222])
    assert taxis == [111, 222] and ranking == [12.0, 9.0]
    assert [o[11] for o in orders] == [1, 0, 1]  # slot 0 is rank 0, slot 1 is rank 1


def test_rank_drivers_ties_go_to_the_smaller_taxi_id() -> None:
    orders = [[0] * 8 + [5.0, 0, 0, 0], [0] * 8 + [5.0, 0, 0, 1]]
    taxis, ranking = mf.rank_drivers(orders, [300, 200])
    assert taxis == [200, 300] and ranking == [5.0, 5.0]
    assert [o[11] for o in orders] == [1, 0]


def test_median_odd_and_even() -> None:
    assert mf.median([1.0, 2.0, 9.0]) == 2.0
    assert mf.median([1.0, 2.0, 3.0, 5.0]) == 2.5


def test_hot_spots_and_surge_shapes() -> None:
    hot = mf.hot_spots()
    assert [h["name"] for h in hot] == ["Aliados", "Bolhão", "Trindade"]
    assert sum(h["w"] for h in hot) == pytest.approx(1.0)
    surge = mf.fixture_surge()
    assert surge["t0"] == mf.SURGE_T0 and surge["t1"] > surge["t0"]


def test_build_fixture_matches_the_contract_shape() -> None:
    data = mf.build_fixture()
    assert data["version"] == 1 and data["unit_m"] == mf.UNIT_M and len(data["shifts"]) == 1
    shift = data["shifts"][0]
    assert shift["id"] == "fix-am" and shift["nDrivers"] == mf.N_TAXIS == len(shift["taxis"])
    assert shift["ranking"] == sorted(shift["ranking"], reverse=True)
    assert shift["ghost"]["total"] == shift["ranking"][0]
    assert all(shift["orders"][i][11] == 0 for i in shift["ghost"]["orders"])
    assert len(shift["speed_by_hour"]) == 24


def test_main_is_deterministic_and_writes_the_committed_fixture(tmp_path: Path) -> None:
    out = tmp_path / "sub" / "mini.json"
    assert mf.main(["--out", str(out)]) == 0
    first = out.read_bytes()
    assert mf.main(["--out", str(out)]) == 0
    assert out.read_bytes() == first
    assert json.loads(first)["shifts"][0]["id"] == "fix-am"
    committed = Path(__file__).resolve().parent.parent / "game" / "fixture" / "mini.json"
    if committed.is_file():
        assert first == committed.read_bytes()
