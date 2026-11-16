"""Browser smoke test of the built game (CONTRACT section 6): menu, one shift, one order, result."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
INSTALL_HINT = "run: python -m playwright install chromium"
SHOT_DIR = Path("test-screenshots")
TIMEOUT_MS = 5000  # wait limit of one page condition, real milliseconds
PIN_STEPS = 40  # tries to find a reachable pin, each stepping 60 game seconds
MONEY_GAME_S = 1800  # game seconds to wait for the money to rise
MONEY_STEP_S = 10  # game seconds per step while waiting for the money
OVER_STEPS = 40  # steps of 600 game seconds to wait for the shift to end
POLL_MS = 100  # pause between two pin checks, real milliseconds
PIN_STEP_S = 60  # game seconds stepped while looking for a pin


class SmokeError(Exception):
    """A smoke assertion failed."""


def check(cond: object, msg: str) -> None:
    """Hard assert.

    Args:
        cond: Condition that must be truthy.
        msg: Message used when it is not.

    Raises:
        SmokeError: If ``cond`` is falsy.
    """
    if not cond:
        raise SmokeError(msg)


def find_pin(page: Any) -> dict[str, float] | None:
    """Return the reachable pin with the smallest eta (CSS px relative to ``#map``).

    Args:
        page: Playwright page.

    Returns:
        ``{px, py}`` or None if no reachable pin appeared.
    """
    js = (
        "() => { const P = window.__porto.PG; const E = P.engine; const G = E.G;"
        " const pins = P.render.pins || []; let best = null, bd = Infinity;"
        " for (const q of pins) { if (!q.reach) continue;"
        "  const d = E.preview ? E.preview(q.o).eta"
        " : Math.hypot(q.o.x0 - G.x, q.o.y0 - G.y);"
        "  if (d < bd) { bd = d; best = {px: q.px, py: q.py}; } }"
        " return best; }"
    )
    for i in range(PIN_STEPS + 1):
        page.wait_for_timeout(POLL_MS)
        pin = page.evaluate(js)
        if pin:
            return pin
        if i < PIN_STEPS:
            page.evaluate(f"() => window.__porto.PG.engine.step({PIN_STEP_S})")
    return None


def open_menu(page: Any, tag: str, errors: list[str]) -> None:
    """Smoke step 2: the menu is visible and lists shifts.

    Args:
        page: Playwright page with the game loaded.
        tag: Screenshot name tag.
        errors: Live list of collected console errors.

    Raises:
        SmokeError: If there is no shift card or there are console errors.
    """
    page.wait_for_function("() => !!window.__porto", timeout=TIMEOUT_MS)
    page.wait_for_selector("#menu", state="visible", timeout=TIMEOUT_MS)
    n_cards = page.locator('#shiftList [id^="shift-"]').count()
    check(n_cards >= 1, "no shift cards in #shiftList")
    page.screenshot(path=str(SHOT_DIR / f"smoke-{tag}-menu.png"))
    check(not errors, "console errors on load: " + "; ".join(errors))


def start_shift(page: Any) -> None:
    """Smoke step 3: click the first shift and wait until it is being played.

    Args:
        page: Playwright page on the menu.
    """
    page.locator('[id^="shift-"]').first.click()
    page.wait_for_function(
        "() => { const P = window.__porto.PG; const G = P.engine && P.engine.G;"
        " return P.screen === 'play' && !!G && !G.over; }",
        timeout=TIMEOUT_MS,
    )


def take_order(page: Any, tag: str) -> None:
    """Smoke steps 4-5: click a reachable pin and wait for the money to rise.

    Args:
        page: Playwright page in play mode.
        tag: Screenshot name tag.

    Raises:
        SmokeError: If no pin appears, the click does not book it, or the money does not rise.
    """
    pin = find_pin(page)
    check(pin, "no reachable pin appeared")
    before = page.evaluate("() => window.__porto.PG.engine.G.tot")
    box = page.locator("#map").bounding_box()
    check(box, "#map has no box")
    page.mouse.click(box["x"] + pin["px"], box["y"] + pin["py"])
    mode = page.evaluate("() => window.__porto.PG.engine.G.mode")
    check(mode in ("pickup", "ride"), f"mode after click is {mode!r}")

    rose = False
    for _ in range(MONEY_GAME_S // MONEY_STEP_S):
        page.evaluate(f"() => window.__porto.PG.engine.step({MONEY_STEP_S})")
        if page.evaluate("() => window.__porto.PG.engine.G.tot") > before:
            rose = True
            break
    check(rose, "money did not rise")
    page.screenshot(path=str(SHOT_DIR / f"smoke-{tag}-play.png"))


def finish_shift(page: Any, tag: str, errors: list[str]) -> None:
    """Smoke steps 6-7: run the shift to its end and check the result screen.

    Args:
        page: Playwright page in play mode.
        tag: Screenshot name tag.
        errors: Live list of collected console errors.

    Raises:
        SmokeError: If the shift does not end or there are console errors.
    """
    for _ in range(OVER_STEPS):
        if page.evaluate("() => window.__porto.PG.engine.G.over"):
            break
        page.evaluate("() => window.__porto.PG.engine.step(600)")
    check(page.evaluate("() => window.__porto.PG.engine.G.over"), "shift did not end")
    page.wait_for_selector("#result", state="visible", timeout=TIMEOUT_MS)
    page.screenshot(path=str(SHOT_DIR / f"smoke-{tag}-result.png"))
    check(not errors, "console errors: " + "; ".join(errors))


def run_steps(page: Any, tag: str, errors: list[str]) -> None:
    """Run the smoke steps 2-7 on an opened page.

    Args:
        page: Playwright page with the game loaded.
        tag: Screenshot name tag.
        errors: Live list of collected console errors.

    Raises:
        SmokeError: On any failed step.
    """
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    open_menu(page, tag, errors)
    start_shift(page)
    take_order(page, tag)
    finish_shift(page, tag, errors)


def smoke(html: Path, tag: str, width: int, height: int, browser: str | None) -> int:
    """Open the game in headless Chromium and run all steps.

    Args:
        html: Built game file.
        tag: Screenshot name tag.
        width: Viewport width in CSS px.
        height: Viewport height in CSS px.
        browser: Optional path of a Chromium executable.

    Returns:
        Process exit code.
    """
    try:
        from playwright.sync_api import Error as PwError
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(INSTALL_HINT, file=sys.stderr)
        return EXIT_USAGE
    errors: list[str] = []
    with sync_playwright() as pw:
        try:
            kw = {"executable_path": browser} if browser else {}
            br = pw.chromium.launch(headless=True, **kw)
        except PwError as err:
            print(f"{INSTALL_HINT}\n({str(err).splitlines()[0]})", file=sys.stderr)
            return EXIT_USAGE
        try:
            page = br.new_page(viewport={"width": width, "height": height})
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.goto(html.resolve().as_uri())
            run_steps(page, tag, errors)
        except (SmokeError, PwError) as err:
            print(f"SMOKE FAIL: {err}", file=sys.stderr)
            if errors:
                print("console errors: " + "; ".join(errors), file=sys.stderr)
            return EXIT_FAIL
        finally:
            br.close()
    print(f"SMOKE OK ({tag})")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """Command line entry point.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        0 pass, 1 failed assert, 2 usage or missing file/Playwright.
    """
    ap = argparse.ArgumentParser(description="Smoke test of the built game")
    ap.add_argument("html", type=Path)
    ap.add_argument("--tag", default="x")
    ap.add_argument("--width", type=int, default=390)
    ap.add_argument("--height", type=int, default=844)
    ap.add_argument("--browser", default=None)
    args = ap.parse_args(argv)
    if not args.html.is_file():
        print(f"file not found: {args.html}", file=sys.stderr)
        return EXIT_USAGE
    return smoke(args.html, args.tag, args.width, args.height, args.browser)


if __name__ == "__main__":
    raise SystemExit(main())
