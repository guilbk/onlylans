"""The share card module and its styles ship in the built game."""

from pathlib import Path

from pipeline.build_game import collect_css, collect_js

SRC = Path(__file__).resolve().parent.parent / "game" / "src"


def test_share_js_is_bundled() -> None:
    js = collect_js(SRC / "js")
    assert "PG.share" in js and "btn-share" in js


def test_share_css_is_bundled() -> None:
    assert ".share-btn" in collect_css(SRC / "css")


def test_card_size_and_title() -> None:
    src = (SRC / "js" / "69_share.js").read_text(encoding="utf-8")
    assert "W = 1080, H = 1350" in src and "'7 ланосів'" in src
