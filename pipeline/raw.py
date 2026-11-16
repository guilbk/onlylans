"""Raw Porto taxi data: join the archive parts, extract train.csv.zip, stream its rows.

The archive lives in git as ``data/porto/porto_uci.zip.part00`` ... ``part05``. The parts are
joined into ``data/work/porto_uci.zip``; the inner ``train.csv.zip`` is extracted next to it.
The 1.9 GB ``train.csv`` itself is only ever streamed, never written to disk.
"""

from __future__ import annotations

import csv
import hashlib
import io
import shutil
import zipfile
from collections.abc import Iterator
from pathlib import Path

ARCHIVE_NAME = "porto_uci.zip"
PART_GLOB = f"{ARCHIVE_NAME}.part*"
TRAIN_ZIP_MEMBER = "train.csv.zip"
TRAIN_CSV_MEMBER = "train.csv"
CHUNK_BYTES = 8 * 1024 * 1024
EXPECTED_SIZE = 534065916
EXPECTED_SHA256 = "a33e2a5e145607ae2bad0db5d21b7548c88b7e0f9db1ce15839f24c4c61f8c76"
CSV_FIELD_LIMIT = 2**31 - 1


def file_sha256(path: Path) -> str:
    """Compute the SHA-256 of a file, reading it in 8 MB chunks.

    Args:
        path: File to hash.

    Returns:
        Lowercase hex digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as src:
        while chunk := src.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _is_valid(path: Path, expected_size: int, expected_sha256: str) -> bool:
    """Tell whether a file exists with the expected size (bytes) and SHA-256."""
    if not path.is_file() or path.stat().st_size != expected_size:
        return False
    return file_sha256(path) == expected_sha256


def _concat_parts(parts: list[Path], tmp: Path) -> tuple[int, str]:
    """Write the parts one after another into ``tmp`` while hashing them.

    Args:
        parts: Part files, in the order they are joined.
        tmp: Path of the file to write.

    Returns:
        ``(size, sha256)``: bytes written and their lowercase hex SHA-256.
    """
    digest = hashlib.sha256()
    size = 0
    with tmp.open("wb") as dst:
        for part in parts:
            with part.open("rb") as src:
                while chunk := src.read(CHUNK_BYTES):
                    dst.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
    return size, digest.hexdigest()


def join_parts(
    parts_dir: Path,
    out: Path,
    expected_size: int = EXPECTED_SIZE,
    expected_sha256: str = EXPECTED_SHA256,
) -> Path:
    """Concatenate the archive parts (sorted by name) into one zip and verify it.

    Skips all work when ``out`` already exists with the expected size and hash.

    Args:
        parts_dir: Directory holding ``porto_uci.zip.partNN`` files.
        out: Path of the joined zip to write.
        expected_size: Expected size of the joined file, in bytes.
        expected_sha256: Expected SHA-256 of the joined file, lowercase hex.

    Returns:
        ``out``.

    Raises:
        ValueError: If no parts are found, or the joined size or hash does not match.
    """
    if _is_valid(out, expected_size, expected_sha256):
        return out
    parts = sorted(parts_dir.glob(PART_GLOB))
    if not parts:
        raise ValueError(f"no parts matching {PART_GLOB} in {parts_dir}")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    size, sha256 = _concat_parts(parts, tmp)
    if size != expected_size:
        tmp.unlink()
        raise ValueError(f"joined size {size} != expected {expected_size}")
    if sha256 != expected_sha256:
        tmp.unlink()
        raise ValueError(f"joined SHA-256 {sha256} != expected {expected_sha256}")
    tmp.replace(out)
    return out


def extract_train(zip_path: Path, work: Path) -> Path:
    """Extract the ``train.csv.zip`` member of the outer archive into ``work``.

    Other members of the outer archive (test trajectories, solutions) are ignored. Skips the
    extraction when the target already exists with the member's size.

    Args:
        zip_path: The joined outer archive.
        work: Directory to extract into.

    Returns:
        Path of the extracted ``train.csv.zip``.
    """
    target = work / TRAIN_ZIP_MEMBER
    with zipfile.ZipFile(zip_path) as outer:
        info = outer.getinfo(TRAIN_ZIP_MEMBER)
        if target.is_file() and target.stat().st_size == info.file_size:
            return target
        work.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        with outer.open(info) as src, tmp.open("wb") as dst:
            shutil.copyfileobj(src, dst, CHUNK_BYTES)
    tmp.replace(target)
    return target


def iter_train_rows(train_zip: Path) -> Iterator[list[str]]:
    """Stream the rows of ``train.csv`` straight out of ``train.csv.zip``.

    Args:
        train_zip: Path of ``train.csv.zip``.

    Yields:
        The header row first, then one list of string fields per data row.
    """
    csv.field_size_limit(CSV_FIELD_LIMIT)
    with zipfile.ZipFile(train_zip) as archive, archive.open(TRAIN_CSV_MEMBER) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
        yield from csv.reader(text)


def ensure_raw(root: Path) -> Path:
    """Join, verify and extract everything needed to read the training rows.

    Args:
        root: Repository root (contains ``data/porto``).

    Returns:
        Path of ``data/work/train.csv.zip``.
    """
    work = root / "data" / "work"
    joined = join_parts(root / "data" / "porto", work / ARCHIVE_NAME)
    return extract_train(joined, work)
