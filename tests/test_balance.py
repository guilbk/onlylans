"""Tests for pipeline/balance.py: the thin command line over pipeline/sim.py."""

import json
from pathlib import Path

import pytest

from pipeline import balance as b

SHIFT = {
    "id": "mon-am", "start_hour": 8, "detour": 1.4, "speed_by_hour": [30.0] * 24,
    "orders": [[400, 1800, 2400, 1900, 2400, [10, 0], 60, 1.0, 5.0, 2, 0, 0],
               [1500, 1800, 2400, 1900, 2400, [10, 0], 60, 1.0, 7.0, 2, 0, 0]],
    "hot": [{"x": 1800, "y": 2400, "w": 1.0}], "surges": [],
    "ranking": [30.0, 20.0, 10.0, 4.0], "median": 10.0, "top10": 20.0,
}  # fmt: skip


@pytest.fixture
def data(tmp_path: Path) -> Path:
    path = tmp_path / "d.json"
    path.write_text(json.dumps({"unit_m": 5, "shifts": [SHIFT, SHIFT]}), encoding="utf-8")
    return path


def result(medal: int) -> b.Result:
    return b.Result("a", 1, 1, 1, 1, medal, 1, 1)


def test_rank_counts_strictly_more() -> None:
    assert b.rank_among(8.0, [10.0, 8.0, 8.0, 2.0]) == 2
    assert b.rank_among(11.0, [10.0, 8.0]) == 1
    assert b.rank_among(0.0, [10.0, 8.0, 8.0, 2.0]) == 5


def test_summarize_shares() -> None:
    s = b.summarize([result(m) for m in (0, 1, 2, 3, 4)])
    assert s == {"bronze": 0.8, "silver": 0.6, "gold": 0.4, "legend": 0.2}


def test_evaluate_takes_numbers_from_the_sim(data: Path) -> None:
    res = b.evaluate(data, "normal", 0.0, 1)
    assert [r.shift_id for r in res] == ["mon-am", "mon-am"]
    assert res[0].earned == res[1].earned > 0
    assert (res[0].median, res[0].top10, res[0].ghost, res[0].n_drivers) == (10.0, 20.0, 30.0, 4)
    assert res[0].rank == b.rank_among(res[0].earned, SHIFT["ranking"])


def test_format_table_shape() -> None:
    text = b.format_table("normal", "value", 200.0, [result(3)])
    lines = text.splitlines()
    assert lines[0] == "== diff=normal strategy=value lag=200"
    assert lines[1].split() == ["shift", "bot", "EUR", "median", "top10", "ghost", "medal", "rank"]
    assert "gold" in lines[2] and lines[2].endswith("1/1")
    assert lines[-1].startswith("summary: bronze+ 100%")


def test_main_prints_every_run_and_writes_json(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "r.json"
    argv = [
        "--data",
        str(data),
        "--diff",
        "easy,hard",
        "--lag",
        "0",
        "--shifts",
        "1",
        "--workers",
        "1",
        "--json",
        str(out),
    ]
    assert b.main(argv) == 0
    text = capsys.readouterr().out
    assert "diff=easy" in text and "diff=hard" in text
    runs = json.loads(out.read_text(encoding="utf-8"))
    assert [r["params"]["diff"] for r in runs] == ["easy", "hard"]
    assert all(len(r["results"]) == 1 for r in runs)


def test_unknown_strategy_or_diff_exits() -> None:
    with pytest.raises(SystemExit, match="nearest"):
        b.main(["--strategy", "nearest"])
    with pytest.raises(SystemExit, match="wild"):
        b.main(["--diff", "wild"])
