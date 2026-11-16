import contextlib
import http.client
import json
import random
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pipeline import build_game

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import party  # noqa: E402


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def make() -> tuple[party.Party, Clock]:
    clock = Clock()
    return party.Party(clock), clock


def running(n: int = 2) -> tuple[party.Party, Clock, list[party.Player]]:
    p, clock = make()
    players = [p.join(f"P{i}")[0] for i in range(n)]
    p.start(p.token, 3, "hard", 180, 5)
    clock.t += 6
    return p, clock, players


def test_join_names_and_colours() -> None:
    p, _ = make()
    a, _ = p.join("")
    b, _ = p.join("  Ріїн   Гіслінг ")
    c, _ = p.join("ріїн гіслінг")
    assert a.name == "Таксист 1"
    assert b.name == "Ріїн Гіслінг"
    assert c.name == "ріїн гіслінг 2"
    assert len({a.color, b.color, c.color}) == 3
    assert "key" not in json.dumps(p.state())


def test_name_is_cleaned_and_clipped() -> None:
    assert party.clean_name("a\nb\tc") == "a b c"
    assert len(party.clean_name("x" * 100)) == party.MAX_NAME
    assert party.clean_name(42) == ""


def test_rejoin_with_key_keeps_the_player() -> None:
    p, _ = make()
    a, _ = p.join("A")
    again, _ = p.join("other name", a.key)
    assert again is a
    assert len(p.state()["players"]) == 1


def test_room_is_limited() -> None:
    p, _ = make()
    for i in range(party.MAX_PLAYERS):
        p.join(f"n{i}")
    with pytest.raises(party.PartyError) as err:
        p.join("one more")
    assert err.value.code == "full"


def test_phases_lobby_running_done() -> None:
    p, clock = make()
    p.join("A")
    assert p.state()["phase"] == "lobby"
    s = p.start(p.token, 2, "easy", 100, 4)
    assert s["phase"] == "running"
    assert s["start_at"] == clock.t + 4
    assert (s["shift"], s["difficulty"], s["duration"]) == (2, "easy", 100)
    clock.t += 4 + 100 + party.GRACE_S - 0.1
    assert p.state()["phase"] == "running"
    clock.t += 0.2
    assert p.state()["phase"] == "done"
    with pytest.raises(party.PartyError) as err:
        p.join("late")
    assert err.value.status == 409


def test_start_validates_and_only_from_lobby() -> None:
    p, _ = make()
    with pytest.raises(party.PartyError):
        p.start(p.token, 0, "impossible")
    with pytest.raises(party.PartyError):
        p.start(p.token, "zero", "easy")
    p.start(p.token, 0, "easy", 1e9, -5)
    st = p.state()
    assert st["duration"] == party.DURATION_RANGE[1]
    assert st["start_at"] == st["now"]
    with pytest.raises(party.PartyError) as err:
        p.start(p.token, 0, "easy")
    assert err.value.status == 409


def test_first_claim_wins_and_the_loser_learns_the_name() -> None:
    p, _, (a, b) = running()
    assert p.claim(a.key, 7) == (True, None)
    assert p.claim(b.key, 7) == (False, "P0")
    assert p.claim(a.key, 7) == (True, None)  # the owner may repeat
    assert p.state()["claims"] == {"7": a.id}


def test_claim_needs_a_running_game_and_a_known_key() -> None:
    p, _ = make()
    a, _ = p.join("A")
    with pytest.raises(party.PartyError) as err:
        p.claim(a.key, 1)
    assert err.value.code == "phase"
    p.start(p.token, 0, "easy", 100, 0)
    with pytest.raises(party.PartyError) as err2:
        p.claim("nope", 1)
    assert err2.value.status == 403
    with pytest.raises(party.PartyError):
        p.claim(a.key, "x")


def test_release_only_by_the_owner() -> None:
    p, _, (a, b) = running()
    p.claim(a.key, 3)
    assert p.release(b.key, 3) is False
    assert p.release(a.key, 3) is True
    assert p.claim(b.key, 3) == (True, None)


