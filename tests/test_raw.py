"""Tests for pipeline.raw."""

import hashlib
import zipfile
from pathlib import Path

import pytest

from pipeline import raw

HEADER = (
    "TRIP_ID,CALL_TYPE,ORIGIN_CALL,ORIGIN_STAND,TAXI_ID,TIMESTAMP,DAY_TYPE,MISSING_DATA,POLYLINE"
)
ROWS = [
    '1,A,1,NA,20000001,1399852800,A,False,"[[-8.6,41.1],[-8.61,41.11]]"',
    "2,B,NA,7,20000002,1399852900,A,True,[]",
    '3,C,NA,NA,20000003,1399853000,B,False,"[[-8.62,41.12]]"',
    "4,C,NA,NA,20000004,1399853100,C,False,[]",
]


def make_parts(tmp_path: Path) -> tuple[Path, bytes]:
    """Write three small parts and return their directory and the joined bytes."""
    parts_dir = tmp_path / "parts"
    parts_dir.mkdir()
    chunks = [b"alpha-", b"bravo-", b"charlie"]
    for index, chunk in enumerate(chunks):
        (parts_dir / f"porto_uci.zip.part{index:02d}").write_bytes(chunk)
    return parts_dir, b"".join(chunks)


def make_outer_zip(tmp_path: Path) -> Path:
    """Build an outer archive holding train.csv.zip (4 rows) and an unrelated member."""
    inner = tmp_path / "inner" / "train.csv.zip"
    inner.parent.mkdir()
    with zipfile.ZipFile(inner, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("train.csv", "\n".join([HEADER, *ROWS]) + "\n")
    outer = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer, "w") as archive:
        archive.write(inner, "train.csv.zip")
        archive.writestr("test.csv", "ignored\n")
    return outer


def test_join_parts_concatenates_in_order(tmp_path: Path) -> None:
    parts_dir, joined = make_parts(tmp_path)
    out = tmp_path / "work" / "joined.zip"
    result = raw.join_parts(parts_dir, out, len(joined), hashlib.sha256(joined).hexdigest())
    assert result == out
    assert out.read_bytes() == joined


def test_join_parts_skips_when_output_is_valid(tmp_path: Path) -> None:
    parts_dir, joined = make_parts(tmp_path)
    out = tmp_path / "joined.zip"
    digest = hashlib.sha256(joined).hexdigest()
    raw.join_parts(parts_dir, out, len(joined), digest)
    for part in parts_dir.iterdir():
        part.unlink()
    assert raw.join_parts(parts_dir, out, len(joined), digest) == out


def test_join_parts_size_mismatch_raises(tmp_path: Path) -> None:
    parts_dir, joined = make_parts(tmp_path)
    out = tmp_path / "joined.zip"
    with pytest.raises(ValueError, match="size"):
        raw.join_parts(parts_dir, out, len(joined) + 1, hashlib.sha256(joined).hexdigest())
    assert not out.exists()


def test_join_parts_hash_mismatch_raises(tmp_path: Path) -> None:
    parts_dir, joined = make_parts(tmp_path)
    out = tmp_path / "joined.zip"
    with pytest.raises(ValueError, match="SHA-256"):
        raw.join_parts(parts_dir, out, len(joined), "0" * 64)
    assert not out.exists()


def test_join_parts_without_parts_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no parts"):
        raw.join_parts(tmp_path, tmp_path / "out.zip", 1, "0" * 64)


def test_extract_train_writes_member_and_skips_second_time(tmp_path: Path) -> None:
    outer = make_outer_zip(tmp_path)
    work = tmp_path / "work"
    target = raw.extract_train(outer, work)
    assert target == work / "train.csv.zip"
    assert sorted(path.name for path in work.iterdir()) == ["train.csv.zip"]
    mtime = target.stat().st_mtime_ns
    assert raw.extract_train(outer, work) == target
    assert target.stat().st_mtime_ns == mtime


def test_iter_train_rows_yields_header_then_rows(tmp_path: Path) -> None:
    train_zip = raw.extract_train(make_outer_zip(tmp_path), tmp_path / "work")
    rows = list(raw.iter_train_rows(train_zip))
    assert rows[0][0] == "TRIP_ID"
    assert len(rows) == 5
    assert rows[1][8] == "[[-8.6,41.1],[-8.61,41.11]]"
    assert rows[2][7] == "True"
