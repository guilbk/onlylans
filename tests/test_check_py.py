import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from check_py import _missing_annotations, check_source, iter_files, main  # noqa: E402

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
    assert "class K: no docstring" in text


def test_class_docstring_is_required_and_accepted() -> None:
    assert check_source('"""Mod."""\n\n\nclass A:\n    """Doc."""\n') == []
    (problem,) = check_source('"""Mod."""\n\n\nclass A:\n    x = 1\n')
    assert problem == "<string>:4: class A: no docstring"
    nested = '"""Mod."""\n\n\ndef f() -> None:\n    """Doc."""\n\n    class B:\n        pass\n'
    assert check_source(nested) == ["<string>:7: class B: no docstring"]


def test_missing_annotations_skips_self_and_covers_varargs() -> None:
    fn = ast.parse("def f(self, a, *args, k: int, **kw):\n    pass\n").body[0]
    assert _missing_annotations(fn) == ["a", "args", "kw", "return"]
    ok = ast.parse("def g(x: int, /, y: int, *, z: int) -> int:\n    return x\n").body[0]
    assert _missing_annotations(ok) == []


def test_iter_files_expands_dirs_and_ignores_missing(tmp_path: Path) -> None:
    (tmp_path / "pkg" / "sub").mkdir(parents=True)
    a, b = tmp_path / "pkg" / "b.py", tmp_path / "pkg" / "sub" / "a.py"
    a.write_text("", encoding="utf-8")
    b.write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "note.txt").write_text("", encoding="utf-8")
    single = tmp_path / "one.py"
    single.write_text("", encoding="utf-8")
    found = iter_files([tmp_path / "pkg", single, tmp_path / "missing"])
    assert found == sorted([a, b, single])


def test_main_exit_code_and_report(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    good = tmp_path / "good.py"
    good.write_text(GOOD, encoding="utf-8")
    bad = tmp_path / "bad.py"
    bad.write_text(BAD, encoding="utf-8")
    assert main([str(good)]) == 0
    assert capsys.readouterr().out == ""
    assert main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "bad.py" in out and "good.py" not in out