def test_concurrent_claims_have_one_winner() -> None:
    p, _, players = running(8)
    wins: list[bool] = []

    def go(key: str) -> None:
        wins.append(p.claim(key, 99)[0])

    threads = [threading.Thread(target=go, args=(pl.key,)) for pl in players]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert wins.count(True) == 1


def test_sync_stores_clamped_numbers_and_rejects_junk() -> None:
    p, _, (a, _b) = running()
    assert p.state()["players"][0]["x"] is None
    st = p.sync(a.key, {"x": 100.5, "y": -3, "hx": 5, "hy": 0, "money": 12.345, "trips": 4})
    me = st["players"][0]
    assert (me["x"], me["y"], me["hx"], me["money"], me["trips"]) == (100.5, -3, 1.0, 12.35, 4)
    for bad in ({"x": "1", "y": 2}, {"money": float("nan")}, {"money": True}):
        with pytest.raises(party.PartyError):
            p.sync(a.key, bad)


def test_offline_flag_and_reset() -> None:
    p, clock, (a, b) = running()
    p.sync(a.key, {"money": 50})
    clock.t += party.OFFLINE_S + 1
    p.sync(a.key, {})  # only A stays in touch
    online = {x["name"]: x["online"] for x in p.state()["players"]}
    assert online == {"P0": True, "P1": False}
    p.claim(a.key, 1)
    st = p.reset(p.token)
    assert st["phase"] == "lobby"
    assert [x["name"] for x in st["players"]] == ["P0"]
    assert st["players"][0]["money"] == 0
    assert st["claims"] == {}
    with pytest.raises(party.PartyError):
        p.sync(b.key, {})


# ---- rooms, tokens, lobby ----


def test_host_is_the_first_player_and_the_token_is_checked() -> None:
    p, _ = make()
    a, st = p.join("A")
    p.join("B")
    assert st["host"] == a.id
    assert p.state()["room"] == ""
    for bad in (None, "", "nope", 5):
        with pytest.raises(party.PartyError) as err:
            p.start(bad, 0, "easy")
        assert (err.value.status, err.value.code) == (403, "host_only")
    with pytest.raises(party.PartyError):
        p.reset("nope")
    assert p.start(p.token, 0, "easy", 60, 0)["phase"] == "running"
    assert "token" not in json.dumps(p.state())


def test_lobby_drops_silent_guests_but_keeps_the_host() -> None:
    p, clock = make()
    h, _ = p.join("Host")
    g, _ = p.join("Guest")
    clock.t += party.LOBBY_DROP_S + 1
    assert [x["name"] for x in p.state()["players"]] == ["Host"]
    with pytest.raises(party.PartyError):
        p.sync(g.key, {})
    p.sync(h.key, {})  # the host is still known


def test_sync_stamps_the_position_time() -> None:
    p, clock, (a, _b) = running()
    clock.t += 1
    st = p.sync(a.key, {"x": 1, "y": 2})
    assert st["players"][0]["at"] == clock.t
    p.sync(a.key, {"money": 5})
    assert p.state()["players"][0]["at"] == clock.t


def test_room_codes() -> None:
    assert party.clean_code(" bc d ") == "BCD"
    assert party.clean_code("ВКМН") == "BKMH"  # Cyrillic lookalikes
    assert party.clean_code("bcdfghj") == "BCDF"
    assert party.clean_code(5) == ""
    assert not set(party.CODE_ALPHABET) & set("AEIOUQ01")


def test_rooms_are_separate_and_codes_unique() -> None:
    clock = Clock()
    rooms = party.Rooms(clock, random.Random(1))
    a, ha, _ = rooms.create("A")
    b, hb, _ = rooms.create("B")
    assert a.code != b.code
    assert len(a.code) == party.CODE_LEN
    assert set(a.code) <= set(party.CODE_ALPHABET)
    assert a.token != b.token
    assert rooms.get(a.code.lower()) is a
    assert rooms.get(f" {b.code[:2]} {b.code[2:]}") is b
    a.join("A2")
    assert len(a.state()["players"]) == 2
    assert len(b.state()["players"]) == 1
    assert (ha.id, hb.id) == (1, 1)
    with pytest.raises(party.PartyError) as err:
        rooms.get("BBBB")
    assert (err.value.status, err.value.code) == (404, "no_room")
    # a token of one room does not open another
    with pytest.raises(party.PartyError):
        b.start(a.token, 0, "easy")


