import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pipeline import geo
from pipeline import validate as v

BOUNDS = (0, 0, 3000, 3800)
Doc = dict[str, Any]


def make_shift(
    shift_id: str = "mon-am", start_hour: int | None = None, fare: float | None = None
) -> Doc:
    """One valid shift: taxi 0 drives orders 0 and 2, taxi 1 drives order 1."""

    def order(t: int, taxi: int) -> list[Any]:
        return [t, 10, 10, 40, 10, [10, 0, 10, 0, 10, 0], 45, 1.5, fare, 0, 0, taxi]

    if start_hour is None:
        start_hour = v.expected_start_hour(shift_id) or 0
    if fare is None:  # 3.25 + 0.50 * 1.5 km = 4.00 EUR, x1.2 = 4.80 EUR at night
        fare = 4.8 if geo.night_hour(start_hour) else 4.0
    return {
        "id": shift_id,
        "name": "Ранок",
        "day": "понеділок",
        "slot": shift_id.split("-")[1],
        "start_local": f"2014-05-12 {start_hour:02d}:00",
        "start_hour": start_hour,
        "difficulty": 3,
        "nDrivers": 2,
        "orders": [order(100, 0), order(200, 1), order(300, 0)],
        "taxis": [101, 202],
        "ranking": [2 * fare, fare],
        "ghost": {"taxi": 0, "total": 2 * fare, "orders": [0, 2]},
        "median": 1.5 * fare,
        "top10": 2 * fare,
        "speed_by_hour": [20.0] * 24,
        "detour": 1.3,
        "hot": [{"x": 100, "y": 100, "w": 0.5, "name": "A"}],
        "surges": [{"x": 100, "y": 100, "r": 20, "t0": 150, "t1": 900, "n": 3, "name": "S"}],
    }


def make_doc() -> Doc:
    """A valid 28-shift document."""
    shifts = [make_shift(sid) for sid in v.expected_shift_ids()]
    return {
        "version": 1,
        "unit_m": 5,
        "bounds": [0, 0, 3000, 3800],
        "generated": "test",
        "shifts": shifts,
    }


def rules_of(found: list[str]) -> set[str]:
    return {x[1 : x.index("]")] for x in found}


def test_valid_document_has_no_violations() -> None:
    assert v.validate_data(make_doc()) == []


def set_shift(key: str, value: Any) -> Callable[[Doc], None]:
    def mutate(doc: Doc) -> None:
        doc["shifts"][0][key] = value

    return mutate


def set_order(index: int, field: int, value: Any) -> Callable[[Doc], None]:
    def mutate(doc: Doc) -> None:
        doc["shifts"][0]["orders"][index][field] = value

    return mutate


def del_shift_key(key: str) -> Callable[[Doc], None]:
    def mutate(doc: Doc) -> None:
        del doc["shifts"][0][key]

    return mutate


def swap_ids(doc: Doc) -> None:
    doc["shifts"][0]["id"], doc["shifts"][1]["id"] = "mon-lunch", "mon-am"


def pop_order_field(doc: Doc) -> None:
    doc["shifts"][0]["orders"][0].pop()


def unsort_orders(doc: Doc) -> None:
    doc["shifts"][0]["orders"][0][0] = 250


def swap_ranking(doc: Doc) -> None:
    doc["shifts"][0]["ranking"].reverse()


def tie_wrong_taxi_order(doc: Doc) -> None:
    s = doc["shifts"][0]
    s["orders"][2][8] = 0.0  # taxi 0 now earns 4.0, like taxi 1
    s["ranking"] = [4.0, 4.0]
    s["taxis"] = [202, 101]
    s["ghost"]["total"] = 4.0
    s["median"] = s["top10"] = 4.0


def lose_pts_delta(doc: Doc) -> None:
    doc["shifts"][0]["orders"][0][5] = [10, 0, 10, 0]


def shift_ghost(key: str, value: Any) -> Callable[[Doc], None]:
    def mutate(doc: Doc) -> None:
        doc["shifts"][0]["ghost"][key] = value

    return mutate


def set_surge(key: str, value: Any) -> Callable[[Doc], None]:
    def mutate(doc: Doc) -> None:
        doc["shifts"][0]["surges"][0][key] = value

    return mutate


