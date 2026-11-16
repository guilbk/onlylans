"""Build the single-file offline game ``game/index.html`` from ``game/src`` (CONTRACT section 6)."""

from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

SRC_DEFAULT = Path("game/src")
DATA_DEFAULT = Path("game/game_data.json")
FIXTURE_DEFAULT = Path("game/fixture/mini.json")
ROADS_DEFAULT = Path("game/roads.json")
STREETS_DEFAULT = Path("game/streets.png")
MISSIONS_DEFAULT = Path("game/missions.json")
FACTS_DEFAULT = Path("game/facts.json")
ACHIEVEMENTS_DEFAULT = Path("game/achievements.json")
HEAT_DEFAULT = Path("game/heat.json")
OUT_DEFAULT = Path("game/index.html")

PH_CSS = "/*__CSS__*/"
PH_DATA = "<!--__DATA__-->"
PH_JS = "<!--__JS__-->"
KIB = 1024  # bytes in a KiB, for the size line


class BuildError(Exception):
    """Raised when the game cannot be built."""


def default_data(data_path: Path = DATA_DEFAULT, fixture: Path = FIXTURE_DEFAULT) -> Path:
    """Pick the data file: the real game data if it exists, else the fixture.

    Args:
        data_path: Path of the real game data.
        fixture: Path of the fallback fixture.

    Returns:
        ``data_path`` if it is a file, otherwise ``fixture``.
    """
    return data_path if data_path.is_file() else fixture


def escape_json(text: str) -> str:
    r"""Escape every ``<`` as ``\u003c`` so JSON can sit inside a script element.

    ``<`` only occurs inside JSON strings, where ``\u003c`` means the same character, so the text
    stays valid JSON and can never contain ``</script`` or ``<!--``.

    Args:
        text: JSON text.

    Returns:
        The escaped text (still valid JSON).
    """
    return text.replace("<", "\\u003c")


def replace_once(template: str, placeholder: str, value: str) -> str:
    """Replace a placeholder that must occur exactly once.

    Args:
        template: Text containing the placeholder.
        placeholder: The marker to replace.
        value: Replacement text (inserted verbatim).

    Returns:
        The text with the placeholder replaced.

    Raises:
        BuildError: If the placeholder does not occur exactly once.
    """
    count = template.count(placeholder)
    if count != 1:
        raise BuildError(f"placeholder {placeholder} occurs {count} times, expected 1")
    return template.replace(placeholder, value, 1)


def collect_css(css_dir: Path) -> str:
    """Concatenate all ``*.css`` files of a directory, sorted by name.

    Args:
        css_dir: Directory with CSS files.

    Returns:
        The concatenated CSS (empty if the directory has none).
    """
    parts = [p.read_text(encoding="utf-8") for p in sorted(css_dir.glob("*.css"))]
    return "\n".join(parts)


def collect_js(js_dir: Path) -> str:
    """Wrap each ``*.js`` file of a directory in its own script element, sorted by name.

    Args:
        js_dir: Directory with JS files.

    Returns:
        The script elements, one per file.

    Raises:
        BuildError: If a file contains ``</script`` (any case).
    """
    out: list[str] = []
    for path in sorted(js_dir.glob("*.js")):
        code = path.read_text(encoding="utf-8")
        if "</script" in code.lower():
            raise BuildError(f"{path} contains '</script'")
        out.append(f"<script>\n{code}\n</script>")
    return "\n".join(out)