def test_rooms_forget_idle_ones_and_are_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock()
    rooms = party.Rooms(clock, random.Random(2))
    old, _, _ = rooms.create("old")
    clock.t += party.ROOM_TTL_S + 1
    rooms.create("new")
    with pytest.raises(party.PartyError):
        rooms.get(old.code)
    monkeypatch.setattr(party, "MAX_ROOMS", 2)
    rooms.create("third")
    with pytest.raises(party.PartyError) as err:
        rooms.create("fourth")
    assert err.value.status == 503


def test_join_link_uses_the_callers_address_or_the_lan_one() -> None:
    assert party.join_link("192.168.1.5:8090", "BCDF") == "http://192.168.1.5:8090/?room=BCDF"
    lan = "http://10.0.0.2:8090/"
    assert party.join_link("127.0.0.1:8090", "BCDF", lan) == lan + "?room=BCDF"
    assert party.join_link("localhost:8090", "BCDF", lan) == lan + "?room=BCDF"
    assert party.join_link("10.0.0.7:8090", "BCDF", lan) == "http://10.0.0.7:8090/?room=BCDF"


def test_qr_payload_rows_are_square() -> None:
    q = party.qr_payload("http://192.168.1.5:8090/?room=BCDF")
    assert q["url"].endswith("?room=BCDF")
    assert len(q["rows"]) == len(q["rows"][0]) >= 21
    assert set("".join(q["rows"])) == {"0", "1"}
    assert party.qr_payload("")["rows"] == []
    assert party.qr_payload("x" * 500)["rows"] == []


# ---- one real HTTP round on a free port ----

JSON = {"Content-Type": "application/json"}


