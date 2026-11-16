"""The e2e scenarios and page helpers, run against a fake page (no browser needed)."""

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import e2e  # noqa: E402

Answer = Callable[..., Any]


class FakeLocator:
    """A locator with canned answers; clicks and taps are recorded."""

    def __init__(self, page: "FakePage", selector: str) -> None:
        self.page, self.selector = page, selector

    @property
    def first(self) -> "FakeLocator":
        return self

    def locator(self, selector: str) -> "FakeLocator":
        return FakeLocator(self.page, selector)

    def count(self) -> int:
        return self.page.counts.get(self.selector, 0)

    def click(self) -> None:
        self.page.log.append(("click", self.selector))

    def tap(self) -> None:
        self.page.log.append(("tap", self.selector))

    def is_visible(self) -> bool:
        return True

    def bounding_box(self) -> dict[str, float] | None:
        return self.page.boxes.get(self.selector)

    def all_inner_texts(self) -> list[str]:
        return self.page.texts.get(self.selector, [])

    def inner_text(self) -> str:
        return "#3 з 212"


class FakeMouse:
    def __init__(self, log: list[tuple[Any, ...]]) -> None:
        self.log = log

    def move(self, x: float, y: float) -> None:
        self.log.append(("move", x, y))

    def click(self, x: float, y: float) -> None:
        self.log.append(("mouse-click", x, y))

    def tap(self, x: float, y: float) -> None:
        self.log.append(("tap-at", x, y))


class FakePage:
    """The part of a Playwright page that the e2e module uses."""

    def __init__(self, answers: dict[str, Answer] | None = None) -> None:
        self.answers = answers or {}
        self.counts: dict[str, int] = {}
        self.boxes: dict[str, dict[str, float] | None] = {}
        self.texts: dict[str, list[str]] = {}
        self.log: list[tuple[Any, ...]] = []
        self.handlers: dict[str, Callable[[Any], None]] = {}
        self.mouse = FakeMouse(self.log)
        self.touchscreen = FakeMouse(self.log)

    def evaluate(self, js: str, arg: Any = None) -> Any:
        answer = self.answers[js]
        return answer(arg) if callable(answer) else answer

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector)

    def get_by_text(self, _text: str) -> FakeLocator:
        return FakeLocator(self, "hero")

    def wait_for_function(self, js: str, **_kw: Any) -> None:
        self.log.append(("wait-fn", js))

    def wait_for_selector(self, selector: str, **_kw: Any) -> None:
        self.log.append(("wait-sel", selector))

    def wait_for_timeout(self, _ms: int) -> None:
        self.log.append(("pause",))

    def screenshot(self, path: str) -> None:
        self.log.append(("shot", Path(path).name))

    def set_default_timeout(self, _ms: int) -> None:
        pass

    def goto(self, url: str) -> None:
        self.log.append(("goto", url))

    def on(self, event: str, handler: Callable[[Any], None]) -> None:
        self.handlers[event] = handler


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self.page, self.closed = page, False

    def new_page(self) -> FakePage:
        return self.page

    def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, page: FakePage) -> None:
        self.page, self.contexts = page, []

    def new_context(self, **kw: Any) -> FakeContext:
        ctx = FakeContext(self.page)
        self.contexts.append((kw, ctx))
        return ctx


def make_env(page: FakePage, tmp_path: Path) -> e2e.Env:
    return e2e.Env(FakeBrowser(page), "file:///game.html", 390, 844, tmp_path, [])


def test_ev_passes_the_argument_only_when_given() -> None:
    page = FakePage({"js": lambda arg: ("arg", arg), "js2": 5})
    assert e2e.ev(page, "js", 7) == ("arg", 7)
    assert e2e.ev(page, "js") == ("arg", None)
    assert e2e.ev(page, "js2") == 5


