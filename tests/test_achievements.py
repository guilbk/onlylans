import json
from pathlib import Path

import pytest

from pipeline import achievements as ac

UNIT = 5
AX, AY = ac.AIRPORT


def order(x: float, y: float, km: float = 3.0, x1: float | None = None, y1: float | None = None):
    """Compact order with the pickup at (x, y) metres and the drop-off at (x1, y1)."""
    x1 = x if x1 is None else x1
    y1 = y if y1 is None else y1
    return [0, x / UNIT, y / UNIT, x1 / UNIT, y1 / UNIT, [], 60, km, 5.0, 0, 0, 0]


def shift(sid, slot, orders, hot=(), median=10.0):
    return {"id": sid, "slot": slot, "orders": list(orders), "hot": list(hot), "median": median}


def hot(name, x, y):
    return {"name": name, "x": x / UNIT, "y": y / UNIT, "w": 0.1}


def data():
    air = [order(AX, AY), order(9000, 9000, x1=AX, y1=AY), order(AX + 10, AY)]
    plain = [order(9000 + i, 9000, km=1.0 + i * 0.1) for i in range(100)]
    return {
        "unit_m": UNIT,
        "shifts": [
            shift("mon-am", "am", plain, [hot("Aliados", 9000, 9000)]),
            shift(
                "mon-night",
                "night",
                air,
                [hot("Aliados", 9100, 9000), hot("São Bento", 5000, 5000)],
            ),
            shift("sat-night", "night", plain, [hot("Marquês", 7000, 7000)]),
            shift("sun-pm", "pm", plain),
        ],
    }  # fmt: skip


def test_percentile_nearest_rank() -> None:
    assert ac.percentile([5, 1, 3, 2, 4, 10, 9, 8, 7, 6], 0.95) == 10
    assert ac.percentile([7], 0.95) == 7


def test_districts_are_distinct_sorted_and_in_metres() -> None:
    got = ac.districts(data()["shifts"], UNIT)
    assert [d["name"] for d in got] == ["Aliados", "Marquês", "São Bento"]
    assert got[0] == {"name": "Aliados", "x": 9000, "y": 9000}  # first seen position wins


def test_airport_trips_per_shift() -> None:
    assert ac.airport_trips(data()["shifts"], UNIT) == [0, 3, 0, 0]


def test_twelve_badges_with_thresholds_from_data() -> None:
    doc = ac.build_achievements(data())
    b = {x["id"]: x for x in doc["badges"]}
    assert doc["version"] == 1 and len(doc["badges"]) == 12 and len(b) == 12
    assert b["night"]["n"] == 1  # 2 night shifts, half of them
    assert b["week"]["n"] == 3  # mon, sat, sun
    assert b["airport"]["n"] == 3 and b["airport"]["r"] == ac.AIRPORT_R_M
    assert b["districts"]["n"] == 3 and len(b["districts"]["spots"]) == 3
    assert b["long"]["km"] == 10.5 and b["long"]["km"] % 0.5 == 0  # p95 of 1.0..10.9, rounded
    assert b["money"]["eur"] == 100 and b["money"]["n"] == 100  # 10 median shifts of €10
    assert doc["weekend"] == ["sat", "sun"]
    for x in doc["badges"]:
        assert x["icon"] and x["title"] and x["desc"] and x["n"] >= 1


def test_cli_roundtrip_and_error(tmp_path: Path) -> None:
    src, out = tmp_path / "d.json", tmp_path / "o" / "a.json"
    src.write_text(json.dumps(data()), encoding="utf-8")
    assert ac.main(["--data", str(src), "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8")) == ac.build_achievements(data())
    assert "\n" not in out.read_text(encoding="utf-8")
    assert ac.main(["--data", str(tmp_path / "nope.json"), "--out", str(out)]) == 1


@pytest.mark.skipif(not Path("game/game_data.json").is_file(), reason="real data not present")
def test_real_data() -> None:
    doc = ac.build_achievements(json.loads(Path("game/game_data.json").read_text(encoding="utf-8")))
    b = {x["id"]: x for x in doc["badges"]}
    assert len(b) == 12 and b["night"]["n"] == 4 and b["week"]["n"] == 7
    assert b["long"]["km"] > 4 and b["districts"]["n"] >= 5