def set_hot(key: str, value: Any) -> Callable[[Doc], None]:
    def mutate(doc: Doc) -> None:
        doc["shifts"][0]["hot"][0][key] = value

    return mutate


def drop_shift(doc: Doc) -> None:
    doc["shifts"].pop()


def extra_key(doc: Doc) -> None:
    doc["extra"] = 1


def nan_unit(doc: Doc) -> None:
    doc["unit_m"] = "5"


def no_orders(doc: Doc) -> None:
    doc["shifts"][0]["orders"] = []


BROKEN: list[tuple[str, Callable[[Doc], None]]] = [
    ("top", extra_key),
    ("top", lambda d: d.update(version=2)),
    ("top", lambda d: d.update(bounds=[0, 0, 3000, 3801])),
    ("top", nan_unit),
    ("top", lambda d: d.update(generated=7)),
    ("shift-ids", drop_shift),
    ("shift-ids", swap_ids),
    ("shift-fields", del_shift_key("detour")),
    ("shift-types", set_shift("median", "x")),
    ("shift-types", set_shift("nDrivers", True)),
    ("shift-values", set_shift("slot", "dawn")),
    ("shift-values", set_shift("difficulty", 6)),
    ("shift-values", set_shift("start_hour", 24)),
    ("shift-values", set_shift("start_local", "12.05.2014")),
    ("shift-hours", set_shift("start_hour", 9)),
    ("shift-hours", set_shift("start_local", "2014-05-12 09:00")),
    ("shift-hours", set_shift("slot", "pm")),
    ("shift-values", set_shift("speed_by_hour", [20.0] * 23)),
    ("shift-values", no_orders),
    ("order-arity", pop_order_field),
    ("order-types", set_order(0, 1, 1.5)),
    ("order-types", set_order(0, 5, "abc")),
    ("order-t", set_order(0, 0, 7200)),
    ("order-t", set_order(0, 0, -1)),
    ("order-bounds", set_order(0, 1, 3001)),
    ("order-bounds", set_order(0, 4, 3801)),
    ("order-bounds", set_order(0, 5, [3000, 0, 10, 0, 10, 0])),
    ("order-km", set_order(0, 7, 0)),
    ("order-call", set_order(0, 9, 3)),
    ("order-stand", set_order(0, 10, -1)),
    ("order-taxi", set_order(0, 11, 2)),
    ("order-pts", set_order(0, 5, [10, 0, 10, 0, 10])),
    ("order-pts", set_order(0, 3, 41)),
    ("order-pts", lose_pts_delta),
    ("order-d", set_order(0, 6, 60)),
    ("order-fare", set_order(0, 8, 4.01)),
    ("order-sorted", unsort_orders),
    ("ranking", swap_ranking),
    ("ranking", tie_wrong_taxi_order),
    ("ranking", set_shift("nDrivers", 3)),
    ("ranking-total", set_shift("ranking", [8.0, 3.99])),
    ("ghost", shift_ghost("taxi", 1)),
    ("ghost", shift_ghost("total", 7.5)),
    ("ghost", shift_ghost("orders", [0, 1])),
    ("median", set_shift("median", 7.0)),
    ("top10", set_shift("top10", 4.0)),
    ("hot", set_hot("w", 1.5)),
    ("hot", set_hot("x", 3001)),
    ("surge", set_surge("r", 0)),
    ("surge", set_surge("y", 3801)),
    ("surge", set_surge("t0", 150.5)),
    ("surge-time", set_surge("t0", 149)),
    ("surge-time", set_surge("t1", 7201)),
    ("surge-time", set_surge("t1", 150)),
]


@pytest.mark.parametrize(("rule", "mutate"), BROKEN)
def test_each_rule_catches_its_break(rule: str, mutate: Callable[[Doc], None]) -> None:
    doc = make_doc()
    mutate(doc)
    found = v.validate_data(doc)
    assert rule in rules_of(found), found


def test_fare_uses_local_pickup_hour_and_night_factor() -> None:
    doc = make_doc()
    doc["shifts"][3] = make_shift("mon-night", start_hour=22, fare=4.8)
    assert v.validate_data(doc) == []
    doc["shifts"][3] = make_shift("mon-night", start_hour=22, fare=4.0)
    assert "order-fare" in rules_of(v.validate_data(doc))


