import contextlib
import http.client
import json
import random
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

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
    assert party.clean_code("abcdefg") == "BCDE"
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
        go = {"room": room, "token": host["token"], "shift": 1, "difficulty": "normal"}
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
            conn.request("POST", "/api/create", body="{}")
            resp = conn.getresponse()
            assert resp.status == 200
            assert resp.getheader("Connection") != "close"
            resp.read()
        conn.close()