def call(port: int, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    data = json.dumps(body) if body is not None else None
    conn.request(method, path, body=data, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    return resp.status, json.loads(raw) if raw[:1] == b"{" else {"raw": raw.decode()}


@contextlib.contextmanager
def serving(directory: Path, lan_base: str = "") -> Iterator[int]:
    server = party.make_party_server(
        directory, 0, party.Rooms(), host="127.0.0.1", lan_base=lan_base
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_http_round(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<title>game</title>", encoding="utf-8")
    with serving(tmp_path) as port:
        status, page = call(port, "GET", "/?room=BCDF")
        assert status == 200
        assert "<title>game</title>" in page["raw"]
        status, host = call(port, "POST", "/api/create", {"name": "Анна"})
        assert status == 200
        room = host["room"]
        assert host["state"]["host"] == host["id"]
        status, b = call(port, "POST", "/api/join", {"room": room.lower(), "name": ""})
        assert (status, b["state"]["players"][1]["name"]) == (200, "Таксист 2")
        claim = {"room": room, "key": host["key"], "order": 1}
        assert call(port, "POST", "/api/claim", claim)[0] == 409
        bad = {"room": room, "token": b["key"], "shift": 1, "difficulty": "normal"}
        assert call(port, "POST", "/api/start", bad) == (403, {"error": "host_only"})
        go = {
            "room": room,
            "token": host["token"],
            "shift": 1,
            "difficulty": "normal",
            "countdown": 0,
        }
        status, st = call(port, "POST", "/api/start", go)
        assert (status, st["phase"]) == (200, "running")
        ok = call(port, "POST", "/api/claim", {**claim, "order": 5})[1]
        lost = call(port, "POST", "/api/claim", {"room": room, "key": b["key"], "order": 5})[1]
        assert ok == {"ok": True, "by": None}
        assert lost == {"ok": False, "by": "Анна"}
        sync = {"room": room, "key": b["key"], "x": 5, "y": 6, "money": 9}
        status, st = call(port, "POST", "/api/sync", sync)
        assert st["players"][1]["money"] == 9
        assert st["claims"] == {"5": host["id"]}
        assert call(port, "GET", f"/api/party?room={room}")[1]["claims"] == {"5": host["id"]}
        assert call(port, "POST", "/api/sync", {"room": room, "key": "bad"})[0] == 403
        assert call(port, "POST", "/api/sync", {"room": "BBBB", "key": "bad"})[0] == 404
        assert call(port, "GET", "/api/party?room=BBBB") == (404, {"error": "no_room"})
        assert call(port, "POST", "/api/nothing", {"room": room})[0] == 404
        assert call(port, "GET", "/api/nothing")[0] == 404
        assert call(port, "POST", "/api/reset", {"room": room, "token": "x"})[0] == 403
        done = call(port, "POST", "/api/reset", {"room": room, "token": host["token"]})
        assert done[1]["phase"] == "lobby"


def test_http_serves_the_qr_of_the_room(tmp_path: Path) -> None:
    with serving(tmp_path, "http://10.0.0.2:8090/") as port:
        room = call(port, "POST", "/api/create", {"name": "A"})[1]["room"]
        status, q = call(port, "GET", f"/api/qr?room={room}")
        assert status == 200
        assert q["url"] == f"http://10.0.0.2:8090/?room={room}"  # the caller is on loopback
        assert len(q["rows"]) >= 21
        assert call(port, "GET", "/api/qr?room=BBBB")[0] == 404


def test_http_keeps_the_connection_alive(tmp_path: Path) -> None:
    with serving(tmp_path) as port:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        for _ in range(3):
            conn.request("POST", "/api/create", body="{}", headers=JSON)
            resp = conn.getresponse()
            assert resp.status == 200
            assert resp.getheader("Connection") != "close"
            resp.read()
        conn.close()


# ---- browser: friends in a room, from the menu hook to the result ----

SHOTS = Path("test-screenshots/party2")
REACHABLE = (
    "() => __porto.PG.engine.G.sh.orders.filter(o => __porto.PG.engine.reachable(o)).map(o => o.i)"
)
BOOK = """i => { const E = __porto.PG.engine, o = E.G.sh.orders[i];
  const ok = E.startPickup(o); return [ok, E.G.mode]; }"""


@pytest.fixture(scope="module")
def game(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, int]]:
    pytest.importorskip("playwright.sync_api")
    out = tmp_path_factory.mktemp("game")
    if build_game.main(["--out", str(out / "index.html")]) != 0:
        pytest.skip("the game cannot be built here")
    with serving(out) as port:
        yield f"http://127.0.0.1:{port}", port


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as pw:
        try:
            b = pw.chromium.launch()
        except sync_api.Error:
            pytest.skip("chromium is not installed (python -m playwright install chromium)")
        yield b
        b.close()


def phone(browser: Any, url: str, width: int = 390, height: int = 844) -> Any:
    page = browser.new_context(viewport={"width": width, "height": height}).new_page()
    page.goto(url)
    page.wait_for_function("window.__porto && __porto.PG.screen === 'menu'")
    return page


def create_lobby(browser: Any, base: str) -> tuple[Any, str]:
    host = phone(browser, base + "/")
    host.evaluate("__porto.PG.bus.emit('party:open')")
    host.fill(".pty-input", "Ведучий")
    host.click("text=Створити лобі")
    host.wait_for_selector(".pty-code")
    return host, host.inner_text(".pty-code")


def join_by_link(browser: Any, base: str, code: str, name: str) -> Any:
    guest = phone(browser, f"{base}/?room={code.lower()}")
    guest.fill(".pty-input", name)
    guest.click("text=Приєднатися")
    guest.wait_for_selector(".pty-wait")
    return guest


def in_play(page: Any) -> None:
    page.wait_for_function(
        "__porto.PG.screen === 'play' && __porto.PG.engine.G && __porto.PG.engine.G.t > 0",
        timeout=15000,
    )


def test_room_from_the_menu_to_a_contested_claim(browser: Any, game: tuple[str, int]) -> None:
    base, port = game
    SHOTS.mkdir(parents=True, exist_ok=True)
    host, code = create_lobby(browser, base)
    assert len(code) == party.CODE_LEN
    assert host.url.endswith(f"?room={code}")  # the link is in the address bar
    host.screenshot(path=str(SHOTS / "lobby-host-390.png"))
    anna = join_by_link(browser, base, code, "Анна")
    # the second guest uses the shortcut and types the code in lower case
    ivan = phone(browser, base + "/?party=1")
    ivan.fill(".pty-input >> nth=0", "Іван")
    ivan.fill(".pty-codein", code.lower())
    ivan.click("text=Приєднатися")
    ivan.wait_for_selector(".pty-wait")
    anna.screenshot(path=str(SHOTS / "lobby-guest-390.png"))
    host.wait_for_function("document.querySelectorAll('.pty-list .pty-row').length === 3")
    assert "ведучий" in host.inner_text(".pty-list")
    assert "(ти)" in anna.inner_text(".pty-list")
    screen = phone(browser, f"{base}/?room={code}&screen=1", 1366, 768)
    screen.wait_for_selector("canvas.pty-qr")
    screen.wait_for_function("document.querySelectorAll('.pty-list .pty-row').length === 3")
    screen.screenshot(path=str(SHOTS / "screen-lobby-1366.png"))

    refused = call(port, "POST", "/api/start", {"room": code, "token": "no", "shift": 0})
    assert refused[0] == 403
    host.click("text=Старт")
    for page in (host, anna, ivan):
        in_play(page)
    host.wait_for_selector(".pty-mini")
    # two phones book the same order; the second one is told he lost and is rolled back
    page_ids = []
    for _ in range(40):
        page_ids = [set(p.evaluate(REACHABLE)) for p in (host, anna)]
        if page_ids[0] & page_ids[1]:
            break
        host.wait_for_timeout(250)
    common = min(page_ids[0] & page_ids[1])
    assert host.evaluate(BOOK, common) == [True, "pickup"]
    for _ in range(40):
        if call(port, "GET", f"/api/party?room={code}")[1]["claims"].get(str(common)):
            break
        host.wait_for_timeout(50)
    assert anna.evaluate(BOOK, common) == [True, "pickup"]  # instant, before the server answered
    anna.wait_for_function("__porto.PG.engine.G.mode === 'idle'", timeout=3000)
    assert "Вже забрав Ведучий" in anna.inner_text("body")
    assert host.evaluate("__porto.PG.engine.G.mode") == "pickup"
    host.wait_for_timeout(1500)
    host.screenshot(path=str(SHOTS / "play-host-390.png"))
    anna.screenshot(path=str(SHOTS / "play-anna-390.png"))
    screen.wait_for_selector(".pty-board .pty-row")
    screen.screenshot(path=str(SHOTS / "screen-play-1366.png"))
    assert screen.locator(".pty-board .pty-row").count() == 3


def test_a_short_shift_ends_with_the_player_race(browser: Any, game: tuple[str, int]) -> None:
    base, port = game
    host, code = create_lobby(browser, base)
    anna = join_by_link(browser, base, code, "Анна")
    token = host.evaluate("JSON.parse(sessionStorage.getItem('party-session')).token")
    st = call(
        port,
        "POST",
        "/api/start",
        {
            "room": code,
            "token": token,
            "shift": 1,
            "difficulty": "easy",
            "duration": 10,
            "countdown": 3,
        },
    )
    assert st[1]["phase"] == "running"
    host.wait_for_selector(".pty-count")  # the 3-2-1
    in_play(host)
    for page in (host, anna):
        page.wait_for_selector("#party-race", timeout=30000)
        assert "Перегони гравців" in page.inner_text("#party-race")
        assert "Анна" in page.inner_text("#party-race")
    assert host.locator("#party-race >> text=Ще раз").count() == 1
    assert anna.locator("#party-race >> text=Ще раз").count() == 0
    host.screenshot(path=str(SHOTS / "result-host-390.png"))
    host.click("#party-race >> text=Ще раз")
    anna.wait_for_selector(".pty-code", timeout=8000)  # the reset sends everybody back to the lobby


def test_http_body_limits(tmp_path: Path) -> None:
    with serving(tmp_path) as port:

        def post(body: bytes, headers: dict[str, str]) -> tuple[int, dict]:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("POST", "/api/create", body=body, headers=headers)
            resp = conn.getresponse()
            data = json.loads(resp.read())
            conn.close()
            return resp.status, data

        assert post(b"{}", {"Content-Type": "text/plain"}) == (415, {"error": "bad_type"})
        assert post(b"{}", {}) == (415, {"error": "bad_type"})
        assert post(b"x" * (party.MAX_BODY + 1), JSON) == (413, {"error": "bad_body"})
        assert post(b"{nope", JSON) == (400, {"error": "bad_body"})
        assert post(b"[1]", JSON) == (400, {"error": "bad_body"})
        assert post(b"{}", JSON)[0] == 200


def test_claim_rejects_bad_indices_without_clamping() -> None:
    p, _, (a, _b) = running()
    for bad in (-5, 3.7, 1e9, party.DEFAULT_SIZES[3], True, "1", None):
        with pytest.raises(party.PartyError) as err:
            p.claim(a.key, bad)
        assert err.value.code == "bad_value"
        with pytest.raises(party.PartyError):
            p.release(a.key, bad)
    assert p.state()["claims"] == {}
    assert p.claim(a.key, party.DEFAULT_SIZES[3] - 1) == (True, None)


def test_the_real_order_count_is_the_bound() -> None:
    clock = Clock()
    p = party.Party(clock, sizes=(10, 20))
    a, _ = p.join("A")
    p.start(p.token, 0, "easy", 100, 0)
    with pytest.raises(party.PartyError):
        p.claim(a.key, 10)
    assert p.claim(a.key, 9)[0]


def test_a_player_holds_only_a_few_bookings() -> None:
    p, _, (a, b) = running()
    for i in range(party.MAX_ACTIVE):
        assert p.claim(a.key, i)[0]
    with pytest.raises(party.PartyError) as err:
        p.claim(a.key, 50)
    assert (err.value.code, err.value.status) == ("too_many", 409)
    assert p.claim(a.key, 0)[0]  # repeating a held order is fine
    assert p.release(a.key, 0)
    assert p.claim(a.key, 50)[0]
    assert p.claim(b.key, 0)[0]  # the others are not affected
    p.sync(a.key, {"trips": 2})  # two were picked up: they are no longer bookings
    assert p.claim(a.key, 51)[0]
    assert p.claim(a.key, 52)[0]


def test_claims_only_while_the_shift_is_on() -> None:
    p, clock = make()
    a, _ = p.join("A")
    p.start(p.token, 0, "easy", 100, 5)
    with pytest.raises(party.PartyError):
        p.claim(a.key, 1)  # countdown
    clock.t += 5
    assert p.claim(a.key, 1)[0]
    clock.t += 100
    with pytest.raises(party.PartyError):
        p.claim(a.key, 2)  # the closing grace


def test_sync_after_the_end_keeps_the_final_money() -> None:
    p, clock, (a, _b) = running()
    p.sync(a.key, {"money": 40, "trips": 3})
    clock.t += 180 + party.GRACE_S + 1
    st = p.sync(a.key, {"money": 9999, "trips": 99, "x": 1, "y": 2})
    assert st["phase"] == "done"
    assert (st["players"][0]["money"], st["players"][0]["trips"]) == (40, 3)
    assert st["players"][0]["x"] is None


def test_start_rejects_a_shift_that_does_not_exist() -> None:
    p = party.Party(Clock(), sizes=(5, 5))
    p.join("A")
    for bad in (2, -1, 1.5, "0"):
        with pytest.raises(party.PartyError):
            p.start(p.token, bad, "easy")
    assert p.start(p.token, 1, "easy")["shift"] == 1


def test_load_sizes(tmp_path: Path) -> None:
    f = tmp_path / "game_data.json"
    f.write_text(json.dumps({"shifts": [{"orders": [1, 2]}, {"orders": [1]}]}), encoding="utf-8")
    assert party.load_sizes(f) == (2, 1)
    assert party.load_sizes(tmp_path / "none.json") == party.DEFAULT_SIZES
    f.write_text("{}", encoding="utf-8")
    assert party.load_sizes(f) == party.DEFAULT_SIZES


# ---- public URL, compact replies, 30 players ----


def test_join_link_prefers_the_public_url_and_forwarded_scheme() -> None:
    pub = "https://abc-def.trycloudflare.com"
    assert party.join_link("127.0.0.1:8090", "BCDF", "http://10.0.0.2:8090/", pub) == (
        pub + "/?room=BCDF"
    )
    assert party.join_link("x.example", "BCDF", "", pub + "/") == pub + "/?room=BCDF"
    seen = party.join_link("abc.trycloudflare.com", "BCDF", proto="https")
    assert seen == "https://abc.trycloudflare.com/?room=BCDF"
    assert party.join_link("a:1", "BCDF", proto="gopher") == "http://a:1/?room=BCDF"


def test_state_is_compact_and_does_not_grow() -> None:
    p, clock = make()
    players = [p.join(f"P{i}")[0] for i in range(30)]
    p.start(p.token, 0, "normal", 180, 0)
    first = len(json.dumps(p.state(), separators=(",", ":")))
    for i, pl in enumerate(players):
        p.sync(pl.key, {"x": 1.23456 + i, "y": 2.0, "hx": 0.123456, "hy": 0.5, "money": 1.239})
        clock.t += 0.2
    state = p.state()
    assert state["players"][0]["hx"] == 0.12
    assert state["players"][0]["money"] == 1.24
    assert len(str(state["players"][0]["at"]).split(".")[-1]) <= 3
    for _ in range(300):  # many syncs add nothing: no history
        p.sync(players[0].key, {"x": 5.0, "y": 5.0, "money": 2})
        clock.t += 0.2
    assert len(json.dumps(p.state(), separators=(",", ":"))) <= first * 1.5
    assert "key" not in json.dumps(state)


def test_thirty_players_fit_one_room_and_the_cap_is_forty() -> None:
    assert party.MAX_PLAYERS == 40
    p, _ = make()
    for i in range(30):
        p.join(f"n{i}")
    assert len(p.state()["players"]) == 30


def test_http_public_url_in_qr_and_forwarded_proto(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("x", encoding="utf-8")
    pub = "https://abc-def.trycloudflare.com"
    server = party.make_party_server(tmp_path, 0, party.Rooms(), host="127.0.0.1", public_url=pub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        _, host = call(port, "POST", "/api/create", {"name": "A"})
        _, qr = call(port, "GET", f"/api/qr?room={host['room']}")
        assert qr["url"] == f"{pub}/?room={host['room']}"
        assert "\n" not in json.dumps(host)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    with serving(tmp_path) as port:
        _, host = call(port, "POST", "/api/create", {"name": "A"})
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(
            "GET",
            f"/api/qr?room={host['room']}",
            headers={"Host": "q.trycloudflare.com", "X-Forwarded-Proto": "https"},
        )
        qr = json.loads(conn.getresponse().read())
        conn.close()
        assert qr["url"] == f"https://q.trycloudflare.com/?room={host['room']}"


def test_keep_alive_serves_many_requests_on_one_connection(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("x", encoding="utf-8")
    with serving(tmp_path) as port:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("POST", "/api/create", json.dumps({"name": "A"}), JSON)
        room = json.loads(conn.getresponse().read())["room"]
        for _ in range(20):
            conn.request("GET", f"/api/party?room={room}")
            resp = conn.getresponse()
            assert resp.status == 200
            resp.read()
        conn.close()
