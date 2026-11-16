import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import lang_share as ls  # noqa: E402

ZERO = {"Python": 0, "JavaScript": 0, "CSS": 0, "HTML": 0}


@pytest.mark.parametrize(
    ("path", "lang"),
    [
        ("pipeline/geo.py", "Python"),
        ("game/src/js/20_engine.js", "JavaScript"),
        ("tools/roads_test.mjs", "JavaScript"),
        ("x/y.CJS", "JavaScript"),
        ("game/src/css/00_base.css", "CSS"),
        ("game/src/index.html", "HTML"),
        ("tools/audio_demo.htm", "HTML"),
        ("data/helper.py", None),
        ("game/game_data.json", None),
        ("docs/CONTRACT.md", None),
        ("Makefile", None),
        ("database/x.py", "Python"),
    ],
)
def test_language_of(path: str, lang: str | None) -> None:
    assert ls.language_of(path) == lang


def test_parse_nul_list_skips_empty_items() -> None:
    assert ls.parse_nul_list(b"a.py\0b/c.js\0") == ["a.py", "b/c.js"]
    assert ls.parse_nul_list(b"") == []


def test_parse_check_attr_keeps_only_switched_on() -> None:
    raw = (
        b"a.py\0linguist-generated\0unspecified\0"
        b"a.py\0linguist-vendored\0unset\0"
        b"b.js\0linguist-generated\0set\0"
        b"b.js\0linguist-vendored\0true\0"
        b"c.css\0linguist-documentation\0false\0"
    )
    on = ls.parse_check_attr(raw)
    assert on["a.py"] == set()
    assert on["b.js"] == {"linguist-generated", "linguist-vendored"}
    assert on["c.css"] == set()


def test_count_bytes_skips_excluded_unknown_and_absent() -> None:
    files = ["a.py", "b.js", "c.css", "d.html", "gen.js", "data/x.py", "note.md", "gone.py"]
    sizes = {"a.py": 100, "b.js": 40, "c.css": 5, "d.html": 5, "gen.js": 999, "data/x.py": 7}
    excluded = {"gen.js": {"linguist-generated"}, "a.py": set()}
    totals = ls.count_bytes(files, sizes, excluded)
    assert totals == {"Python": 100, "JavaScript": 40, "CSS": 5, "HTML": 5}


def test_python_percent() -> None:
    assert ls.python_percent({"Python": 50, "JavaScript": 50}) == pytest.approx(50.0)
    assert ls.python_percent({"Python": 3, "JavaScript": 1}) == pytest.approx(75.0)
    assert ls.python_percent(ZERO) == 0.0
    assert ls.python_percent({}) == 0.0


def test_format_table_lists_each_language_and_the_share() -> None:
    text = ls.format_table({"Python": 75, "JavaScript": 25, "CSS": 0, "HTML": 0})
    lines = text.splitlines()
    assert [ln.split()[0] for ln in lines[1:5]] == ["Python", "JavaScript", "CSS", "HTML"]
    assert "75.00%" in lines[1]
    assert lines[-1] == "Python share: 75.00%"


def test_file_sizes_ignores_missing_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_bytes(b"12345")
    assert ls.file_sizes(tmp_path, ["a.py", "missing.py"]) == {"a.py": 5}


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        check=True,
        capture_output=True,
    )


def make_repo(root: Path, files: dict[str, int], attrs: str) -> None:
    """Create a git repo with files of the given byte sizes and a .gitattributes text."""
    git(root, "init", "-q")
    for rel, size in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"#" * size)
    (root / ".gitattributes").write_text(attrs, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "x")


REPO_FILES = {
    "pipeline/a.py": 600,
    "tools/t.mjs": 300,
    "game/src/js/g.js": 100,
    "dist/out.js": 5000,
    "vendor/lib.js": 5000,
    "docs/example.js": 5000,
    "data/big.py": 5000,
    "game/data.json": 5000,
    "README.md": 5000,
}
REPO_ATTRS = (
    "dist/** linguist-generated=true\nvendor/** linguist-vendored\ndocs/** linguist-documentation\n"
)


def test_measure_on_temp_git_repo(tmp_path: Path) -> None:
    make_repo(tmp_path, REPO_FILES, REPO_ATTRS)
    totals = ls.measure(tmp_path)
    assert totals == {"Python": 600, "JavaScript": 400, "CSS": 0, "HTML": 0}


def test_main_exit_codes_and_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_repo(tmp_path, REPO_FILES, REPO_ATTRS)
    assert ls.main(["--root", str(tmp_path), "--min", "60"]) == 0
    assert "Python share: 60.00%" in capsys.readouterr().out
    assert ls.main(["--root", str(tmp_path), "--min", "60.1"]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_main_without_code_is_below_minimum(tmp_path: Path) -> None:
    make_repo(tmp_path, {"README.md": 10}, "")
    assert ls.main(["--root", str(tmp_path)]) == 1


def test_main_outside_a_repository_exits_two(tmp_path: Path) -> None:
    assert ls.main(["--root", str(tmp_path / "nope")]) == 2
