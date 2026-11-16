import json
from pathlib import Path

import pytest

from pipeline import missions as ms

UNIT = 5
AX, AY = ms.AIRPORT


def order(x: float, y: float, km: float = 3.0, x1: float | None = None, y1: float | None = None):
    """Compact order with the pickup at (x, y) metres and the drop-off at (x1, y1)."""
    x1 = x if x1 is None else x1
    y1 = y if y1 is None else y1
    return [0, x / UNIT, y / UNIT, x1 / UNIT, y1 / UNIT, [], 60, km, 5.0, 0, 0, 0]


def shift(orders, hot=(), sid="mon-am", median=9.63):
    return {"id": sid, "orders": list(orders), "hot": list(hot), "median": median}


def hotspot(x=9000.0, y=12000.0, name="Aliados"):
    return {"x": x / UNIT, "y": y / UNIT, "w": 0.1, "name": name}


def plain_orders(n=100):
    return [order(9000 + i, 12000, km=1.0 + i * 0.1) for i in range(n)]


RIVALS = {"ze": 30.0, "fatima": 25.0, "rui": 20.0, "ines": 35.0, "tiago": 15.0, "lurdes": 22.0,
          "nuno": 9.0}  # fmt: skip


def test_percentile_nearest_rank() -> None:
    vals = [5, 1, 3, 2, 4, 10, 9, 8, 7, 6]
    assert ms.percentile(vals, 0.5) == 5
    assert ms.percentile(vals, 0.85) == 9
    assert ms.percentile(vals, 1.0) == 10
    assert ms.percentile([7], 0.85) == 7


def test_eur_and_genitive() -> None:
    assert ms.eur(9.6) == "€9,60"
    assert ms.genitive("район Boavista") == "району Boavista"
    assert ms.genitive("São Bento") == "São Bento"


def test_airport_needs_enough_trips() -> None:
    near = [order(AX + 100, AY), order(9000, 12000, x1=AX, y1=AY + 200), order(AX, AY - 1400)]
    assert ms.airport_mission(near[:2], UNIT) is None
    m = ms.airport_mission(near, UNIT)
    assert m and m["kind"] == "airport" and m["r"] == ms.AIRPORT_R_M and m["n"] == 1
    far = [order(AX + 1600, AY)] * 5
    assert ms.airport_mission(far, UNIT) is None


def test_district_picks_busiest_named_hotspot() -> None:
    orders = [order(9000, 12000)] * 12 + [order(5000, 5000)] * 20
    hot = [hotspot(5000, 5000, "район Boavista"), hotspot(9000, 12000, "Aliados")]
    m = ms.district_mission(orders, hot, UNIT)
    assert m["title"] == "Відвези 3 пасажирів з району Boavista"
    assert (m["x"], m["y"], m["r"], m["n"]) == (5000, 5000, ms.DISTRICT_R_M, 3)
    far = [hotspot(5000, 5000, ms.NO_PLACE)]
    assert ms.district_mission(orders, far, UNIT) is None
    assert ms.district_mission(orders[:5], [hotspot()], UNIT) is None


def test_long_threshold_comes_from_the_shift() -> None:
    short = [order(0, 0, km=1.0 + 0.1 * i) for i in range(100)]  # 1.0 .. 10.9
    longer = [order(0, 0, km=2.0 * (1.0 + 0.1 * i)) for i in range(100)]
    a, b = ms.long_mission(short), ms.long_mission(longer)
    assert a["km"] == 9.5 and b["km"] == 19.0  # 85th percentile, rounded to 0.5
    assert a["title"] == "Довга поїздка від 9,5 км"
    tiny = ms.long_mission([order(0, 0, km=1.0)] * 20)
    assert tiny["km"] == ms.LONG_MIN_KM
    assert ms.long_mission([]) is None