def test_shot_path_and_shot_record_the_last_screenshot(tmp_path: Path) -> None:
    env = make_env(FakePage(), tmp_path)
    env.num, env.name = 4, "rank"
    assert env.shot_path("x") == tmp_path / "390x844-4-rank-x.png"
    assert env.shot(env.browser.page, "x") == str(tmp_path / "390x844-4-rank-x.png")
    assert env.last_shot.endswith("rank-x.png")


def test_session_opens_the_game_collects_errors_and_closes(tmp_path: Path) -> None:
    page = FakePage()
    env = make_env(page, tmp_path)
    with env.session(touch=True) as got:
        assert got is page
        page.handlers["console"](type("M", (), {"type": "error", "text": "boom"})())
        page.handlers["console"](type("M", (), {"type": "log", "text": "fine"})())
        page.handlers["pageerror"]("bad")
    kw, ctx = env.browser.contexts[0]
    assert kw == {"viewport": {"width": 390, "height": 844}, "has_touch": True}
    assert ctx.closed
    assert env.errors == ["boom", "pageerror: bad"]
    assert ("goto", "file:///game.html") in page.log


def test_session_saves_a_fail_screenshot_on_error(tmp_path: Path) -> None:
    page = FakePage()
    env = make_env(page, tmp_path)
    env.num, env.name = 1, "menu"
    with pytest.raises(e2e.Fail), env.session():
        raise e2e.Fail("x")
    assert ("shot", "390x844-1-menu-fail.png") in page.log
    with pytest.raises(e2e.Skip), env.session():
        raise e2e.Skip("y")
    assert page.log.count(("shot", "390x844-1-menu-fail.png")) == 1


def test_start_shift_clicks_or_taps_the_first_card(tmp_path: Path) -> None:
    page = FakePage()
    e2e.start_shift(page)
    e2e.start_shift(page, touch=True)
    selector = '#shiftList [id^="shift-"]'
    assert [e[0] for e in page.log if e[0] in ("click", "tap")] == ["click", "tap"]
    assert page.log[0] == ("click", selector)
    assert page.log[1] == ("wait-fn", e2e.JS_READY)


def test_collect_pins_steps_and_labels_each_pin_with_its_time() -> None:
    snaps = iter([{"t": 150.0, "pins": [{"i": 1}]}, {"t": 300.0, "pins": [{"i": 1}, {"i": 2}]}])
    page = FakePage({e2e.JS_PAUSE_STEP: 0, e2e.JS_PINS: lambda _a: next(snaps)})
    seen = e2e.collect_pins(page, 2, 150.0)
    assert seen == [(150.0, {"i": 1}), (300.0, {"i": 1}), (300.0, {"i": 2})]


def test_wait_for_pin_returns_an_isolated_pin_or_fails() -> None:
    pin = {"i": 4, "px": 100.0, "py": 100.0, "reach": True}
    page = FakePage({e2e.JS_PAUSE_STEP: 0, e2e.JS_PINS: {"t": 1.0, "pins": [pin]}})
    assert e2e.wait_for_pin(page, 400.0) is pin
    page.answers[e2e.JS_PINS] = {"t": 1.0, "pins": []}
    with pytest.raises(e2e.Fail, match="no isolated reachable pin"):
        e2e.wait_for_pin(page, 400.0)
    steps = [e for e in page.log if e[0] == "pause"]
    assert len(steps) == 1 + e2e.PIN_PASSES + 1  # the first call, then every pass


def test_pin_passes_cover_a_whole_shift() -> None:
    assert e2e.PIN_PASSES * e2e.PIN_STEP_S == e2e.SHIFT_S


def menu_page(cards: int = 28, labels: tuple[str, ...] = e2e.EXPECTED_DIFFICULTIES) -> FakePage:
    page = FakePage()
    page.counts['#shiftList [id^="shift-"]'] = cards
    page.boxes["hero"] = {"x": 10.0, "y": 10.0, "width": 80.0, "height": 20.0}
    page.texts[".diff-btn"] = [f" {x} " for x in labels]
    return page