def build_data_block(
    data: Path,
    roads: Path,
    streets: Path,
    missions: Path | None = None,
    facts: Path | None = None,
    achievements: Path | None = None,
    heat: Path | None = None,
) -> str:
    """Build the inline data: game data, then roads, streets, missions, facts, achievements.

    Args:
        data: Game data JSON (must exist).
        roads: Roads JSON; skipped silently if missing.
        streets: Streets PNG; skipped silently if missing.
        missions: Missions JSON (CONTRACT section 16); skipped silently if missing or ``None``.
        facts: Result facts JSON (CONTRACT section 17); skipped silently if missing or ``None``.
        achievements: Achievements JSON (CONTRACT section 18); skipped if missing or ``None``.
        heat: Earnings heat JSON (CONTRACT section 21); skipped if missing or ``None``.

    Returns:
        HTML for the data elements.

    Raises:
        BuildError: If the game data file is missing.
    """
    if not data.is_file():
        raise BuildError(f"data file not found: {data}")
    text = data.read_text(encoding="utf-8").strip()
    parts = [f'<script type="application/json" id="game-data">{escape_json(text)}</script>']
    if roads.is_file():
        rtext = roads.read_text(encoding="utf-8").strip()
        parts.append(
            f'<script type="application/json" id="roads-data">{escape_json(rtext)}</script>'
        )
    if streets.is_file():
        b64 = base64.b64encode(streets.read_bytes()).decode("ascii")
        parts.append(f'<img id="streets-png" hidden src="data:image/png;base64,{b64}">')
    if missions is not None and missions.is_file():
        mtext = missions.read_text(encoding="utf-8").strip()
        parts.append(
            f'<script type="application/json" id="missions-data">{escape_json(mtext)}</script>'
        )
    if facts is not None and facts.is_file():
        ftext = facts.read_text(encoding="utf-8").strip()
        parts.append(
            f'<script type="application/json" id="facts-data">{escape_json(ftext)}</script>'
        )
    if achievements is not None and achievements.is_file():
        atext = achievements.read_text(encoding="utf-8").strip()
        parts.append(
            f'<script type="application/json" id="achievements-data">{escape_json(atext)}</script>'
        )
    if heat is not None and heat.is_file():
        htext = heat.read_text(encoding="utf-8").strip()
        parts.append(
            f'<script type="application/json" id="heat-data">{escape_json(htext)}</script>'
        )
    return "\n".join(parts)


def build(
    src: Path,
    data: Path,
    roads: Path,
    streets: Path,
    missions: Path | None = None,
    facts: Path | None = None,
    achievements: Path | None = None,
    heat: Path | None = None,
) -> str:
    """Assemble the final HTML.

    Args:
        src: Source directory (``index.html``, ``css/``, ``js/``).
        data: Game data JSON.
        roads: Roads JSON (optional file).
        streets: Streets PNG (optional file).
        missions: Missions JSON (optional file; absent = no missions in the game).
        facts: Result facts JSON (optional file; absent = no facts on the result screen).
        achievements: Achievements JSON (optional file; absent = no badges in the game).
        heat: Heat JSON (optional file; absent = no heat button).

    Returns:
        The complete HTML document.

    Raises:
        BuildError: On a missing template or placeholder problems.
    """
    template_path = src / "index.html"
    if not template_path.is_file():
        raise BuildError(f"template not found: {template_path}")
    html = template_path.read_text(encoding="utf-8")
    # Pieces are computed first, then placed; each placeholder is checked on the template.
    css = collect_css(src / "css")
    js = collect_js(src / "js")
    block = build_data_block(data, roads, streets, missions, facts, achievements, heat)
    for ph in (PH_CSS, PH_DATA, PH_JS):
        replace_once(html, ph, "")  # validates the count before any substitution
    html = html.replace(PH_CSS, css, 1)
    html = html.replace(PH_DATA, block, 1)
    return html.replace(PH_JS, js, 1)


def main(argv: list[str] | None = None) -> int:
    """Command line entry point.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        0 on success, 1 on a build error.
    """
    ap = argparse.ArgumentParser(description="Build game/index.html")
    ap.add_argument("--src", type=Path, default=SRC_DEFAULT)
    ap.add_argument("--data", type=Path, default=None)
    ap.add_argument("--roads", type=Path, default=ROADS_DEFAULT)
    ap.add_argument("--streets", type=Path, default=STREETS_DEFAULT)
    ap.add_argument("--missions", type=Path, default=MISSIONS_DEFAULT)
    ap.add_argument("--facts", type=Path, default=FACTS_DEFAULT)
    ap.add_argument("--achievements", type=Path, default=ACHIEVEMENTS_DEFAULT)
    ap.add_argument("--heat", type=Path, default=HEAT_DEFAULT)
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = ap.parse_args(argv)
    data = args.data if args.data is not None else default_data()
    try:
        html = build(
            args.src,
            data,
            args.roads,
            args.streets,
            args.missions,
            args.facts,
            args.achievements,
            args.heat,
        )
    except (BuildError, OSError) as err:
        print(f"build error: {err}", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_name(args.out.name + ".tmp")
    tmp.write_text(html, encoding="utf-8")
    os.replace(tmp, args.out)  # atomic: a reader never sees a half-written file
    print(f"built {args.out} ({len(html) // KIB} KB, data: {data})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