def test_night_shift_crossing_midnight_changes_fare_by_hour() -> None:
    order = [7300, 10, 10, 40, 10, [10, 0, 10, 0, 10, 0], 45, 1.5, 4.8, 0, 0, 0]
    assert v.check_order_fare(order, 22) == []  # 22:00 + 2 h = 00:00, still night
    assert v.check_order_fare(order, 4) != []  # 04:00 + 2 h = 06:00, day fare is 4.0


def test_not_an_object_and_non_list_shifts() -> None:
    assert rules_of(v.validate_data([])) == {"top"}
    doc = make_doc()
    doc["shifts"] = {}
    assert "top" in rules_of(v.validate_data(doc))
    doc = make_doc()
    doc["shifts"][5] = 7
    assert "shift-types" in rules_of(v.validate_data(doc))


def test_helpers_is_int_is_num_kind_ok() -> None:
    assert v.is_int(3) and not v.is_int(3.0) and not v.is_int(True)
    assert v.is_num(3) and v.is_num(2.5) and not v.is_num(False) and not v.is_num("1")
    assert v.kind_ok("a", "str") and v.kind_ok([], "list") and v.kind_ok({}, "dict")
    assert not v.kind_ok({}, "list") and not v.kind_ok(1.5, "int") and v.kind_ok(1, "num")


def test_in_bounds_includes_edges() -> None:
    assert v.in_bounds(0, 0, BOUNDS) and v.in_bounds(3000, 3800, BOUNDS)
    assert not v.in_bounds(-1, 0, BOUNDS) and not v.in_bounds(0, 3801, BOUNDS)


def test_expected_shift_ids_order() -> None:
    ids = v.expected_shift_ids()
    assert len(ids) == 28
    assert ids[:5] == ["mon-am", "mon-lunch", "mon-pm", "mon-night", "tue-am"]
    assert ids[-1] == "sun-night"


@pytest.mark.parametrize(
    ("shift_id", "hour"),
    [("mon-am", 8), ("tue-lunch", 12), ("wed-pm", 17), ("thu-night", 22), ("sat-night", 0)],
)
def test_expected_start_hour(shift_id: str, hour: int) -> None:
    assert v.expected_start_hour(shift_id) == hour
    assert v.expected_start_hour("mon-dawn") is None


def test_viol_format() -> None:
    assert v.viol("rule", "shift x", "bad") == "[rule] shift x: bad"


def test_check_order_functions_directly() -> None:
    order = make_shift()["orders"][0]
    assert v.check_order_shape(order) == []
    assert v.check_order_units(order, BOUNDS, 2) == []
    assert v.check_order_path(order, BOUNDS) == []
    assert v.check_order_fare(order, 8) == []
    assert v.check_order_shape("x")[0].startswith("[order-arity]")
    second = make_shift()["orders"][1]  # taxi index 1
    assert v.check_order_units(second, BOUNDS, 1)[0].startswith("[order-taxi]")
    assert v.check_order_path([*order[:5], [1], *order[6:]], BOUNDS)[0].startswith("[order-pts]")
    assert v.check_order_fare(order, 22)[0].startswith("[order-fare]")


def test_path_too_short_or_long_is_flagged() -> None:
    order = make_shift()["orders"][0]
    short = [*order[:5], [20, 0, 20, 0], 30, *order[7:]]
    assert any("points" in x for x in v.check_order_path(short, BOUNDS))
    long_pts = [1, 0] * (v.MAX_RIDE_POINTS)  # n = 241 points
    big = [0, 0, 0, v.MAX_RIDE_POINTS, 0, long_pts, 15 * v.MAX_RIDE_POINTS, 1.0, 3.75, 0, 0, 0]
    big[3] = v.MAX_RIDE_POINTS
    assert any("points" in x for x in v.check_order_path(big, BOUNDS))


def test_check_ranking_and_summary_directly() -> None:
    shift = make_shift()
    assert v.check_ranking_order(shift) == []
    assert v.check_ranking_totals(shift) == []
    assert v.check_ghost(shift) == []
    assert v.check_summary(shift) == []
    shift["median"] = 6.004  # a median rounded to cents stays within tolerance
    assert v.check_summary(shift) == []
    shift["median"] = 6.02
    assert v.check_summary(shift)[0].startswith("[median]")