def test_sc_menu_passes_and_fails(tmp_path: Path) -> None:
    env = make_env(menu_page(), tmp_path)
    assert "28 cards" in e2e.sc_menu(env)
    with pytest.raises(e2e.Fail, match="27 shift cards"):
        e2e.sc_menu(make_env(menu_page(cards=27), tmp_path))
    with pytest.raises(e2e.Fail, match="difficulty buttons"):
        e2e.sc_menu(make_env(menu_page(labels=("Легко",)), tmp_path))


def test_sc_about_reports_missing_parts(tmp_path: Path) -> None:
    text = "UCI CC BY 4.0 Це дані Це ігрова модель"
    page = FakePage({e2e.JS_ABOUT: {"text": text, "nData": 6, "nModel": 6}})
    assert "data list 6 items" in e2e.sc_about(make_env(page, tmp_path))
    page.answers[e2e.JS_ABOUT] = {"text": "UCI", "nData": 1, "nModel": 6}
    with pytest.raises(e2e.Fail, match="missing: CC BY 4.0"):
        e2e.sc_about(make_env(page, tmp_path))


def rival(i: int, x: float = 100.0) -> dict[str, Any]:
    return {"id": i, "x": x + i, "y": 200.0, "color": f"#{i:02x}{i:02x}{i:02x}"}


def test_sc_rivals_skip_pass_and_fail(tmp_path: Path) -> None:
    page = FakePage({e2e.JS_RIVALS: None})
    with pytest.raises(e2e.Skip):
        e2e.sc_rivals(make_env(page, tmp_path))
    before = [rival(i) for i in range(1, 8)]
    after = [rival(i, x=150.0) for i in range(1, 8)]
    snap = {"a": before, "b": after, "draws": True}
    page.answers[e2e.JS_RIVALS] = snap
    assert "7 rivals" in e2e.sc_rivals(make_env(page, tmp_path))
    page.answers[e2e.JS_RIVALS] = {**snap, "b": after[:6], "a": before[:6]}
    with pytest.raises(e2e.Fail, match="6 rivals"):
        e2e.sc_rivals(make_env(page, tmp_path))
    page.answers[e2e.JS_RIVALS] = {**snap, "a": after}
    with pytest.raises(e2e.Fail, match="no rival moved"):
        e2e.sc_rivals(make_env(page, tmp_path))


def test_pin_target_locates_the_pin_on_the_page(tmp_path: Path) -> None:
    pin = {"i": 2, "px": 30.0, "py": 40.0, "reach": True}
    page = FakePage({e2e.JS_PAUSE_STEP: 0, e2e.JS_PINS: {"t": 1.0, "pins": [pin]}})
    env = make_env(page, tmp_path)
    page.boxes["#map"] = None
    with pytest.raises(e2e.Fail, match="#map has no box"):
        e2e.pin_target(env, page)
    page.boxes["#map"] = {"x": 5.0, "y": 10.0, "width": 300.0, "height": 600.0}
    assert e2e.pin_target(env, page) == (pin, 35.0, 50.0)


def test_check_mouse_and_check_touch_follow_the_pin(tmp_path: Path) -> None:
    pin = {"i": 2, "px": 30.0, "py": 40.0, "reach": True}
    states = iter(
        [
            {"mode": "idle", "sel": 2, "cur": None},
            {"mode": "ride", "sel": 2, "cur": 2},
        ]
    )
    cards = {"shown": True, "cls": "card sel"}
    page = FakePage(
        {
            e2e.JS_PAUSE_STEP: 0,
            e2e.JS_PINS: {"t": 1.0, "pins": [pin]},
            e2e.JS_STATE: lambda _a: next(states),
            e2e.JS_CARD: cards,
        }
    )
    page.boxes["#map"] = {"x": 0.0, "y": 0.0, "width": 300.0, "height": 600.0}
    e2e.check_touch(make_env(page, tmp_path))
    assert ("tap-at", 30.0, 40.0) in page.log
    states = iter([{"mode": "idle", "sel": 2, "cur": None}, {"mode": "pickup", "cur": 2}])
    page.answers[e2e.JS_STATE] = lambda _a: next(states)
    e2e.check_mouse(make_env(page, tmp_path))
    assert ("move", 27.0, 37.0) in page.log
    assert ("mouse-click", 30.0, 40.0) in page.log