def test_rival_is_the_strongest_one_the_player_matches() -> None:
    m = ms.rival_mission(RIVALS, 21.0, "mon-am")
    assert m["rival"] == "rui" and m["title"] == "Обжени Камран «Сова» за гроші"
    assert ms.rival_mission(RIVALS, 5.0, "mon-am")["rival"] == "nuno"  # all above: the weakest
    assert ms.rival_mission(None, 5.0, "mon-am") is None


def test_median_rounds_up_to_cents() -> None:
    m = ms.median_mission(9.63)
    assert m["eur"] == 9.63 and m["by"] == 3600 and "€9,63" in m["title"]
    assert ms.median_mission(9.631)["eur"] == 9.64


def test_pick_three_distinct_and_deterministic() -> None:
    sh = shift(plain_orders(), [hotspot()])
    a = ms.pick_missions(sh, UNIT, RIVALS, 21.0)
    assert a == ms.pick_missions(sh, UNIT, RIVALS, 21.0)
    assert len(a) == ms.PER_SHIFT
    assert [m["id"] for m in a] == ["m1", "m2", "m3"]
    kinds = [m["kind"] for m in a]
    assert len(set(kinds)) == 3 and set(kinds) <= set(ms.KINDS)
    assert all(m["title"] and m["short"] and m["n"] >= 1 for m in a)


def test_pick_airport_first_when_supported() -> None:
    orders = plain_orders() + [order(AX, AY)] * 4
    got = ms.pick_missions(shift(orders, [hotspot()]), UNIT, RIVALS, 21.0)
    assert got[0]["kind"] == "airport"
    no_air = ms.pick_missions(shift(plain_orders(), [hotspot()]), UNIT, RIVALS, 21.0)
    assert "airport" not in [m["kind"] for m in no_air]


def test_pick_without_rivals_or_hotspots_still_gives_three() -> None:
    got = ms.pick_missions(shift(plain_orders()), UNIT)
    kinds = {m["kind"] for m in got}
    assert len(got) == 3 and kinds <= {"long", "combo", "median"}


def test_order_varies_between_shifts() -> None:
    orders = plain_orders()
    sets = {
        tuple(
            m["kind"]
            for m in ms.pick_missions(shift(orders, [hotspot()], sid=f"s{i}"), UNIT, RIVALS, 21.0)
        )
        for i in range(20)
    }
    assert len(sets) > 1


def test_build_missions_and_cli(tmp_path: Path) -> None:
    data = {
        "unit_m": UNIT,
        "shifts": [shift(plain_orders(), [hotspot()], sid=f"s{i}") for i in range(3)],
    }
    doc = ms.build_missions(data)
    assert doc["version"] == 1 and list(doc["shifts"]) == ["s0", "s1", "s2"]
    assert all(len(v) == 3 for v in doc["shifts"].values())
    assert all(m["kind"] != "rival" for v in doc["shifts"].values() for m in v)
    totals = {"s1": (RIVALS, 21.0)}
    with_rival = ms.build_missions(data, totals)
    assert with_rival["shifts"]["s0"] == doc["shifts"]["s0"]
    src, out = tmp_path / "d.json", tmp_path / "out" / "m.json"
    src.write_text(json.dumps(data), encoding="utf-8")
    assert ms.main(["--data", str(src), "--out", str(out), "--no-rivals"]) == 0
    assert json.loads(out.read_text(encoding="utf-8")) == doc
    assert ms.main(["--data", str(tmp_path / "nope.json"), "--out", str(out)]) == 1


@pytest.mark.skipif(not Path("game/game_data.json").is_file(), reason="real data not present")
def test_real_data_every_shift_has_three_missions() -> None:
    data = json.loads(Path("game/game_data.json").read_text(encoding="utf-8"))
    doc = ms.build_missions(data)
    assert len(doc["shifts"]) == 28
    for sid, got in doc["shifts"].items():
        assert len(got) == 3, sid
        assert len({m["kind"] for m in got}) == 3, sid