def test_top10_index_for_many_drivers() -> None:
    shift = make_shift()
    shift["ranking"] = [float(x) for x in range(25, 0, -1)]
    shift["median"] = 13.0
    shift["top10"] = 23.0  # ceil(0.10 * 25) - 1 = 2 -> third value
    assert v.check_summary(shift) == []
    shift["top10"] = 24.0
    assert v.check_summary(shift)[0].startswith("[top10]")


def test_check_surge_and_places_directly() -> None:
    surge = {"x": 1, "y": 1, "r": 5, "t0": 150, "t1": 7200, "n": 2, "name": "S"}
    assert v.check_surge(surge, "w", BOUNDS) == []
    assert v.check_surge({**surge, "t1": 7201}, "w", BOUNDS)
    assert v.check_surge({**surge, "extra": 1}, "w", BOUNDS)
    assert v.check_places(make_shift(), BOUNDS) == []


@pytest.mark.parametrize(("size", "limit", "bad"), [(10, 10, False), (11, 10, True)])
def test_check_file_size(size: int, limit: int, bad: bool) -> None:
    assert bool(v.check_file_size(size, limit, "f")) is bad


def make_roads() -> Doc:
    return {
        "v": 1,
        "unit_m": 2.5,
        "nodes": [0, 0, 10, 0, 10, 10],
        "edges": [[0, 1, []], [1, 2, [12, 5]]],
    }


def set_roads(key: str, value: Any) -> Callable[[Doc], None]:
    def mutate(doc: Doc) -> None:
        doc[key] = value

    return mutate


ROADS_BROKEN: list[tuple[str, Callable[[Doc], None]]] = [
    ("roads-header", set_roads("v", 2)),
    ("roads-header", set_roads("unit_m", 5)),
    ("roads-header", set_roads("nodes", [0, 0, 10])),
    ("roads-header", set_roads("nodes", [0.5, 0, 10, 0, 10, 10])),
    ("roads-header", set_roads("edges", {})),
    ("roads-header", set_roads("extra", 1)),
    ("roads-bounds", set_roads("nodes", [0, 0, 10, 0, 6001, 10])),
    ("roads-bounds", set_roads("edges", [[0, 1, []], [1, 2, [6001, 5]]])),
    ("roads-sorted", set_roads("nodes", [10, 0, 0, 0, 10, 10])),
    ("roads-sorted", set_roads("edges", [[1, 2, []], [0, 1, []]])),
    ("roads-index", set_roads("edges", [[0, 1, []], [1, 3, []]])),
    ("roads-index", set_roads("edges", [[0, 1, []], [1, -1, []]])),
    ("roads-edge", set_roads("edges", [[0, 1], [1, 2, []]])),
    ("roads-edge", set_roads("edges", [[0, 1, []], [1, 2, [1]]])),
    ("roads-connected", set_roads("edges", [[0, 1, []]])),
    ("roads-connected", set_roads("nodes", [0, 0, 10, 0, 10, 10, 20, 20])),
]


def test_valid_roads_pass() -> None:
    assert v.validate_roads(make_roads()) == []


@pytest.mark.parametrize(("rule", "mutate"), ROADS_BROKEN)
def test_each_roads_rule_catches_its_break(rule: str, mutate: Callable[[Doc], None]) -> None:
    roads = make_roads()
    mutate(roads)
    found = v.validate_roads(roads)
    assert rule in rules_of(found), found


def test_validate_roads_rejects_a_non_object() -> None:
    assert rules_of(v.validate_roads([])) == {"roads-header"}


def test_count_components() -> None:
    assert v.count_components(0, []) == 0
    assert v.count_components(3, [[0, 1], [1, 2]]) == 1
    assert v.count_components(4, [[0, 1], [2, 3]]) == 2
    assert v.count_components(3, [[0, 1]]) == 2  # node 2 is isolated


def make_html(data: Doc | None = None, roads: str | None = None) -> str:
    payload = json.dumps(data if data is not None else {"a": 1}).replace("</", "<\\/")
    head = '<html><style>b{}</style><script type="application/json" id="game-data">'
    html = f"{head}{payload}</script>"
    if roads is not None:
        html += f'<script type="application/json" id="roads-data">{roads}</script>'
    return html + "<script>var x = 1;</script></html>"


