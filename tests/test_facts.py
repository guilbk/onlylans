import json
from pathlib import Path

import pytest

from pipeline import facts

UNIT = 5


def order(x: float, y: float, km: float, t: int = 0):
    return [t, x / UNIT, y / UNIT, x / UNIT, y / UNIT, [], 60, km, 5.0, 0, 0, 0]


def shift(orders, hot=(), ghost_n=14, ghost_total=52.3):
    return {
        "id": "mon-am",
        "orders": orders,
        "hot": list(hot),
        "ghost": {"orders": list(range(ghost_n)), "total": ghost_total, "taxi": 0},
    }


@pytest.mark.parametrize(
    ("n", "form"),
    [(0, "m"), (1, "o"), (2, "f"), (4, "f"), (5, "m"), (11, "m"), (12, "m"), (14, "m"),
     (21, "o"), (22, "f"), (101, "o"), (111, "m"), (1234, "f")],
)  # fmt: skip
def test_plural_follows_ukrainian_rules(n: int, form: str) -> None:
    assert facts.plural(n, "o", "f", "m") == form


def test_number_formats() -> None:
    assert facts.thousands(1234) == "1 234"
    assert facts.thousands(12) == "12"
    assert facts.km_text(23.44) == "23,4 км"


def test_trips_fact_uses_plural_and_thousands() -> None:
    assert facts.trips_fact([None] * 1234) == "Справжні водії цієї зміни зробили 1 234 поїздки"
    assert facts.trips_fact([None] * 5).endswith("5 поїздок")
    assert facts.trips_fact([None]).endswith("1 поїздку")


def test_longest_fact_picks_longest_and_names_the_place() -> None:
    orders = [order(3000, 4000, 3.0), order(1000, 1000, 23.44), order(2000, 2000, 5.0)]
    text = facts.longest_fact(orders, UNIT)
    assert text is not None and text.startswith("Найдовша поїздка — 23,4 км з ")
    assert facts.longest_fact([], UNIT) is None


def test_longest_fact_far_point_is_a_suburb() -> None:
    text = facts.longest_fact([order(90000, 90000, 9.0)], UNIT)
    assert text is not None and text.endswith("з околиці")


def test_district_fact_takes_the_largest_share_and_drops_the_prefix() -> None:
    hot = [{"name": "Aliados", "w": 0.1}, {"name": "район Байша", "w": 0.3}]
    assert facts.district_fact(hot) == "Найзавантаженіший район — Байша"
    assert facts.district_fact([]) is None


def test_ghost_fact() -> None:
    assert facts.ghost_fact(shift([])) == "Привид зробив 14 поїздок, заробив €52,30"


def test_shift_facts_skip_what_the_data_cannot_support() -> None:
    assert (
        len(facts.shift_facts(shift([order(1000, 1000, 5.0)], [{"name": "Aliados", "w": 1}]), UNIT))
        == 4
    )
    assert len(facts.shift_facts(shift([]), UNIT)) == 2


def test_cli_is_deterministic_and_reports_missing_data(tmp_path: Path) -> None:
    data = tmp_path / "d.json"
    data.write_text(json.dumps({"unit_m": UNIT, "shifts": [shift([order(1000, 1000, 5.0)])]}))
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    assert facts.main(["--data", str(data), "--out", str(a)]) == 0
    assert facts.main(["--data", str(data), "--out", str(b)]) == 0
    assert a.read_bytes() == b.read_bytes()
    assert json.loads(a.read_text(encoding="utf-8"))["shifts"]["mon-am"][0].startswith("Справжні")
    assert facts.main(["--data", str(tmp_path / "none.json"), "--out", str(a)]) == 1
