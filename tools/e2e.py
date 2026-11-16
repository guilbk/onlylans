"""Browser scenario checks of the built game (CONTRACT section 6), beyond the smoke test.

Eight scenarios run in headless Chromium, each with a PASS / FAIL / SKIP verdict, a reason and a
screenshot. Page logic stays small; everything that can be decided in Python (parsing the rank
text, comparing colours, picking pins, judging results) is a pure helper that has unit tests.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
INSTALL_HINT = "run: python -m playwright install chromium"
OUT_DIR = Path("test-screenshots/e2e")
DEFAULT_WIDTH = 390
DEFAULT_HEIGHT = 844
TIMEOUT_MS = 8000
LONG_TIMEOUT_MS = 90000
FRAME_MS = 120

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

EXPECTED_SHIFTS = 28
EXPECTED_DIFFICULTIES = ("Легко", "Нормально", "Важко")
HERO_NAME = "Ріїн Гіслінг"
MEDAL_NAMES = ("без медалі", "Бронза", "Срібло", "Золото", "Легенда")
RACE_TITLE = "Перегони 7 ланосів"
RACE_ROWS = 8
RIVAL_COUNT = 7
PIN_SAMPLES = 20
PIN_CANDIDATES = 60
SHIFT_S = 7200  # game seconds in one shift
PIN_STEP_S = 150.0
PIN_PASSES = int(SHIFT_S / PIN_STEP_S)  # steps that cover a whole shift
LOW_MAP_SHARE = 0.5  # a pin to click must lie in the upper half of the viewport
TAKEN_MODES = ("pickup", "ride")  # engine modes after an order is taken
SAMPLE_STEP_S = 300.0
RANK_STEP_S = 290.0  # 24 samples span 6960 s: the whole shift, not past its end
X3_STEP_S = 2.0  # game s per 60 fps frame at the x3 speed: 40 x 3 / 60
BOT_EVERY = 5  # the scripted driver looks for an order every N steps
RANK_SAMPLES = 24
MIN_PIN_GAP_PX = 40.0
SHORT_HEX_DIGITS = 3  # #rgb notation
CHANNEL_MAX = 255  # largest value of an rgb() channel
MAX_REASONS = 3  # problems or errors quoted in a verdict
HOVER_APPROACH_PX = 3  # the mouse arrives at a pin from this far up-left
TABLE_COLUMNS = 3  # number, scenario, status
MAP_W_M = 15000.0
MAP_H_M = 19000.0
ABOUT_PARTS = ("UCI", "CC BY 4.0", "Це дані", "Це ігрова модель")
ABOUT_MIN_ITEMS = 5

_RANK_RE = re.compile(r"#\s*(\d+)\s*з\s*(\d+)")
_HEX_RE = re.compile(r"^#([0-9a-f]{3}|[0-9a-f]{6})$")
_RGB_RE = re.compile(r"^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)")


class Fail(Exception):
    """A scenario assertion failed."""


class Skip(Exception):
    """A scenario cannot run in this build (a module is absent)."""


@dataclass(frozen=True)
class Outcome:
    """Verdict of one scenario.

    Attributes:
        num: Scenario number 1..8.
        name: Short scenario name.
        status: One of PASS, FAIL, SKIP.
        reason: One line explaining the verdict.
        shot: Screenshot path, or an empty string.
    """

    num: int
    name: str
    status: str
    reason: str
    shot: str = ""


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested in tests/test_e2e_helpers.py)
# ---------------------------------------------------------------------------


def parse_rank(text: str) -> tuple[int, int] | None:
    """Parse the live rank text «#37 з 212».

    Args:
        text: Text of the HUD rank block.

    Returns:
        ``(rank, drivers)`` as integers (positions), or None if the text has no rank.
    """
    m = _RANK_RE.search(text)
    return (int(m.group(1)), int(m.group(2))) if m else None


def normalise_colour(value: str) -> str | None:
    """Turn a CSS colour into a lower-case ``#rrggbb`` string.

    Args:
        value: ``#rgb``, ``#rrggbb`` or ``rgb(r, g, b)`` text (any case).

    Returns:
        ``#rrggbb`` or None if the text is not a colour in these notations.
    """
    v = value.strip().lower()
    if _HEX_RE.match(v):
        digits = v[1:]
        if len(digits) == SHORT_HEX_DIGITS:
            digits = "".join(c * 2 for c in digits)
        return "#" + digits
    m = _RGB_RE.match(v)
    if m:
        r, g, b = (int(x) for x in m.groups())
        if max(r, g, b) <= CHANNEL_MAX:
            return f"#{r:02x}{g:02x}{b:02x}"
    return None


def distinct_colours(values: Sequence[str]) -> bool:
    """Tell whether every colour is valid and no two are the same.

    Args:
        values: CSS colour strings.

    Returns:
        True when all parse and all are different (an empty list is False).
    """
    norm = [normalise_colour(v) for v in values]
    return bool(norm) and None not in norm and len(set(norm)) == len(norm)


def pick_evenly(items: Sequence[Any], n: int) -> list[Any]:
    """Pick up to ``n`` items spread evenly over the list, keeping order.

    Args:
        items: Source items.
        n: How many to pick.

    Returns:
        ``items`` itself (as a list) if it has at most ``n`` items, else ``n`` spread-out ones.
    """
    if n <= 0:
        return []
    if len(items) <= n:
        return list(items)
    return [items[i * len(items) // n] for i in range(n)]


def group_by_time(pairs: Sequence[tuple[float, int]]) -> list[tuple[float, list[int]]]:
    """Group ``(game time s, order index)`` pairs by time, times ascending.

    Args:
        pairs: Observations of reachable orders.

    Returns:
        ``[(t, [indices])]`` with each index listed once, at the first time it was seen.
    """
    seen: set[int] = set()
    groups: dict[float, list[int]] = {}
    for t, i in sorted(pairs):
        if i not in seen:
            seen.add(i)
            groups.setdefault(t, []).append(i)
    return sorted(groups.items())


def pick_isolated_pin(
    pins: Sequence[dict[str, Any]], max_y: float, min_gap: float = MIN_PIN_GAP_PX
) -> dict[str, Any] | None:
    """Choose a reachable pin that no other pin is close to, in the upper part of the map.

    Args:
        pins: Dicts with ``px``, ``py`` (CSS px) and ``reach`` (bool).
        max_y: Largest allowed ``py`` in CSS px (keeps the pin clear of the bottom dock).
        min_gap: Smallest distance in CSS px to every other pin.

    Returns:
        The reachable isolated pin with the smallest ``py``, or None.
    """
    best: dict[str, Any] | None = None
    for p in pins:
        if not p["reach"] or p["py"] > max_y:
            continue
        gap = min(
            (math.hypot(p["px"] - q["px"], p["py"] - q["py"]) for q in pins if q is not p),
            default=math.inf,
        )
        if gap >= min_gap and (best is None or p["py"] < best["py"]):
            best = p
    return best


def in_viewport(box: dict[str, float] | None, width: int, height: int) -> bool:
    """Tell whether a bounding box has any part inside the viewport.

    Args:
        box: Playwright bounding box ``{x, y, width, height}`` in CSS px, or None.
        width: Viewport width, CSS px.
        height: Viewport height, CSS px.

    Returns:
        True if the box is non-empty and overlaps ``[0, width] x [0, height]``.
    """
    if not box or box["width"] <= 0 or box["height"] <= 0:
        return False
    return (
        box["x"] < width
        and box["y"] < height
        and box["x"] + box["width"] > 0
        and box["y"] + box["height"] > 0
    )


def judge_takeable(rows: Sequence[dict[str, Any]]) -> list[str]:
    """List the problems found when taking pins on fresh games.

    Args:
        rows: Per pin ``{i, t, reach, took, mode}`` (``t`` game s).

    Returns:
        One message per pin that was not reachable, was refused, or left the car idle.
    """
    problems = []
    for r in rows:
        if not r["reach"]:
            problems.append(f"order {r['i']} at t={r['t']:.0f}s: reachable() is false")
        elif not r["took"] or r["mode"] not in ("pickup", "ride"):
            problems.append(f"order {r['i']} at t={r['t']:.0f}s: take refused (mode {r['mode']})")
    return problems


def judge_rank_samples(samples: Sequence[dict[str, Any]]) -> list[str]:
    """Check the HUD rank text against the engine over a shift.

    Args:
        samples: Per sample ``{text, rank, nDrivers, ghostMoney}``.

    Returns:
        Problem messages; empty when the HUD always shows «#rank з nDrivers» of the engine and
        the rank text changed at least once.
    """
    problems = []
    shown: set[tuple[int, int]] = set()
    for k, s in enumerate(samples):
        parsed = parse_rank(s["text"])
        if parsed is None:
            problems.append(f"sample {k}: no «#N з M» in {s['text']!r}")
        elif parsed != (s["rank"], s["nDrivers"]):
            problems.append(f"sample {k}: HUD {parsed} but engine {(s['rank'], s['nDrivers'])}")
        else:
            shown.add(parsed)
    if not problems and len(shown) < 2:
        problems.append("rank never changed during the shift")
    return problems


def judge_ghost_samples(samples: Sequence[dict[str, Any]]) -> list[str]:
    """Check that the ghost car moves on the map and its money never falls.

    Args:
        samples: Per sample ``{gx, gy, ghostMoney}`` (metres, €).

    Returns:
        Problem messages; empty when positions are finite, inside the map, not all equal, and
        ``ghostMoney`` is non-decreasing.
    """
    problems = []
    points = set()
    prev = -math.inf
    for k, s in enumerate(samples):
        x, y = s["gx"], s["gy"]
        if math.isfinite(x) and math.isfinite(y) and 0 <= x <= MAP_W_M and 0 <= y <= MAP_H_M:
            points.add((round(x), round(y)))
        else:
            problems.append(f"sample {k}: ghost off the map at ({x}, {y})")
        if s["ghostMoney"] < prev:
            problems.append(f"sample {k}: ghost money fell to {s['ghostMoney']}")
        prev = s["ghostMoney"]
    if len(points) < 2:
        problems.append("ghost never moved")
    return problems


def missing_about_parts(text: str, n_data: int, n_model: int) -> list[str]:
    """List what the «Про дані» screen lacks.

    Args:
        text: Visible text of the screen.
        n_data: Number of list items in the data block.
        n_model: Number of list items in the game-model block.

    Returns:
        Names of missing phrases and too-short lists; empty if the screen is complete.
    """
    missing = [p for p in ABOUT_PARTS if p not in text]
    if n_data < ABOUT_MIN_ITEMS:
        missing.append(f"data list has {n_data} items")
    if n_model < ABOUT_MIN_ITEMS:
        missing.append(f"model list has {n_model} items")
    return missing


def format_table(outcomes: Sequence[Outcome]) -> str:
    """Render the verdicts as a plain-text table.

    Args:
        outcomes: One verdict per scenario.

    Returns:
        Multi-line text with a header and one row per scenario; the last column is the reason
        and then the screenshot file name.
    """
    rows = [("#", "scenario", "status")]
    rows += [(str(o.num), o.name, o.status) for o in outcomes]
    w = [max(len(r[c]) for r in rows) for c in range(TABLE_COLUMNS)]
    lines = []
    for r, o in zip(rows[1:], outcomes, strict=True):
        shot = f"  [{Path(o.shot).name}]" if o.shot else ""
        lines.append(f"{r[0]:<{w[0]}}  {r[1]:<{w[1]}}  {r[2]:<{w[2]}}  {o.reason}{shot}")
    head = f"{rows[0][0]:<{w[0]}}  {rows[0][1]:<{w[1]}}  {rows[0][2]:<{w[2]}}  reason  [screenshot]"
    return "\n".join([head, *lines])


def exit_code(outcomes: Sequence[Outcome]) -> int:
    """Map verdicts to a process exit code.

    Args:
        outcomes: One verdict per scenario.

    Returns:
        1 if any scenario FAILed, else 0 (SKIP is not a failure).
    """
    return EXIT_FAIL if any(o.status == FAIL for o in outcomes) else EXIT_OK


def require(cond: object, msg: str) -> None:
    """Fail the scenario unless a condition holds.

    Args:
        cond: Condition that must be truthy.
        msg: Failure reason.

    Raises:
        Fail: If ``cond`` is falsy.
    """
    if not cond:
        raise Fail(msg)


# ---------------------------------------------------------------------------
# In-page JavaScript (small, read-only except where a step needs the engine)
# ---------------------------------------------------------------------------

JS_PG = "const PG = window.__porto.PG, E = PG.engine;"
JS_READY = f"() => {{ {JS_PG} return PG.screen === 'play' && !!E.G && !E.G.over; }}"
JS_PAUSE_STEP = f"(dt) => {{ {JS_PG} E.G.paused = true; E.step(dt); return E.G.t; }}"
JS_PINS = (
    f"() => {{ {JS_PG} return {{t: E.G.t, pins: (PG.render.pins || []).map("
    "q => ({i: q.o.i, px: q.px, py: q.py, reach: q.reach}))}; }"
)
JS_VERIFY = (
    f"(args) => {{ {JS_PG} const out = [];"
    " for (const [t, ids] of args.groups) for (const i of ids) {"
    "  E.newGame(args.idx); E.step(t); const G = E.G; const o = G.sh.orders[i];"
    "  const reach = E.reachable(o); const took = E.startPickup(o);"
    "  out.push({i, t, reach, took, mode: G.mode}); }"
    " E.newGame(args.idx); E.G.paused = true; return out; }"
)
JS_STATE = (
    f"() => {{ {JS_PG} const G = E.G; return {{mode: G.mode, cur: G.cur ? G.cur.i : null,"
    " tot: G.tot, sel: PG.orders && PG.orders.selected ? PG.orders.selected.i : null}; }"
)
JS_CARD = (
    "() => { const c = document.getElementById('order-card');"
    " return c ? {cls: c.className, shown: getComputedStyle(c).display !== 'none'} : null; }"
)
JS_SAMPLE = (
    f"(dt) => {{ {JS_PG} E.G.paused = true; E.step(dt); const G = E.G; const out = {{}};"
    " PG.data.ghostAt(G.sh, G.t, out);"
    " return {gx: out.x, gy: out.y, ghostMoney: G.ghostMoney, rank: G.rank,"
    " nDrivers: G.sh.nDrivers, t: G.t}; }"
)
JS_BEST = (
    "const best = (G) => { let b = null;"
    " for (const o of G.sh.orders) {"
    "  if (E.reachable(o) && (!b || o.fare > b.fare)) b = o; }"
    " return b; };"
)
JS_TAKE_BEST = f"() => {{ {JS_PG} {JS_BEST} const b = best(E.G); return !!b && E.startPickup(b); }}"
JS_FULL_SHIFT = (
    f"(args) => {{ {JS_PG} {JS_BEST} const G = E.G; G.fast = true; let n = 0;"
    " while (!G.over) { E.step(args.dt); n++;"
    "  if (n % args.every === 0 && (G.mode === 'idle' || G.mode === 'cruise')) {"
    "   const b = best(G); if (b) E.startPickup(b); } }"
    " return {steps: n, tot: G.tot, rides: G.rides, hasAi: !!PG.ai}; }"
)
JS_RIVALS = (
    f"(dt) => {{ {JS_PG} if (!PG.ai) return null; E.G.paused = true;"
    " const snap = () => (E.G.rivals || []).map(r => ({id: r.id, color: r.color, x: r.x, y: r.y}));"
    " const a = snap(); E.step(dt); return {a, b: snap(), draws: !!PG.render.drawsRivals}; }"
)
JS_RESULT = (
    "() => { const q = s => document.querySelector(s);"
    " const rows = document.querySelectorAll('#result .race-row').length;"
    " const h = q('#result .res-race h2');"
    " return {medal: (q('#res-medal') || {}).textContent || '',"
    " rank: (q('#result .res-rank') || {}).textContent || '', rows,"
    " raceTitle: h ? h.textContent : ''}; }"
)
JS_ABOUT = (
    "() => { const a = document.getElementById('about');"
    " const n = s => a.querySelectorAll(s + ' li').length;"
    " return {text: a.innerText, nData: n('.about-data'), nModel: n('.about-model')}; }"
)


# ---------------------------------------------------------------------------
# Browser plumbing
# ---------------------------------------------------------------------------


@dataclass
class Env:
    """Shared state of one run.

    Attributes:
        browser: Playwright browser.
        url: ``file://`` URL of the game.
        width: Viewport width, CSS px.
        height: Viewport height, CSS px.
        out: Directory for screenshots.
        errors: Console errors and page errors collected from every page.
        num: Number of the scenario now running.
        name: Name of the scenario now running.
        last_shot: Path of the latest screenshot of the running scenario.
    """

    browser: Any
    url: str
    width: int
    height: int
    out: Path
    errors: list[str]
    num: int = 0
    name: str = ""
    last_shot: str = ""

    def shot_path(self, suffix: str) -> Path:
        """Return the screenshot path of the running scenario.

        Args:
            suffix: Short label such as ``menu`` or ``fail``.

        Returns:
            ``<out>/<WxH>-<num>-<name>-<suffix>.png``.
        """
        return self.out / f"{self.width}x{self.height}-{self.num}-{self.name}-{suffix}.png"

    def shot(self, page: Any, suffix: str) -> str:
        """Take a screenshot of the page.

        Args:
            page: Playwright page.
            suffix: Short label for the file name.

        Returns:
            The screenshot path as text.
        """
        path = self.shot_path(suffix)
        page.screenshot(path=str(path))
        self.last_shot = str(path)
        return self.last_shot

    @contextmanager
    def session(self, touch: bool = False) -> Iterator[Any]:
        """Open a fresh page of the game; on any error save a ``fail`` screenshot.

        Args:
            touch: Emulate a touch screen (``has_touch``) instead of a mouse-only device.

        Yields:
            The Playwright page with the game loaded and its console watched.
        """
        ctx = self.browser.new_context(
            viewport={"width": self.width, "height": self.height}, has_touch=touch
        )
        page = ctx.new_page()
        page.set_default_timeout(LONG_TIMEOUT_MS)
        page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        try:
            page.goto(self.url)
            page.wait_for_function("() => !!window.__porto", timeout=TIMEOUT_MS)
            page.wait_for_selector("#menu", state="visible", timeout=TIMEOUT_MS)
            yield page
        except Skip:
            raise
        except Exception:
            try:
                self.shot(page, "fail")
            except Exception as err:  # the page may be gone; the original error matters more
                self.errors.append(f"screenshot failed: {err}")
            raise
        finally:
            ctx.close()


def ev(page: Any, js: str, arg: Any = None) -> Any:
    """Evaluate JavaScript in the page.

    Args:
        page: Playwright page.
        js: Arrow function source.
        arg: Optional single JSON-serialisable argument.

    Returns:
        The JSON-decoded result.
    """
    return page.evaluate(js, arg) if arg is not None else page.evaluate(js)


def start_shift(page: Any, touch: bool = False) -> None:
    """Click the first shift card and wait until the game is playing.

    Args:
        page: Playwright page on the menu.
        touch: Use a touch tap instead of a mouse click.
    """
    card = page.locator('#shiftList [id^="shift-"]').first
    card.tap() if touch else card.click()
    page.wait_for_function(JS_READY, timeout=TIMEOUT_MS)


def collect_pins(page: Any, steps: int, step_s: float) -> list[tuple[float, dict[str, Any]]]:
    """Step a paused game forward and record the pins seen on screen.

    Args:
        page: Playwright page in play mode.
        steps: Number of steps.
        step_s: Game seconds per step.

    Returns:
        ``(game time s, pin)`` for every pin seen, in time order.
    """
    seen: list[tuple[float, dict[str, Any]]] = []
    for _ in range(steps):
        ev(page, JS_PAUSE_STEP, step_s)
        page.wait_for_timeout(FRAME_MS)
        snap = ev(page, JS_PINS)
        seen += [(snap["t"], p) for p in snap["pins"]]
    return seen


def wait_for_pin(page: Any, max_y: float) -> dict[str, Any]:
    """Step a paused game until an isolated reachable pin is on screen.

    Args:
        page: Playwright page in play mode.
        max_y: Largest allowed pin ``py``, CSS px.

    Returns:
        The pin dict ``{i, px, py, reach}``.

    Raises:
        Fail: If no such pin appears in the whole shift.
    """
    for _ in range(PIN_PASSES + 1):
        ev(page, JS_PAUSE_STEP, PIN_STEP_S)
        page.wait_for_timeout(FRAME_MS)
        pin = pick_isolated_pin(ev(page, JS_PINS)["pins"], max_y)
        if pin:
            return pin
    raise Fail("no isolated reachable pin appeared during the shift")


# ---------------------------------------------------------------------------
# Scenarios: each returns a reason (PASS) or raises Fail / Skip
# ---------------------------------------------------------------------------


def sc_menu(env: Env) -> str:
    """Scenario 1: 28 shift cards, the hero name and the difficulty buttons.

    Args:
        env: Shared run state (viewport, screenshot directory, console error list).

    Returns:
        One line that says what was checked, for the PASS row.

    Raises:
        Fail: If an assertion of the scenario fails.
        Skip: If a module the scenario needs is absent from the build.
    """
    with env.session() as page:
        cards = page.locator('#shiftList [id^="shift-"]').count()
        require(cards == EXPECTED_SHIFTS, f"{cards} shift cards, expected {EXPECTED_SHIFTS}")
        hero = page.get_by_text(HERO_NAME).first
        require(hero.is_visible(), f"«{HERO_NAME}» is not visible")
        require(
            in_viewport(hero.bounding_box(), env.width, env.height),
            f"«{HERO_NAME}» is outside the viewport",
        )
        labels = [t.strip() for t in page.locator(".diff-btn").all_inner_texts()]
        require(tuple(labels) == EXPECTED_DIFFICULTIES, f"difficulty buttons are {labels}")
        require(page.locator(".diff-btn").first.is_visible(), "difficulty buttons are hidden")
        env.shot(page, "menu")
    return f"{cards} cards, «{HERO_NAME}» in view, buttons {'/'.join(labels)}"


def sc_pins(env: Env) -> str:
    """Scenario 2: every sampled reachable pin is takeable on a fresh game.

    Args:
        env: Shared run state (viewport, screenshot directory, console error list).

    Returns:
        One line that says what was checked, for the PASS row.

    Raises:
        Fail: If an assertion of the scenario fails.
        Skip: If a module the scenario needs is absent from the build.
    """
    with env.session() as page:
        start_shift(page)
        idx = ev(page, f"() => {{ {JS_PG} return E.G.idx; }}")
        seen = collect_pins(page, PIN_PASSES, PIN_STEP_S)
        pairs = [(t, p["i"]) for t, p in seen if p["reach"]]
        groups = group_by_time(pairs)
        require(groups, "no reachable pin was ever on screen")
        flat = pick_evenly([(t, i) for t, ids in groups for i in ids], PIN_SAMPLES)
        require(len(flat) >= 1, "no pins to check")
        chosen = group_by_time(flat)
        rows = ev(page, JS_VERIFY, {"idx": idx, "groups": chosen})
        problems = judge_takeable(rows)
        env.shot(page, "pins")
        require(not problems, "; ".join(problems[:MAX_REASONS]))
    return f"{len(rows)} of {len({i for _, i in pairs})} reachable pins taken on fresh games"


def pin_target(env: Env, page: Any) -> tuple[dict[str, Any], float, float]:
    """Wait for an isolated pin and locate it on the page.

    Args:
        env: Shared run state (the viewport height bounds the pin).
        page: Playwright page in play mode.

    Returns:
        ``(pin, x, y)``: the pin dict and its position in page CSS px.

    Raises:
        Fail: If no pin appears or ``#map`` has no box.
    """
    pin = wait_for_pin(page, env.height * LOW_MAP_SHARE)
    box = page.locator("#map").bounding_box()
    require(box, "#map has no box")
    return pin, box["x"] + pin["px"], box["y"] + pin["py"]


def check_touch(env: Env) -> None:
    """Touch half of scenario 3: the first tap selects the card, the second takes the order.

    Args:
        env: Shared run state.

    Raises:
        Fail: If a tap does not behave as described.
    """
    with env.session(touch=True) as page:
        start_shift(page, touch=True)
        pin, x, y = pin_target(env, page)
        page.touchscreen.tap(x, y)
        page.wait_for_timeout(FRAME_MS * 2)
        st, card = ev(page, JS_STATE), ev(page, JS_CARD)
        require(card and card["shown"] and "sel" in card["cls"], f"touch: no selected card {card}")
        require(st["mode"] == "idle", f"touch: first tap took the order (mode {st['mode']})")
        require(st["sel"] == pin["i"], f"touch: selected {st['sel']}, expected {pin['i']}")
        env.shot(page, "touch1")
        page.touchscreen.tap(x, y)
        page.wait_for_timeout(FRAME_MS)
        st = ev(page, JS_STATE)
        require(st["mode"] in TAKEN_MODES and st["cur"] == pin["i"], f"touch: 2nd tap {st}")
        env.shot(page, "touch2")


def check_mouse(env: Env) -> None:
    """Mouse half of scenario 3: hover shows the card, a click takes the order.

    Args:
        env: Shared run state.

    Raises:
        Fail: If the hover or the click does not behave as described.
    """
    with env.session() as page:
        start_shift(page)
        pin, x, y = pin_target(env, page)
        page.mouse.move(x - HOVER_APPROACH_PX, y - HOVER_APPROACH_PX)
        page.mouse.move(x, y)
        page.wait_for_timeout(FRAME_MS * 2)
        card, st = ev(page, JS_CARD), ev(page, JS_STATE)
        require(card and card["shown"], f"mouse: hover shows no card {card}")
        require(st["mode"] == "idle", f"mouse: hover took the order (mode {st['mode']})")
        env.shot(page, "hover")
        page.mouse.click(x, y)
        page.wait_for_timeout(FRAME_MS)
        st = ev(page, JS_STATE)
        require(st["mode"] in TAKEN_MODES and st["cur"] == pin["i"], f"mouse: click {st}")


def sc_touch_mouse(env: Env) -> str:
    """Scenario 3: touch needs two taps, mouse hover shows the card and a click takes.

    Args:
        env: Shared run state.

    Returns:
        One line that says what was checked, for the PASS row.

    Raises:
        Fail: If an assertion of the scenario fails.
    """
    check_touch(env)
    check_mouse(env)
    return "touch: tap 1 selects (card), tap 2 takes; mouse: hover card, click takes"


def sc_rank_ghost(env: Env) -> str:
    """Scenario 4: ghost car moves, live rank «#N з M» matches the engine and changes.

    Args:
        env: Shared run state (viewport, screenshot directory, console error list).

    Returns:
        One line that says what was checked, for the PASS row.

    Raises:
        Fail: If an assertion of the scenario fails.
        Skip: If a module the scenario needs is absent from the build.
    """
    with env.session() as page:
        start_shift(page)
        wait_for_pin(page, float(env.height))
        require(ev(page, JS_TAKE_BEST), "could not take an order to move the rank")
        samples = []
        for _ in range(RANK_SAMPLES):
            snap = ev(page, JS_SAMPLE, RANK_STEP_S)
            page.wait_for_timeout(FRAME_MS)
            snap["text"] = page.locator("#hud-rank").locator("..").inner_text()
            samples.append(snap)
        env.shot(page, "rank")
        problems = judge_rank_samples(samples) + judge_ghost_samples(samples)
        require(not problems, "; ".join(problems[:MAX_REASONS]))
    ranks = sorted({s["rank"] for s in samples})
    return f"HUD «#N з M» matches engine, {len(ranks)} distinct ranks, ghost moved"


def sc_full_shift(env: Env) -> str:
    """Scenario 5: a full shift at x3 ends on the result screen with a medal line.

    Args:
        env: Shared run state (viewport, screenshot directory, console error list).

    Returns:
        One line that says what was checked, for the PASS row.

    Raises:
        Fail: If an assertion of the scenario fails.
        Skip: If a module the scenario needs is absent from the build.
    """
    with env.session() as page:
        start_shift(page)
        run = ev(page, JS_FULL_SHIFT, {"dt": X3_STEP_S, "every": BOT_EVERY})
        page.wait_for_selector("#result", state="visible", timeout=TIMEOUT_MS)
        page.wait_for_function(
            "() => (document.getElementById('res-medal') || {}).textContent", timeout=TIMEOUT_MS
        )
        res = ev(page, JS_RESULT)
        env.shot(page, "result")
        require(res["medal"] in MEDAL_NAMES, f"medal line is {res['medal']!r}")
        require(parse_rank(res["rank"]), f"result rank line is {res['rank']!r}")
        if not run["hasAi"]:
            return f"{run['rides']} rides, medal «{res['medal']}»; race table SKIP (no PG.ai)"
        require(res["raceTitle"] == RACE_TITLE, f"race title is {res['raceTitle']!r}")
        require(res["rows"] == RACE_ROWS, f"race table has {res['rows']} rows, not {RACE_ROWS}")
    return f"{run['rides']} rides, medal «{res['medal']}», race table {res['rows']} rows"


def sc_rivals(env: Env) -> str:
    """Scenario 6: all 7 rivals are on the map with 7 distinct colours.

    Args:
        env: Shared run state (viewport, screenshot directory, console error list).

    Returns:
        One line that says what was checked, for the PASS row.

    Raises:
        Fail: If an assertion of the scenario fails.
        Skip: If a module the scenario needs is absent from the build.
    """
    with env.session() as page:
        start_shift(page)
        snap = ev(page, JS_RIVALS, SAMPLE_STEP_S)
        env.shot(page, "rivals")
        if snap is None:
            raise Skip("PG.ai is absent in this build")
        rivals = snap["b"]
        require(len(rivals) == RIVAL_COUNT, f"{len(rivals)} rivals, expected {RIVAL_COUNT}")
        require(distinct_colours([r["color"] for r in rivals]), "rival colours are not 7 distinct")
        off = [r["id"] for r in rivals if not (0 <= r["x"] <= MAP_W_M and 0 <= r["y"] <= MAP_H_M)]
        require(not off, f"rivals off the map: {off}")
        require(snap["draws"], "PG.render.drawsRivals is not true")
        moved = sum(
            1
            for a, b in zip(snap["a"], rivals, strict=True)
            if (a["x"], a["y"]) != (b["x"], b["y"])
        )
        require(moved > 0, "no rival moved")
    return f"{len(rivals)} rivals on the map, 7 distinct colours, {moved} moved"


def sc_about(env: Env) -> str:
    """Scenario 7: «Про дані» opens and lists data against the game model.

    Args:
        env: Shared run state (viewport, screenshot directory, console error list).

    Returns:
        One line that says what was checked, for the PASS row.

    Raises:
        Fail: If an assertion of the scenario fails.
        Skip: If a module the scenario needs is absent from the build.
    """
    with env.session() as page:
        page.locator("#btn-about").click()
        page.wait_for_selector("#about", state="visible", timeout=TIMEOUT_MS)
        info = ev(page, JS_ABOUT)
        env.shot(page, "about")
        missing = missing_about_parts(info["text"], info["nData"], info["nModel"])
        require(not missing, "missing: " + "; ".join(missing))
    return f"data list {info['nData']} items, game-model list {info['nModel']} items, source named"


SCENARIOS: tuple[tuple[str, Callable[[Env], str]], ...] = (
    ("menu", sc_menu),
    ("pins-takeable", sc_pins),
    ("touch-mouse", sc_touch_mouse),
    ("rank-ghost", sc_rank_ghost),
    ("full-shift", sc_full_shift),
    ("rivals", sc_rivals),
    ("about", sc_about),
)


def run_scenario(env: Env, num: int, name: str, fn: Callable[[Env], str]) -> Outcome:
    """Run one scenario and turn the result into a verdict.

    Args:
        env: Shared run state.
        num: Scenario number.
        name: Scenario name.
        fn: Scenario function.

    Returns:
        PASS with the reason, SKIP, or FAIL with the error text.
    """
    env.num, env.name, env.last_shot = num, name, ""
    try:
        reason = fn(env)
    except Skip as skip:
        return Outcome(num, name, SKIP, str(skip), env.last_shot)
    except Fail as err:
        return Outcome(num, name, FAIL, str(err), env.last_shot)
    except Exception as err:  # a browser or script error is a failed scenario, not a crash
        text = f"{type(err).__name__}: {str(err).splitlines()[0]}"
        return Outcome(num, name, FAIL, text, env.last_shot)
    return Outcome(num, name, PASS, reason, env.last_shot)


def console_outcome(env: Env, num: int) -> Outcome:
    """Scenario 8: no console errors were seen in any scenario.

    Args:
        env: Shared run state with the collected errors.
        num: Scenario number.

    Returns:
        PASS if the error list is empty, else FAIL with the first messages.
    """
    if env.errors:
        return Outcome(
            num, "console-clean", FAIL, f"{len(env.errors)}: " + "; ".join(env.errors[:MAX_REASONS])
        )
    return Outcome(num, "console-clean", PASS, "no console errors or page errors")


def run_all(
    html: Path, width: int, height: int, out: Path, browser_path: str | None
) -> list[Outcome] | None:
    """Run every scenario in headless Chromium.

    Args:
        html: Built game file.
        width: Viewport width, CSS px.
        height: Viewport height, CSS px.
        out: Screenshot directory.
        browser_path: Optional Chromium executable.

    Returns:
        Verdicts for scenarios 1..8, or None if Playwright or its browser is missing.
    """
    try:
        from playwright.sync_api import Error as PwError
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(INSTALL_HINT, file=sys.stderr)
        return None
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        try:
            kw = {"executable_path": browser_path} if browser_path else {}
            br = pw.chromium.launch(headless=True, **kw)
        except PwError as err:
            print(f"{INSTALL_HINT}\n({str(err).splitlines()[0]})", file=sys.stderr)
            return None
        env = Env(br, html.resolve().as_uri(), width, height, out, [])
        try:
            outcomes = [run_scenario(env, n, name, fn) for n, (name, fn) in enumerate(SCENARIOS, 1)]
            outcomes.append(console_outcome(env, len(SCENARIOS) + 1))
        finally:
            br.close()
    return outcomes


def main(argv: list[str] | None = None) -> int:
    """Command line entry point.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        0 all scenarios pass or skip, 1 any FAIL, 2 usage, missing file or missing Playwright.
    """
    ap = argparse.ArgumentParser(description="Browser scenario checks of the built game")
    ap.add_argument("html", type=Path)
    ap.add_argument("--width", type=int, default=DEFAULT_WIDTH, help="viewport width, CSS px")
    ap.add_argument("--height", type=int, default=DEFAULT_HEIGHT, help="viewport height, CSS px")
    ap.add_argument("--out", type=Path, default=OUT_DIR, help="screenshot directory")
    ap.add_argument("--browser", default=None, help="path of a Chromium executable")
    args = ap.parse_args(argv)
    if not args.html.is_file():
        print(f"file not found: {args.html}", file=sys.stderr)
        return EXIT_USAGE
    outcomes = run_all(args.html, args.width, args.height, args.out, args.browser)
    if outcomes is None:
        return EXIT_USAGE
    print(format_table(outcomes))
    return exit_code(outcomes)


if __name__ == "__main__":
    raise SystemExit(main())