def test_valid_html_passes() -> None:
    assert v.check_html(make_html(), {"a": 1}) == []
    assert v.check_html(make_html(roads='{"v":1}')) == []


def test_extract_script() -> None:
    html = make_html()
    assert v.extract_script(html, "game-data") == '{"a": 1}'
    assert v.extract_script(html, "roads-data") is None
    assert v.extract_script(html.replace("id=", "ID="), "game-data") == '{"a": 1}'


@pytest.mark.parametrize(
    ("rule", "html"),
    [
        ("html-placeholder", make_html() + "/*__CSS__*/"),
        ("html-placeholder", make_html() + "<!--__DATA__-->"),
        ("html-placeholder", make_html() + "<!--__JS__-->"),
        ("html-data", "<html></html>"),
        ("html-data", make_html().replace('{"a": 1}', "{nope")),
        ("html-data", make_html(roads="{broken")),
        ("html-escape", make_html().replace('{"a": 1}', '{"a": "</b>"}')),
        ("html-data", make_html().replace('{"a": 1}', '{"a": "</script>"}')),
        ("html-script", make_html().replace('{"a": 1}', '{"a": "</script>"}')),
        ("html-script", make_html() + "<script>"),
    ],
)
def test_each_html_rule_catches_its_break(rule: str, html: str) -> None:
    assert rule in rules_of(v.check_html(html)), v.check_html(html)


def test_html_data_must_match_the_data_file() -> None:
    found = v.check_html(make_html({"a": 2}), {"a": 1})
    assert rules_of(found) == {"html-data"}


def test_summarize_limits_each_rule() -> None:
    lines = [f"[a] x{i}: bad" for i in range(5)] + ["[b] y: bad"]
    out = v.summarize(lines, limit=2)
    assert out == ["[a] x0: bad", "[a] x1: bad", "[a] ... and 3 more", "[b] y: bad"]
    assert v.summarize([]) == []


def test_format_report() -> None:
    lines = v.format_report([("a.json", []), ("b.json", ["[r] w: d"]), ("c.html", None)])
    assert lines == [
        "a.json: OK",
        "b.json: 1 violation(s)",
        "  [r] w: d",
        "c.html: not found, skipped",
        "RESULT: 1 violation(s)",
    ]
    assert v.format_report([("a", [])])[-1] == "RESULT: OK"


def write_game(tmp_path: Path, doc: Doc) -> Path:
    path = tmp_path / "game_data.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


def test_main_ok_on_valid_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    doc = make_doc()
    data = write_game(tmp_path, doc)
    roads = tmp_path / "roads.json"
    roads.write_text(json.dumps(make_roads()), encoding="utf-8")
    html = tmp_path / "index.html"
    html.write_text(make_html(doc), encoding="utf-8")
    argv = ["--data", str(data), "--roads", str(roads), "--html", str(html)]
    assert v.main(argv) == 0
    out = capsys.readouterr().out
    assert "RESULT: OK" in out and out.count(": OK") == 3 + 1  # three files and the RESULT line


def test_main_lists_violations_and_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    doc = make_doc()
    doc["shifts"][0]["orders"][0][8] = 9.99
    data = write_game(tmp_path, doc)
    assert v.main(["--data", str(data)]) == 1
    out = capsys.readouterr().out
    assert "[order-fare] shift mon-am order 0" in out
    assert "roads.json: not found, skipped" in out
    assert "RESULT:" in out and "violation(s)" in out


def test_main_missing_or_broken_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert v.main(["--data", str(tmp_path / "none.json")]) == 1
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert v.main(["--data", str(bad)]) == 1
    data = write_game(tmp_path, make_doc())
    assert v.main(["--data", str(data), "--roads", str(tmp_path / "missing.json")]) == 1
    assert v.main(["--data", str(data), "--html", str(tmp_path / "missing.html")]) == 1
    assert v.main(["--data", str(data)]) == 0


def test_main_rejects_oversized_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(v, "DATA_MAX_BYTES", 100)
    assert v.main(["--data", str(write_game(tmp_path, make_doc()))]) == 1


def test_inputs_are_not_mutated() -> None:
    doc = make_doc()
    before = copy.deepcopy(doc)
    v.validate_data(doc)
    assert doc == before
