import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import build_game as bg  # noqa: E402


def make_src(tmp_path: Path, js: dict[str, str] | None = None) -> Path:
    src = tmp_path / "src"
    (src / "css").mkdir(parents=True)
    (src / "js").mkdir()
    (src / "index.html").write_text(
        "<style>\n/*__CSS__*/\n</style><body><!--__DATA__--><!--__JS__--></body>", encoding="utf-8"
    )
    (src / "css" / "b.css").write_text("b{}", encoding="utf-8")
    (src / "css" / "a.css").write_text("a{}", encoding="utf-8")
    for name, code in (js or {"10_x.js": "var x=1;", "00_a.js": "var a=1;"}).items():
        (src / "js" / name).write_text(code, encoding="utf-8")
    return src


def write_data(tmp_path: Path, text: str = '{"v":1}') -> Path:
    p = tmp_path / "data.json"
    p.write_text(text, encoding="utf-8")
    return p


def test_placeholders_replaced_once_and_ordered(tmp_path: Path) -> None:
    out = tmp_path / "out.html"
    rc = bg.main(
        [
            "--src",
            str(make_src(tmp_path)),
            "--data",
            str(write_data(tmp_path)),
            "--roads",
            str(tmp_path / "none.json"),
            "--streets",
            str(tmp_path / "none.png"),
            "--out",
            str(out),
        ]
    )
    html = out.read_text(encoding="utf-8")
    assert rc == 0
    for ph in (bg.PH_CSS, bg.PH_DATA, bg.PH_JS):
        assert ph not in html
    assert html.index("a{}") < html.index("b{}")
    assert html.index("game-data") < html.index("var a=1;") < html.index("var x=1;")
    assert html.count('id="game-data"') == 1


def test_script_end_tag_in_js_fails(tmp_path: Path) -> None:
    src = make_src(tmp_path, {"00_a.js": "var s = '</SCRIPT>';"})
    out = tmp_path / "out.html"
    rc = bg.main(["--src", str(src), "--data", str(write_data(tmp_path)), "--out", str(out)])
    assert rc == 1
    assert not out.exists()


def test_missing_roads_and_streets_are_skipped(tmp_path: Path) -> None:
    src, data = make_src(tmp_path), write_data(tmp_path)
    html = bg.build(src, data, tmp_path / "r.json", tmp_path / "s.png")
    assert "roads-data" not in html
    assert "streets-png" not in html


def test_roads_and_streets_inlined_when_present(tmp_path: Path) -> None:
    roads = tmp_path / "r.json"
    roads.write_text('{"v":1}', encoding="utf-8")
    png = tmp_path / "s.png"
    png.write_bytes(b"\x89PNG")
    html = bg.build(make_src(tmp_path), write_data(tmp_path), roads, png)
    assert html.index("game-data") < html.index("roads-data") < html.index("streets-png")
    assert "data:image/png;base64," in html


def test_json_end_tag_is_escaped(tmp_path: Path) -> None:
    data = write_data(tmp_path, json.dumps({"s": "</script>"}))
    html = bg.build(make_src(tmp_path), data, tmp_path / "r.json", tmp_path / "s.png")
    assert '</script>"' not in html.split('id="game-data">')[1].split("</script>")[0]
    assert "<\\/script>" in html


def test_duplicate_placeholder_fails(tmp_path: Path) -> None:
    src = make_src(tmp_path)
    (src / "index.html").write_text("<!--__DATA__--><!--__DATA__-->/*__CSS__*/<!--__JS__-->")
    with pytest.raises(bg.BuildError):
        bg.build(src, write_data(tmp_path), tmp_path / "r.json", tmp_path / "s.png")


def test_default_data_rule(tmp_path: Path) -> None:
    real = tmp_path / "game_data.json"
    fixture = tmp_path / "mini.json"
    assert bg.default_data(real, fixture) == fixture
    real.write_text("{}", encoding="utf-8")
    assert bg.default_data(real, fixture) == real


def test_escape_json_only_touches_close_tags() -> None:
    assert bg.escape_json('{"a":"</script>"}') == '{"a":"<\\/script>"}'
    assert bg.escape_json('{"a":"<b>"}') == '{"a":"<b>"}'
    assert json.loads(bg.escape_json('["</x>"]')) == ["</x>"]  # still valid JSON


def test_replace_once_requires_exactly_one_occurrence() -> None:
    assert bg.replace_once("a-X-b", "X", "Y") == "a-Y-b"
    with pytest.raises(bg.BuildError):
        bg.replace_once("a-b", "X", "Y")
    with pytest.raises(bg.BuildError):
        bg.replace_once("X-X", "X", "Y")


def test_collect_css_sorted_by_name_and_empty_dir(tmp_path: Path) -> None:
    src = make_src(tmp_path)
    assert bg.collect_css(src / "css") == "a{}\nb{}"
    empty = tmp_path / "none"
    empty.mkdir()
    assert bg.collect_css(empty) == ""


def test_collect_js_wraps_each_file_in_name_order(tmp_path: Path) -> None:
    src = make_src(tmp_path)
    out = bg.collect_js(src / "js")
    assert out == "<script>\nvar a=1;\n</script>\n<script>\nvar x=1;\n</script>"


def test_collect_js_rejects_closing_script_tag(tmp_path: Path) -> None:
    src = make_src(tmp_path, {"bad.js": "var s='</SCRIPT>';"})
    with pytest.raises(bg.BuildError):
        bg.collect_js(src / "js")


def test_build_data_block_parts(tmp_path: Path) -> None:
    data = write_data(tmp_path, '{"x":"</p>"}')
    roads = tmp_path / "roads.json"
    streets = tmp_path / "streets.png"
    only_data = bg.build_data_block(data, roads, streets)
    assert only_data == '<script type="application/json" id="game-data">{"x":"<\\/p>"}</script>'
    roads.write_text('{"v":1}', encoding="utf-8")
    streets.write_bytes(b"\x89PNG")
    block = bg.build_data_block(data, roads, streets)
    ids = ["game-data", "roads-data", "streets-png"]
    assert [block.index(f'id="{i}"') for i in ids] == sorted(block.index(f'id="{i}"') for i in ids)
    assert "data:image/png;base64,iVBORw==" in block
    with pytest.raises(bg.BuildError):
        bg.build_data_block(tmp_path / "missing.json", roads, streets)
