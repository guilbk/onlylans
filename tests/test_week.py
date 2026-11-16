"""Tests for pipeline.week."""

import csv
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pipeline import week

HEADER = [
    "TRIP_ID",
    "CALL_TYPE",
    "ORIGIN_CALL",
    "ORIGIN_STAND",
    "TAXI_ID",
    "TIMESTAMP",
    "DAY_TYPE",
    "MISSING_DATA",
    "POLYLINE",
]
TS_COL = HEADER.index("TIMESTAMP")
MISSING_COL = HEADER.index("MISSING_DATA")
HOUR = 3600


def make_row(timestamp: int, missing: str = "False") -> list[str]:
    """Build a trip row with the given TIMESTAMP and MISSING_DATA."""
    return ["t", "C", "NA", "NA", "1", str(timestamp), "A", missing, "[]"]


def iter_rows(path: Path) -> list[list[str]]:
    """Read a CSV file back as a list of rows."""
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


def test_campaign_window_is_lisbon_midnight() -> None:
    w0, w1 = week.campaign_window()
    assert w1 - w0 == 7 * 24 * HOUR
    # Lisbon is UTC+1 in May, so local midnight is 23:00 UTC the evening before.
    assert datetime.fromtimestamp(w0, UTC) == datetime(2014, 5, 11, 23, tzinfo=UTC)
    assert datetime.fromtimestamp(w1, UTC) == datetime(2014, 5, 18, 23, tzinfo=UTC)


def test_keep_row_window_edges() -> None:
    w0, w1 = week.campaign_window()
    assert week.keep_row(make_row(w0), TS_COL, MISSING_COL, w0, w1)
    assert week.keep_row(make_row(w1 - 1), TS_COL, MISSING_COL, w0, w1)
    assert not week.keep_row(make_row(w1), TS_COL, MISSING_COL, w0, w1)
    assert not week.keep_row(make_row(w0 - HOUR), TS_COL, MISSING_COL, w0, w1)


def test_keep_row_drops_missing_data() -> None:
    w0, w1 = week.campaign_window()
    assert not week.keep_row(make_row(w0 + 10, "True"), TS_COL, MISSING_COL, w0, w1)


def test_filter_week_counts_and_writes(tmp_path: Path) -> None:
    w0, w1 = week.campaign_window()
    rows = [
        HEADER,
        make_row(w0),
        make_row(w0 + 5, "True"),
        make_row(w1),
        make_row(w0 - HOUR),
        make_row(w1 - 1),
    ]
    out = tmp_path / "sub" / "week.csv"
    assert week.filter_week(rows, out, w0, w1) == (5, 2)
    train_rows = list(iter_rows(out))
    assert train_rows[0] == HEADER
    assert [row[TS_COL] for row in train_rows[1:]] == [str(w0), str(w1 - 1)]
    assert [p.name for p in out.parent.iterdir()] == ["week.csv"]  # temp file renamed away


def test_filter_week_keeps_the_old_file_when_reading_fails(tmp_path: Path) -> None:
    w0, w1 = week.campaign_window()
    out = tmp_path / "week.csv"
    out.write_text("old", encoding="utf-8")

    def broken() -> Iterator[list[str]]:
        yield HEADER
        yield make_row(w0)
        raise OSError("disk")

    with pytest.raises(OSError, match="disk"):
        week.filter_week(broken(), out, w0, w1)
    assert out.read_text(encoding="utf-8") == "old"



def test_build_parser_defaults_and_overrides() -> None:
    args = week.build_parser().parse_args([])
    assert args.root == Path(".") and args.out is None
    args = week.build_parser().parse_args(["--root", "r", "--out", "o.csv"])
    assert args.root == Path("r") and args.out == Path("o.csv")
