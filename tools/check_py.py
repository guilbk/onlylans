"""AST check: every module and class needs a docstring; every function one and full annotations."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

DEFAULT_PATHS = ("pipeline", "tools")


def _missing_annotations(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """List the unannotated parameters (and the return) of a function.

    Args:
        fn: Function definition node.

    Returns:
        Names of the missing annotations; ``return`` stands for the return type.
    """
    a = fn.args
    params = [*a.posonlyargs, *a.args, *a.kwonlyargs]
    if a.vararg:
        params.append(a.vararg)
    if a.kwarg:
        params.append(a.kwarg)
    skip = params[0].arg if params and params[0].arg in ("self", "cls") else None
    missing = [p.arg for p in params if p.annotation is None and p.arg != skip]
    if fn.returns is None:
        missing.append("return")
    return missing


def check_source(source: str, name: str = "<string>") -> list[str]:
    """Check one module's source text.

    Args:
        source: Python source code.
        name: Name used in the messages.

    Returns:
        Human-readable problems; empty if the module is clean.
    """
    tree = ast.parse(source, filename=name)
    problems: list[str] = []
    if ast.get_docstring(tree) is None:
        problems.append(f"{name}: module has no docstring")
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if ast.get_docstring(node) is None:
                problems.append(f"{name}:{node.lineno}: class {node.name}: no docstring")
            continue
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        where = f"{name}:{node.lineno}: {node.name}"
        if ast.get_docstring(node) is None:
            problems.append(f"{where}: no docstring")
        missing = _missing_annotations(node)
        if missing:
            problems.append(f"{where}: missing annotations for {', '.join(missing)}")
    return problems


def iter_files(paths: list[Path]) -> list[Path]:
    """Expand files and directories into a sorted list of ``.py`` files.

    Args:
        paths: Files or directories (missing ones are ignored).

    Returns:
        Sorted Python files.
    """
    files: set[Path] = set()
    for p in paths:
        if p.is_dir():
            files.update(p.rglob("*.py"))
        elif p.is_file():
            files.add(p)
    return sorted(files)


def main(argv: list[str] | None = None) -> int:
    """Command line entry point.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        0 if all is clean, 1 if any problem was found.
    """
    ap = argparse.ArgumentParser(description="Docstring and annotation check")
    ap.add_argument("paths", nargs="*", type=Path, default=[Path(p) for p in DEFAULT_PATHS])
    args = ap.parse_args(argv)
    problems: list[str] = []
    for f in iter_files(args.paths):
        problems.extend(check_source(f.read_text(encoding="utf-8"), str(f)))
    for line in problems:
        print(line)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
