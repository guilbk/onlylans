"""Tests for tools/smoke.py that need no browser (a fake page stands in for Playwright)."""

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import smoke  # noqa: E402


class FakeLocator:
    """Locator stub: a click is recorded, a count is fixed."""

    def __init__(self, page: "FakePage", count: int = 1) -> None:
        self.page, self._count = page, count
        self.first = self

    def count(self) -> int:
        return self._count

    def click(self) -> None:
        self.page.log.append("click-first")

    def bounding_box(self) -> dict[str, float] | None:
        return self.page.box


class FakeMouse:
    def __init__(self, page: "FakePage") -> None:
        self.page = page

    def click(self, x: float, y: float) -> None:
        self.page.log.append(f"mouse {x:g},{y:g}")
        self.page.mode = "pickup"


class FakePage:
    """Plays a tiny game: money rises per ``step(10)``, the shift ends after ``step(600)``."""

    def __init__(self, pin_after: int | None = 0, cards: int = 1, rises: bool = True) -> None:
        self.log: list[str] = []
        self.steps_60 = 0
        self.pin_after = pin_after
        self.cards = cards
        self.rises = rises
        self.box: dict[str, float] | None = {"x": 10.0, "y": 20.0}
        self.mode = "idle"
        self.tot = 0.0
        self.over = False
        self.mouse = FakeMouse(self)

    def wait_for_timeout(self, ms: int) -> None:
        self.log.append(f"wait {ms}")

    def wait_for_function(self, js: str, timeout: int) -> None:
        self.log.append("wait_for_function")

    def wait_for_selector(self, sel: str, state: str, timeout: int) -> None:
        self.log.append(f"selector {sel}")

    def screenshot(self, path: str) -> None:
        self.log.append(f"shot {Path(path).name}")

    def locator(self, sel: str) -> FakeLocator:
        return FakeLocator(self, self.cards)

    def evaluate(self, js: str) -> Any:
        if "step(60)" in js:
            self.steps_60 += 1
        elif "step(10)" in js:
            self.tot += 1.0 if self.rises else 0.0
        elif "step(600)" in js:
            self.over = True
        elif "reach" in js:
            ready = self.pin_after is not None and self.steps_60 >= self.pin_after
            return {"px": 5.0, "py": 6.0} if ready else None
        elif js.endswith("G.tot") or "G.tot" in js:
            return self.tot
        elif "G.mode" in js:
            return self.mode
        elif "G.over" in js:
            return self.over
        return None


def test_check_raises_only_on_falsy() -> None:
    smoke.check(1, "fine")
    with pytest.raises(smoke.SmokeError, match="boom"):
        smoke.check(0, "boom")


def test_find_pin_immediately_after_steps_and_never() -> None:
    assert smoke.find_pin(FakePage(pin_after=0)) == {"px": 5.0, "py": 6.0}
    late = FakePage(pin_after=3)
    assert smoke.find_pin(late) == {"px": 5.0, "py": 6.0} and late.steps_60 == 3
    never = FakePage(pin_after=None)
    assert smoke.find_pin(never) is None and never.steps_60 == smoke.PIN_STEPS


def test_open_menu_needs_cards_and_no_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(smoke, "SHOT_DIR", tmp_path)
    page = FakePage()
    smoke.open_menu(page, "t", [])
    assert "shot smoke-t-menu.png" in page.log
    with pytest.raises(smoke.SmokeError, match="no shift cards"):
        smoke.open_menu(FakePage(cards=0), "t", [])
    with pytest.raises(smoke.SmokeError, match="console errors"):
        smoke.open_menu(FakePage(), "t", ["TypeError"])


def test_take_order_clicks_the_pin_and_sees_money_rise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(smoke, "SHOT_DIR", tmp_path)
    page = FakePage()
    smoke.take_order(page, "t")
    assert "mouse 15,26" in page.log and "shot smoke-t-play.png" in page.log
    with pytest.raises(smoke.SmokeError, match="money did not rise"):
        smoke.take_order(FakePage(rises=False), "t")
    with pytest.raises(smoke.SmokeError, match="no reachable pin"):
        smoke.take_order(FakePage(pin_after=None), "t")


def test_finish_shift_runs_to_the_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smoke, "SHOT_DIR", tmp_path)
    page = FakePage()
    smoke.finish_shift(page, "t", [])
    assert page.over and "shot smoke-t-result.png" in page.log
    with pytest.raises(smoke.SmokeError, match="console errors"):
        smoke.finish_shift(FakePage(), "t", ["oops"])


def test_run_steps_runs_all_steps_in_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shots = tmp_path / "shots"
    monkeypatch.setattr(smoke, "SHOT_DIR", shots)
    page = FakePage()
    smoke.run_steps(page, "t", [])
    names = [e for e in page.log if e.startswith("shot")]
    assert names == ["shot smoke-t-menu.png", "shot smoke-t-play.png", "shot smoke-t-result.png"]
    assert shots.is_dir()


def test_main_exit_codes_for_a_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    assert smoke.main([str(tmp_path / "nope.html")]) == smoke.EXIT_USAGE
    assert "file not found" in capsys.readouterr().err
