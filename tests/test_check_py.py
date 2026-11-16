import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from check_py import check_source  # noqa: E402

GOOD = '"""Mod."""\n\n\ndef f(a: int, *, b: str = "x") -> int:\n    """Doc."""\n    return a\n'
BAD = (
    "def f(a, b: int):\n    return a\n\n\n"
    "class K:\n    def m(self, x: int) -> None:\n        pass\n"
)


def test_clean_module_has_no_problems() -> None:
    assert check_source(GOOD) == []


def test_bad_module_lists_every_problem() -> None:
    problems = check_source(BAD)
    text = "\n".join(problems)
    assert "module has no docstring" in text
    assert "f: no docstring" in text
    assert "missing annotations for a, return" in text
    assert "m: no docstring" in text
    assert "m: missing" not in text