def test_run_scenario_turns_every_ending_into_an_outcome(tmp_path: Path) -> None:
    env = make_env(FakePage(), tmp_path)

    def passes(_env: e2e.Env) -> str:
        return "fine"

    def fails(_env: e2e.Env) -> str:
        raise e2e.Fail("nope")

    def skips(_env: e2e.Env) -> str:
        raise e2e.Skip("absent")

    def crashes(_env: e2e.Env) -> str:
        raise ValueError("bad\nsecond line")

    got = [
        e2e.run_scenario(env, n, "s", fn) for n, fn in enumerate((passes, fails, skips, crashes))
    ]
    assert [o.status for o in got] == [e2e.PASS, e2e.FAIL, e2e.SKIP, e2e.FAIL]
    assert [o.reason for o in got] == ["fine", "nope", "absent", "ValueError: bad"]
    assert got[0].num == 0 and got[3].num == 3


def test_console_outcome(tmp_path: Path) -> None:
    env = make_env(FakePage(), tmp_path)
    assert e2e.console_outcome(env, 8).status == e2e.PASS
    env.errors += ["a", "b", "c", "d"]
    out = e2e.console_outcome(env, 8)
    assert out.status == e2e.FAIL and out.reason == "4: a; b; c"


def test_run_all_without_playwright_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    assert e2e.run_all(tmp_path / "g.html", 390, 844, tmp_path / "out", None) is None
    assert e2e.INSTALL_HINT in capsys.readouterr().err


def test_main_returns_usage_when_the_browser_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    html = tmp_path / "g.html"
    html.write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(e2e, "run_all", lambda *_a: None)
    assert e2e.main([str(html)]) == e2e.EXIT_USAGE
    done = [e2e.Outcome(1, "menu", e2e.PASS, "ok")]
    monkeypatch.setattr(e2e, "run_all", lambda *_a: done)
    assert e2e.main([str(html)]) == e2e.EXIT_OK


def test_constants_keep_their_values() -> None:
    assert (e2e.SHORT_HEX_DIGITS, e2e.CHANNEL_MAX, e2e.TABLE_COLUMNS) == (3, 255, 3)
    assert e2e.MAX_REASONS == 3 and e2e.TAKEN_MODES == ("pickup", "ride")


def test_sc_pins_takes_every_sampled_reachable_pin(tmp_path: Path) -> None:
    idx_js = f"() => {{ {e2e.JS_PG} return E.G.idx; }}"
    snaps = iter(
        {"t": 150.0 * k, "pins": [{"i": k, "px": 1.0, "py": 1.0, "reach": True}]}
        for k in range(1, e2e.PIN_PASSES + 1)
    )
    rows = [{"i": 1, "t": 150.0, "reach": True, "took": True, "mode": "pickup"}]
    page = FakePage(
        {
            idx_js: 3,
            e2e.JS_PAUSE_STEP: 0,
            e2e.JS_PINS: lambda _a: next(snaps),
            e2e.JS_VERIFY: lambda args: rows if args["idx"] == 3 else [],
        }
    )
    reason = e2e.sc_pins(make_env(page, tmp_path))
    assert reason.startswith("1 of ")
    rows[0]["took"] = False
    page.answers[e2e.JS_PINS] = {
        "t": 150.0,
        "pins": [{"i": 1, "px": 1.0, "py": 1.0, "reach": True}],
    }
    with pytest.raises(e2e.Fail, match="take refused"):
        e2e.sc_pins(make_env(page, tmp_path))


