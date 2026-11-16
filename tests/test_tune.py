"""Tests of the balance sweep (pipeline.tune): scoring, floors, grids and a tiny evaluation."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from pipeline import sim, tune


def summary(**kw: float) -> sim.Summary:
    """A summary with the given shares; the rest are neutral."""
    fields: dict[str, object] = {
        "n": 28, "bronze": 1.0, "silver": 1.0, "gold": 0.4, "legend": 0.1, "bot_eur": 30.0,
        "lost": 0.0, "rival_eur": (10.0,) * 7, "rival_rides": (2.0,) * 7, "place": 1.0,
    }  # fmt: skip
    fields.update(kw)
    return sim.Summary(**fields)  # type: ignore[arg-type]


def test_band_miss() -> None:
    band = tune.Band(0.35, 0.5)
    assert tune.band_miss(0.4, band) == 0.0
    assert tune.band_miss(0.2, band) == pytest.approx(0.15)
    assert tune.band_miss(0.9, band) == pytest.approx(0.4)


def test_target_miss_zero_inside_all_bands() -> None:
    assert tune.target_miss(summary(), tune.TARGETS["normal"]) == 0.0
    assert tune.target_miss(summary(gold=0.8, legend=0.5), tune.TARGETS["normal"]) > 0.1


def test_harder_miss_needs_strict_order() -> None:
    ok = {
        "easy": summary(gold=0.6, bot_eur=40.0),
        "normal": summary(gold=0.4, bot_eur=30.0),
        "hard": summary(gold=0.2, bot_eur=20.0),
    }
    assert tune.harder_miss(ok) == 0.0
    flat = {**ok, "hard": summary(gold=0.4, bot_eur=30.0)}
    assert tune.harder_miss(flat) > 0.0
    assert tune.harder_miss({"easy": summary()}) == 0.0


def test_change_cost_is_zero_for_the_current_design() -> None:
    base = sim.Settings()
    assert tune.change_cost(base) == 0.0
    assert tune.change_cost(replace(base, lead=(360.0, 540.0, 420.0))) > 0.0


def test_reach_floor() -> None:
    base = sim.Settings()
    assert tune.reach_floor(base) == pytest.approx(900 * 0.8 - 200 - 30)
    assert tune.obeys_floor(base)
    cliff = replace(base, lead=(600.0, 210.0, 210.0))
    assert tune.reach_floor(cliff) < 0 and not tune.obeys_floor(cliff)


def test_rank_prefers_zero_miss_then_small_change() -> None:
    s = sim.Settings()
    a = tune.Candidate(s, {}, 0.0, 2.0)
    b = tune.Candidate(s, {}, 0.0, 1.0)
    c = tune.Candidate(s, {}, 0.5, 0.0)
    assert tune.rank([c, a, b]) == [b, a, c]


def test_rank_breaks_ties_with_the_stronger_rivals() -> None:
    s = sim.Settings()
    weak = tune.Candidate(s, {"hard": summary(rival_eur=(10.0,) * 7)}, 0.0, 1.0)
    strong = tune.Candidate(s, {"hard": summary(rival_eur=(30.0,) * 7)}, 0.0, 1.0)
    assert tune.rank([weak, strong]) == [strong, weak]


def test_lead_option_parses_three_numbers() -> None:
    assert tune._lead("310,310,400") == (310.0, 310.0, 400.0)


def test_grids_vary_only_their_levers() -> None:
    base = sim.Settings()
    normal = tune.normal_grid(base)
    assert normal and all(s.lead[0] >= s.lead[1] >= s.lead[2] for s in normal)
    assert all(s.diff_k == base.diff_k for s in normal)
    assert {s.radius for s in normal} == {
        tuple(r * k for r in sim.DEFAULT_RADIUS) for k in tune.RADIUS_SCALES
    }
    floored = tune.normal_grid(base, floor_only=True)
    assert floored and all(tune.obeys_floor(s) for s in floored)
    assert len(floored) < len(normal)
    easy = tune.easy_grid(base)
    assert [s.diff_k["easy"] for s in easy] == list(tune.K_EASY_GRID)
    assert all(s.diff_k["normal"] == 0.9 and s.lead == base.lead for s in easy)
    hard = tune.hard_grid(base)
    assert len(hard) == len(tune.K_HARD_GRID) * 2 * 2 * 2 * 2
    assert all(s.rivals["normal"] == base.rivals["normal"] for s in hard)


def tiny_file(tmp_path: Path) -> Path:
    raw = {
        "unit_m": 5, "shifts": [{
            "id": "mon-am", "start_hour": 8, "detour": 1.4, "speed_by_hour": [20.0] * 24,
            "orders": [[60 * k, 1800, 2400, 1900, 2400, [20, 0], 30, 1.0, 4.0, 0, 0, 0]
                       for k in range(1, 40)],
            "hot": [{"x": 1800, "y": 2400, "w": 1.0}], "surges": [],
            "ranking": [20.0, 10.0], "median": 5.0, "top10": 9.0,
        }],
    }  # fmt: skip
    path = tmp_path / "d.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_evaluate_and_report_on_a_tiny_file(tmp_path: Path) -> None:
    path = tiny_file(tmp_path)
    cands = tune.sweep(tune.easy_grid(sim.Settings())[:2], "easy", path, 1, None)
    assert len(cands) == 2 and cands[0].summaries["easy"].n == 1
    lines = tune.report("easy", "easy", cands, 1)
    assert lines[0].startswith("== easy") and any("any #1" in x for x in lines)
    row = tune.format_row("x", "easy", cands[0])
    assert "lead 1200/1200/900" in row and "rad 6000/4500/3000" in row and "rivals near" in row


def test_main_exits_1_when_the_lead_is_below_the_floor(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = str(tiny_file(tmp_path))
    argv = ["--data", data, "--workers", "1", "--floor", "--lead", "100,100,100"]
    assert tune.main(argv) == 1
    assert "reachability floor" in capsys.readouterr().out
