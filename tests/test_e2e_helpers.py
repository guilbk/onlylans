import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import e2e  # noqa: E402
from e2e import Outcome  # noqa: E402


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("#37 з 212", (37, 212)),
        ("#1 з 5 водіїв", (1, 5)),
        ("  # 12  з  300", (12, 300)),
        ("#– з 212", None),
        ("", None),
    ],
)
def test_parse_rank(text: str, want: tuple[int, int] | None) -> None:
    assert e2e.parse_rank(text) == want


@pytest.mark.parametrize(
    ("value", "want"),
    [
        ("#FF8A3D", "#ff8a3d"),
        ("#fff", "#ffffff"),
        ("rgb(255, 138, 61)", "#ff8a3d"),
        ("rgba(0,0,0,0.5)", "#000000"),
        ("rgb(300, 0, 0)", None),
        ("orange", None),
    ],
)
def test_normalise_colour(value: str, want: str | None) -> None:
    assert e2e.normalise_colour(value) == want


def test_distinct_colours() -> None:
    assert e2e.distinct_colours(["#ff8a3d", "#f4d03f", "rgb(255, 255, 255)"])
    assert not e2e.distinct_colours(["#ffffff", "#FFF"])
    assert not e2e.distinct_colours(["#ffffff", "red"])
    assert not e2e.distinct_colours([])


def test_pick_evenly() -> None:
    assert e2e.pick_evenly([1, 2, 3], 5) == [1, 2, 3]
    assert e2e.pick_evenly(list(range(100)), 4) == [0, 25, 50, 75]
    assert e2e.pick_evenly([1, 2], 0) == []
    picked = e2e.pick_evenly(list(range(167)), 20)
    assert len(picked) == len(set(picked)) == 20


def test_group_by_time_keeps_first_sighting() -> None:
    pairs = [(150.0, 3), (150.0, 4), (300.0, 3), (300.0, 5), (450.0, 4)]
    assert e2e.group_by_time(pairs) == [(150.0, [3, 4]), (300.0, [5])]
    assert e2e.group_by_time([]) == []


def _pin(px: float, py: float, reach: bool = True) -> dict[str, float | bool]:
    return {"i": 0, "px": px, "py": py, "reach": reach}


def test_pick_isolated_pin() -> None:
    near_a, near_b = _pin(100, 100), _pin(110, 100)
    alone = _pin(300, 200)
    grey = _pin(50, 50, reach=False)
    low = _pin(200, 700)
    assert e2e.pick_isolated_pin([near_a, near_b, alone, grey, low], max_y=400) is alone
    assert e2e.pick_isolated_pin([near_a, near_b], max_y=400) is None
    assert e2e.pick_isolated_pin([low], max_y=400) is None
    assert e2e.pick_isolated_pin([_pin(1, 1)], max_y=400) is not None


def test_in_viewport() -> None:
    assert e2e.in_viewport({"x": 10, "y": 10, "width": 50, "height": 20}, 390, 844)
    assert not e2e.in_viewport({"x": 10, "y": 900, "width": 50, "height": 20}, 390, 844)
    assert not e2e.in_viewport({"x": -60, "y": 10, "width": 50, "height": 20}, 390, 844)
    assert not e2e.in_viewport({"x": 10, "y": 10, "width": 0, "height": 20}, 390, 844)
    assert not e2e.in_viewport(None, 390, 844)


def test_judge_takeable() -> None:
    ok = {"i": 1, "t": 150.0, "reach": True, "took": True, "mode": "pickup"}
    unreachable = {"i": 2, "t": 300.0, "reach": False, "took": False, "mode": "idle"}
    refused = {"i": 3, "t": 450.0, "reach": True, "took": False, "mode": "idle"}
    assert e2e.judge_takeable([ok]) == []
    problems = e2e.judge_takeable([ok, unreachable, refused])
    assert len(problems) == 2
    assert "order 2" in problems[0]
    assert "order 3" in problems[1]


def _rank(text: str, rank: int, n: int = 212) -> dict[str, object]:
    return {"text": text, "rank": rank, "nDrivers": n, "ghostMoney": 0.0}


def test_judge_rank_samples() -> None:
    good = [_rank("#3 з 212", 3), _rank("#5 з 212", 5)]
    assert e2e.judge_rank_samples(good) == []
    assert "never changed" in e2e.judge_rank_samples([good[0], good[0]])[0]
    mismatch = e2e.judge_rank_samples([_rank("#3 з 212", 4)])
    assert "HUD (3, 212)" in mismatch[0]
    assert "no «#N з M»" in e2e.judge_rank_samples([_rank("#– з …", 1)])[0]


def _ghost(x: float, y: float, money: float) -> dict[str, float]:
    return {"gx": x, "gy": y, "ghostMoney": money}


def test_judge_ghost_samples() -> None:
    assert e2e.judge_ghost_samples([_ghost(100, 100, 0), _ghost(200, 150, 8.5)]) == []
    still = e2e.judge_ghost_samples([_ghost(100, 100, 0), _ghost(100, 100, 0)])
    assert still == ["ghost never moved"]
    off = e2e.judge_ghost_samples([_ghost(-5, 100, 0), _ghost(200, 150, 1)])
    assert "off the map" in off[0]
    fell = e2e.judge_ghost_samples([_ghost(1, 1, 9), _ghost(2, 2, 4)])
    assert "money fell" in fell[0]
    nan = e2e.judge_ghost_samples([_ghost(float("nan"), 1, 0), _ghost(2, 2, 0)])
    assert "off the map" in nan[0]


def test_missing_about_parts() -> None:
    text = "Джерело UCI, CC BY 4.0. Це дані ... Це ігрова модель ..."
    assert e2e.missing_about_parts(text, 7, 7) == []
    missing = e2e.missing_about_parts("UCI", 2, 7)
    assert "CC BY 4.0" in missing
    assert "data list has 2 items" in missing
    assert "model list has 7 items" not in missing


def test_format_table_and_exit_code() -> None:
    outcomes = [
        Outcome(1, "menu", e2e.PASS, "ok", "a/390x844-1-menu-view.png"),
        Outcome(2, "rivals", e2e.SKIP, "no PG.ai"),
    ]
    table = e2e.format_table(outcomes)
    lines = table.splitlines()
    assert len(lines) == 3
    assert "PASS" in lines[1]
    assert "[390x844-1-menu-view.png]" in lines[1]
    assert lines[2].endswith("no PG.ai")
    assert e2e.exit_code(outcomes) == e2e.EXIT_OK
    failed = [*outcomes, Outcome(3, "about", e2e.FAIL, "missing")]
    assert e2e.exit_code(failed) == e2e.EXIT_FAIL


def test_require() -> None:
    e2e.require(True, "unused")
    with pytest.raises(e2e.Fail, match="boom"):
        e2e.require(0, "boom")


def test_main_rejects_missing_file(capsys: pytest.CaptureFixture[str]) -> None:
    assert e2e.main(["no/such/game.html"]) == e2e.EXIT_USAGE
    assert "file not found" in capsys.readouterr().err