def test_sc_pins_fails_when_no_pin_is_ever_reachable(tmp_path: Path) -> None:
    idx_js = f"() => {{ {e2e.JS_PG} return E.G.idx; }}"
    page = FakePage({idx_js: 0, e2e.JS_PAUSE_STEP: 0, e2e.JS_PINS: {"t": 1.0, "pins": []}})
    with pytest.raises(e2e.Fail, match="no reachable pin"):
        e2e.sc_pins(make_env(page, tmp_path))


def test_sc_touch_mouse_runs_both_halves(tmp_path: Path) -> None:
    pin = {"i": 2, "px": 30.0, "py": 40.0, "reach": True}
    script = iter(
        [
            {"mode": "idle", "sel": 2, "cur": None},
            {"mode": "ride", "sel": 2, "cur": 2},
            {"mode": "idle", "sel": None, "cur": None},
            {"mode": "pickup", "sel": 2, "cur": 2},
        ]
    )
    page = FakePage(
        {
            e2e.JS_PAUSE_STEP: 0,
            e2e.JS_PINS: {"t": 1.0, "pins": [pin]},
            e2e.JS_STATE: lambda _a: next(script),
            e2e.JS_CARD: {"shown": True, "cls": "card sel"},
        }
    )
    page.boxes["#map"] = {"x": 0.0, "y": 0.0, "width": 300.0, "height": 600.0}
    assert e2e.sc_touch_mouse(make_env(page, tmp_path)).startswith("touch: tap 1 selects")


def rank_snap(rank: int, x: float) -> dict[str, Any]:
    return {"rank": rank, "nDrivers": 212, "gx": x, "gy": 100.0, "ghostMoney": x}


def test_sc_rank_ghost_compares_hud_with_engine(tmp_path: Path) -> None:
    pin = {"i": 1, "px": 1.0, "py": 1.0, "reach": True}
    ranks = iter([3] + [5] * (e2e.RANK_SAMPLES - 1))
    xs = iter(range(100, 100 + 10 * e2e.RANK_SAMPLES, 10))
    page = FakePage(
        {
            e2e.JS_PAUSE_STEP: 0,
            e2e.JS_PINS: {"t": 1.0, "pins": [pin]},
            e2e.JS_TAKE_BEST: True,
            e2e.JS_SAMPLE: lambda _a: rank_snap(next(ranks), float(next(xs))),
        }
    )
    # the fake HUD always reads "#3 з 212", so a rank of 5 is a mismatch and must fail
    with pytest.raises(e2e.Fail, match="HUD"):
        e2e.sc_rank_ghost(make_env(page, tmp_path))
    page.answers[e2e.JS_TAKE_BEST] = False
    with pytest.raises(e2e.Fail, match="could not take an order"):
        e2e.sc_rank_ghost(make_env(page, tmp_path))


def test_sc_full_shift_checks_medal_rank_and_race_table(tmp_path: Path) -> None:
    result = {"medal": "Бронза", "rank": "#3 з 212", "rows": 8, "raceTitle": e2e.RACE_TITLE}
    run = {"rides": 12, "hasAi": True}
    page = FakePage({e2e.JS_FULL_SHIFT: run, e2e.JS_RESULT: result})
    assert (
        e2e.sc_full_shift(make_env(page, tmp_path)) == "12 rides, medal «Бронза», race table 8 rows"
    )
    page.answers[e2e.JS_FULL_SHIFT] = {"rides": 12, "hasAi": False}
    assert "race table SKIP" in e2e.sc_full_shift(make_env(page, tmp_path))
    page.answers[e2e.JS_FULL_SHIFT] = run
    page.answers[e2e.JS_RESULT] = {**result, "medal": "?"}
    with pytest.raises(e2e.Fail, match="medal line"):
        e2e.sc_full_shift(make_env(page, tmp_path))
    page.answers[e2e.JS_RESULT] = {**result, "rows": 3}
    with pytest.raises(e2e.Fail, match="race table has 3 rows"):
        e2e.sc_full_shift(make_env(page, tmp_path))
