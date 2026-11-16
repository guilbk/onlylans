"""Share of Python in the repository's code, counted by bytes (CONTRACT section 1).

Mirrors GitHub's language bar for the four languages that matter here: Python against
JavaScript, CSS and HTML. Files are taken from ``git ls-files``; files marked
``linguist-generated``, ``linguist-vendored`` or ``linguist-documentation`` in ``.gitattributes``
are skipped, and so are everything under ``data/``, JSON and Markdown. All sizes are in bytes.
"""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath

EXIT_OK = 0
EXIT_BELOW_MIN = 1
EXIT_USAGE = 2
DEFAULT_MIN_PERCENT = 50.0
PYTHON = "Python"
LANGUAGE_BY_SUFFIX: dict[str, str] = {
    ".py": PYTHON,
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".css": "CSS",
    ".html": "HTML",
    ".htm": "HTML",
}
LANGUAGE_ORDER = (PYTHON, "JavaScript", "CSS", "HTML")
EXCLUDED_DIRS = frozenset({"data"})
EXCLUDING_ATTRS = ("linguist-generated", "linguist-vendored", "linguist-documentation")
ATTR_ON = frozenset({"set", "true"})


def run_git(root: Path, args: list[str], stdin: bytes | None = None) -> bytes:
    """Run ``git -C <root> <args>`` and return its standard output.

    Args:
        root: Repository directory.
        args: Git arguments.
        stdin: Bytes fed to git's standard input, if any.

    Returns:
        Raw standard output.

    Raises:
        subprocess.CalledProcessError: If git exits with a non-zero status.
    """
    done = subprocess.run(
        ["git", "-C", str(root), *args],
        input=stdin,
        capture_output=True,
        check=True,
    )
    return done.stdout


def parse_nul_list(raw: bytes) -> list[str]:
    """Split NUL-separated git output into paths.

    Args:
        raw: Output of a ``-z`` git command.

    Returns:
        The non-empty items, decoded as UTF-8.
    """
    return [item.decode("utf-8") for item in raw.split(b"\0") if item]


def tracked_files(root: Path) -> list[str]:
    """List the files tracked by git.

    Args:
        root: Repository directory.

    Returns:
        Repository-relative POSIX paths, sorted.
    """
    return sorted(parse_nul_list(run_git(root, ["ls-files", "-z"])))


def parse_check_attr(raw: bytes) -> dict[str, set[str]]:
    """Parse ``git check-attr -z`` output into the attributes that are switched on.

    Args:
        raw: Output made of NUL-separated ``path, attribute, value`` triples.

    Returns:
        Map of path to the set of its attributes whose value is ``set`` or ``true``.
    """
    items = parse_nul_list(raw)
    on: dict[str, set[str]] = {}
    for i in range(0, len(items) - 2, 3):
        path, attr, value = items[i : i + 3]
        on.setdefault(path, set())
        if value in ATTR_ON:
            on[path].add(attr)
    return on


def excluding_attrs(root: Path, files: list[str]) -> dict[str, set[str]]:
    """Ask git which files carry an excluding linguist attribute.

    Args:
        root: Repository directory (its ``.gitattributes`` files apply).
        files: Repository-relative paths.

    Returns:
        Map of path to its switched-on attributes among ``EXCLUDING_ATTRS``.
    """
    if not files:
        return {}
    stdin = b"".join(f.encode("utf-8") + b"\0" for f in files)
    raw = run_git(root, ["check-attr", "-z", "--stdin", *EXCLUDING_ATTRS], stdin)
    return parse_check_attr(raw)


def language_of(path: str) -> str | None:
    """Name the counted language of a path, or None if it does not count.

    Args:
        path: Repository-relative POSIX path.

    Returns:
        ``Python``, ``JavaScript``, ``CSS`` or ``HTML``; None for other files and for
        everything under ``data/``.
    """
    pure = PurePosixPath(path)
    if pure.parts and pure.parts[0] in EXCLUDED_DIRS:
        return None
    return LANGUAGE_BY_SUFFIX.get(pure.suffix.lower())


def count_bytes(
    files: Iterable[str],
    sizes: Mapping[str, int],
    excluded: Mapping[str, set[str]],
) -> dict[str, int]:
    """Sum file sizes per counted language.

    Args:
        files: Repository-relative paths.
        sizes: Size in bytes of each path (a path missing here counts as absent).
        excluded: Switched-on excluding attributes per path.

    Returns:
        Bytes per language, with every language of ``LANGUAGE_ORDER`` present.
    """
    totals = dict.fromkeys(LANGUAGE_ORDER, 0)
    for path in files:
        lang = language_of(path)
        if lang is None or excluded.get(path) or path not in sizes:
            continue
        totals[lang] += sizes[path]
    return totals


def python_percent(totals: Mapping[str, int]) -> float:
    """Compute the Python share of the counted bytes.

    Args:
        totals: Bytes per language.

    Returns:
        Percentage 0..100; 0.0 if there are no counted bytes.
    """
    whole = sum(totals.values())
    return 100.0 * totals.get(PYTHON, 0) / whole if whole else 0.0


def format_table(totals: Mapping[str, int]) -> str:
    """Render the per-language table and the Python share.

    Args:
        totals: Bytes per language.

    Returns:
        Multi-line text: one row per language, then the Python share.
    """
    whole = sum(totals.values())
    rows = [f"{'language':<12}{'bytes':>10}{'share':>9}"]
    for lang in LANGUAGE_ORDER:
        share = 100.0 * totals.get(lang, 0) / whole if whole else 0.0
        rows.append(f"{lang:<12}{totals.get(lang, 0):>10}{share:>8.1f}%")
    rows.append(f"{'total':<12}{whole:>10}")
    rows.append(f"Python share: {python_percent(totals):.1f}%")
    return "\n".join(rows)


def file_sizes(root: Path, files: Iterable[str]) -> dict[str, int]:
    """Read the on-disk size in bytes of each existing file.

    Args:
        root: Repository directory.
        files: Repository-relative paths; those missing on disk (sparse checkout) are left out.

    Returns:
        Map of path to size in bytes.
    """
    sizes: dict[str, int] = {}
    for rel in files:
        path = root / rel
        if path.is_file():
            sizes[rel] = path.stat().st_size
    return sizes


def measure(root: Path) -> dict[str, int]:
    """Measure the bytes per language of a git repository.

    Args:
        root: Repository directory.

    Returns:
        Bytes per language, honouring the linguist attributes and the exclusions.
    """
    files = [f for f in tracked_files(root) if language_of(f) is not None]
    return count_bytes(files, file_sizes(root, files), excluding_attrs(root, files))


def main(argv: list[str] | None = None) -> int:
    """Command line entry point.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        0 if the Python share reaches ``--min``, 1 if it is below, 2 if git fails.
    """
    ap = argparse.ArgumentParser(description="Python share of the repository code")
    ap.add_argument("--root", type=Path, default=Path("."), help="repository directory")
    ap.add_argument(
        "--min", type=float, default=DEFAULT_MIN_PERCENT, help="minimum Python share, percent"
    )
    args = ap.parse_args(argv)
    try:
        totals = measure(args.root)
    except (subprocess.CalledProcessError, OSError) as err:
        print(f"lang_share: cannot read the repository: {err}")
        return EXIT_USAGE
    print(format_table(totals))
    share = python_percent(totals)
    if share < args.min:
        print(f"FAIL: Python share {share:.1f}% is below {args.min:g}%")
        return EXIT_BELOW_MIN
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
