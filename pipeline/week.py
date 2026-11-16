"""Cut the campaign week out of the Porto training set into ``data/work/week.csv``.

Usage: ``python -m pipeline.week [--root .] [--out data/work/week.csv]``
"""

from __future__ import annotations

import argparse
import csv
import time
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pipeline.raw import ensure_raw, iter_train_rows

LISBON = ZoneInfo("Europe/Lisbon")
WINDOW_START = datetime(2014, 5, 12, tzinfo=LISBON)
WINDOW_END = datetime(2014, 5, 19, tzinfo=LISBON)
TIMESTAMP_COLUMN = "TIMESTAMP"
MISSING_COLUMN = "MISSING_DATA"
MISSING_FALSE = "False"
DEFAULT_OUT = Path("data/work/week.csv")


def campaign_window() -> tuple[int, int]:
    """Return the campaign window as unix seconds.

    Returns:
        ``(start, end)``: Mon 12.05.2014 00:00 inclusive and Mon 19.05.2014 00:00 exclusive,
        both in Europe/Lisbon.
    """
    return int(WINDOW_START.timestamp()), int(WINDOW_END.timestamp())


def keep_row(row: list[str], ts_col: int, missing_col: int, w0: int, w1: int) -> bool:
    """Decide whether a trip row belongs to the campaign week.

    Only the TIMESTAMP and MISSING_DATA fields are looked at, never POLYLINE.

    Args:
        row: One CSV row.
        ts_col: Index of the TIMESTAMP column (unix seconds).
        missing_col: Index of the MISSING_DATA column.
        w0: Window start, unix seconds, inclusive.
        w1: Window end, unix seconds, exclusive.

    Returns:
        True when ``w0 <= TIMESTAMP < w1`` and MISSING_DATA is ``"False"``.
    """
    return w0 <= int(row[ts_col]) < w1 and row[missing_col] == MISSING_FALSE


def filter_week(rows: Iterable[list[str]], out: Path, w0: int, w1: int) -> tuple[int, int]:
    """Write the header and the rows that pass :func:`keep_row` to a CSV file.

    Args:
        rows: Header row followed by data rows.
        out: Output CSV path; parent directories are created.
        w0: Window start, unix seconds, inclusive.
        w1: Window end, unix seconds, exclusive.

    Returns:
        ``(rows_read, rows_kept)``, counting data rows only.
    """
    iterator = iter(rows)
    header = next(iterator)
    ts_col = header.index(TIMESTAMP_COLUMN)
    missing_col = header.index(MISSING_COLUMN)
    out.parent.mkdir(parents=True, exist_ok=True)
    read = kept = 0
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for row in iterator:
            read += 1
            if keep_row(row, ts_col, missing_col, w0, w1):
                writer.writerow(row)
                kept += 1
    return read, kept


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description="Cut the campaign week out of the Porto data.")
    parser.add_argument("--root", type=Path, default=Path("."), help="repository root")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output CSV path")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the raw-to-week step.

    Args:
        argv: Command-line arguments; ``None`` means ``sys.argv[1:]``.

    Returns:
        Process exit code.
    """
    args = build_parser().parse_args(argv)
    started = time.monotonic()
    train_zip = ensure_raw(args.root)
    w0, w1 = campaign_window()
    read, kept = filter_week(iter_train_rows(train_zip), args.out, w0, w1)
    print(f"rows read: {read}")
    print(f"rows kept: {kept}")
    print(f"seconds: {time.monotonic() - started:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
