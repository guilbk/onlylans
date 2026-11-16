"""Direct tests of the validator's building blocks (the documents come from test_validate)."""

import json
from pathlib import Path
from typing import Any

from pipeline import validate as v
from tests.test_validate import BOUNDS, make_doc, make_shift

ROADS_BOUNDS = (0, 0, 6000, 7600)  # the 15 x 19 km map in 2.5 m units


def rules(found: list[str]) -> set[str]:
    """Return the rule names of the violation strings."""
    return {x[1 : x.index("]")] for x in found}


def test_check_top_level_accepts_the_valid_header_and_names_each_break() -> None:
    doc = make_doc()
    assert v.check_top_level(doc) == []
    assert rules(v.check_top_level([])) == {"top"}
    assert len(v.check_top_level({**doc, "unit_m": 0})) == 1
    assert len(v.check_top_level({**doc, "bounds": [0, 0, 1, 1]})) == 1
    assert len(v.check_top_level({**doc, "generated": 5})) == 1
    assert len(v.check_top_level({**doc, "shifts": {}})) == 1
    assert len(v.check_top_level({**doc, "version": True})) == 1


def test_check_shift_ids_wants_28_ids_in_order() -> None:
    shifts = make_doc()["shifts"]
    assert v.check_shift_ids(shifts) == []
    assert rules(v.check_shift_ids(shifts[:-1])) == {"shift-ids"}
    swapped = [shifts[1], shifts[0], *shifts[2:]]
    assert len(v.check_shift_ids(swapped)) == 2
    assert len(v.check_shift_ids([*shifts[:-1], 5])) == 1


def test_check_shift_fields_reports_missing_extra_and_wrong_kinds() -> None:
    shift = make_shift()
    assert v.check_shift_fields(shift) == []
    broken = {k: val for k, val in shift.items() if k != "median"} | {"bogus": 1, "detour": "x"}
    assert rules(v.check_shift_fields(broken)) == {"shift-fields", "shift-types"}


def test_check_shift_values_checks_each_header_range() -> None:
    shift = make_shift()
    where = "shift mon-am"
    assert v.check_shift_values(shift, where) == []
    for key, bad in (
        ("slot", "dawn"),
        ("start_local", "12.05.2014 08:00"),
        ("difficulty", 9),
        ("start_hour", 24),
        ("speed_by_hour", [1.0] * 23),
    ):
        found = v.check_shift_values({**shift, key: bad}, where)
        assert rules(found) == {"shift-values"}, key


def test_check_shift_hours_compares_slot_hour_and_text() -> None:
    shift = make_shift()
    assert v.check_shift_hours(shift, "w") == []
    assert len(v.check_shift_hours({**shift, "slot": "pm"}, "w")) == 1
    assert len(v.check_shift_hours({**shift, "start_hour": 9}, "w")) == 2
    assert len(v.check_shift_hours({**shift, "start_local": "2014-05-12 07:00"}, "w")) == 1
    assert v.check_shift_hours({**shift, "id": 5}, "w") == []
    assert v.check_shift_hours({**shift, "start_hour": "8"}, "w") == []


def test_check_orders_flags_shape_unsorted_and_keeps_going() -> None:
    shift = make_shift()
    found, shapes_ok = v.check_orders(shift, BOUNDS)
    assert (found, shapes_ok) == ([], True)
    swapped = {**shift, "orders": [shift["orders"][2], shift["orders"][0], shift["orders"][1]]}
    found, shapes_ok = v.check_orders(swapped, BOUNDS)
    assert rules(found) == {"order-sorted"} and shapes_ok
    short = {**shift, "orders": [[1, 2], *shift["orders"]]}
    found, shapes_ok = v.check_orders(short, BOUNDS)
    assert rules(found) == {"order-arity"} and not shapes_ok


def test_check_shift_stops_at_wrong_kinds_and_empty_orders() -> None:
    assert rules(v.check_shift(5, BOUNDS)) == {"shift-types"}
    assert v.check_shift(make_shift(), BOUNDS) == []
    wrong_kind = {**make_shift(), "orders": "none"}
    assert rules(v.check_shift(wrong_kind, BOUNDS)) == {"shift-types"}
    empty = {**make_shift(), "orders": [], "taxis": [], "ranking": [], "nDrivers": 0}
    assert "shift-values" in rules(v.check_shift(empty, BOUNDS))


def test_check_roads_header_and_bounds() -> None:
    roads = {"v": 1, "unit_m": 2.5, "nodes": [0, 0], "edges": []}
    assert v.check_roads_header(roads) == []
    assert v.roads_bounds() == ROADS_BOUNDS
    assert rules(v.check_roads_header([])) == {"roads-header"}
    for key, bad in (("v", 2), ("unit_m", 5), ("nodes", [0]), ("edges", {})):
        assert len(v.check_roads_header({**roads, key: bad})) == 1, key


def test_check_roads_nodes_checks_bounds_and_sort_order() -> None:
    assert v.check_roads_nodes([0, 0, 5, 0, 0, 7]) == []
    assert rules(v.check_roads_nodes([0, 0, 9000, 0])) == {"roads-bounds"}
    assert rules(v.check_roads_nodes([5, 7, 0, 0])) == {"roads-sorted"}


def test_check_roads_edges_checks_shape_index_interior_and_sort() -> None:
    assert v.check_roads_edges([[0, 1, []], [1, 2, [10, 10]]], 3) == []
    assert rules(v.check_roads_edges([[0, 1]], 3)) == {"roads-edge"}
    assert rules(v.check_roads_edges([[0, 9, []]], 3)) == {"roads-index"}
    assert rules(v.check_roads_edges([[0, 1, [1]]], 3)) == {"roads-edge"}
    assert rules(v.check_roads_edges([[0, 1, [99999, 0]]], 3)) == {"roads-bounds"}
    assert rules(v.check_roads_edges([[1, 2, []], [0, 1, []]], 3)) == {"roads-sorted"}


def test_check_json_block_required_escape_and_invalid() -> None:
    page = '<script type="application/json" id="game-data">{"a": 1}</script>'
    assert v.check_json_block(page, "game-data", True) == ([], {"a": 1})
    found, parsed = v.check_json_block(page, "roads-data", True)
    assert rules(found) == {"html-data"} and parsed is None
    assert v.check_json_block(page, "roads-data", False) == ([], None)
    escaped = '<script id="game-data">{"a": "</b>"}</script>'
    assert "html-escape" in rules(v.check_json_block(escaped, "game-data", True)[0])
    bad = '<script id="game-data">{oops</script>'
    found, parsed = v.check_json_block(bad, "game-data", True)
    assert rules(found) == {"html-data"} and parsed is None


def test_load_json_reads_or_explains(tmp_path: Path) -> None:
    good = tmp_path / "a.json"
    good.write_text('{"k": 2}', encoding="utf-8")
    assert v.load_json(good) == ({"k": 2}, [])
    bad = tmp_path / "b.json"
    bad.write_text("{", encoding="utf-8")
    data, found = v.load_json(bad)
    assert data is None and rules(found) == {"file"}
    assert v.load_json(tmp_path / "missing.json")[0] is None


def write_json(path: Path, doc: Any) -> Path:
    """Write ``doc`` as JSON and return the path."""
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_run_data_returns_document_and_violations(tmp_path: Path) -> None:
    doc = make_doc()
    data, found = v.run_data(write_json(tmp_path / "d.json", doc))
    assert data == doc and found == []
    data, found = v.run_data(write_json(tmp_path / "e.json", {"version": 2}))
    assert data == {"version": 2} and "top" in rules(found)
    data, found = v.run_data(tmp_path / "missing.json")
    assert data is None and rules(found) == {"file"}


def test_run_roads_and_run_html(tmp_path: Path) -> None:
    roads = write_json(tmp_path / "r.json", {"v": 2})
    assert "roads-header" in rules(v.run_roads(roads))
    assert rules(v.run_roads(tmp_path / "missing.json")) == {"file"}
    html = tmp_path / "g.html"
    html.write_text("<html></html>", encoding="utf-8")
    assert rules(v.run_html(html, None)) == {"html-data"}
    assert rules(v.run_html(tmp_path / "missing.html", None)) == {"file"}


def test_run_optional_skips_missing_default_but_fails_missing_given(tmp_path: Path) -> None:
    missing = tmp_path / "nope.json"
    assert v.run_optional(None, missing, None, False) == (missing, None)
    path, found = v.run_optional(missing, tmp_path / "other.json", None, False)
    assert path == missing and found is not None and rules(found) == {"file"}
    roads = write_json(tmp_path / "r.json", {"v": 2})
    path, found = v.run_optional(None, roads, None, False)
    assert path == roads and found is not None and "roads-header" in rules(found)


def test_order_field_indices_match_the_contract() -> None:
    names = (v.F_T, v.F_X0, v.F_Y0, v.F_X1, v.F_Y1, v.F_PTS, v.F_D, v.F_KM, v.F_FARE)
    assert names == tuple(range(9))
    assert (v.F_CALL, v.F_STAND, v.F_TAXI) == (9, 10, 11)
    assert v.ORDER_LEN == len(v.ORDER_KINDS) == v.F_TAXI + 1
