import http.client
import json
import sys
import threading
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
    p.start(3, "hard", 180, 5)
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
    s = p.start(2, "easy", 100, 4)
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
        p.start(0, "impossible")
    with pytest.raises(party.PartyError):
        p.start("zero", "easy")
    p.start(0, "easy", 1e9, -5)
    st = p.state()
    assert st["duration"] == party.DURATION_RANGE[1]
    assert st["start_at"] == st["now"]
    with pytest.raises(party.PartyError) as err:
        p.start(0, "easy")
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
    p.start(0, "easy", 100, 0)
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
    st = p.reset()
    assert st["phase"] == "lobby"
    assert [x["name"] for x in st["players"]] == ["P0"]
    assert st["players"][0]["money"] == 0
    assert st["claims"] == {}
    with pytest.raises(party.PartyError):
        p.sync(b.key, {})


# ---- one real HTTP round on a free port ----


def call(port: int, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    data = json.dumps(body) if body is not None else None
    conn.request(method, path, body=data, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    return resp.status, json.loads(raw) if raw[:1] == b"{" else {"raw": raw.decode()}


def test_http_round(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<title>game</title>", encoding="utf-8")
    server = party.make_party_server(tmp_path, 0, party.Party(), host="127.0.0.1")
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, page = call(port, "GET", "/?party=1")
        assert status == 200
        assert "<title>game</title>" in page["raw"]
        status, a = call(port, "POST", "/api/join", {"name": "Анна"})
        _, b = call(port, "POST", "/api/join", {"name": ""})
        assert status == 200
        assert b["state"]["players"][1]["name"] == "Таксист 2"
        assert call(port, "POST", "/api/claim", {"key": a["key"], "order": 1})[0] == 409
        status, st = call(port, "POST", "/api/start", {"shift": 1, "difficulty": "normal"})
        assert (status, st["phase"]) == (200, "running")
        ok = call(port, "POST", "/api/claim", {"key": a["key"], "order": 5})[1]
        lost = call(port, "POST", "/api/claim", {"key": b["key"], "order": 5})[1]
        assert ok == {"ok": True, "by": None}
        assert lost == {"ok": False, "by": "Анна"}
        status, st = call(port, "POST", "/api/sync", {"key": b["key"], "x": 5, "y": 6, "money": 9})
        assert st["players"][1]["money"] == 9
        assert st["claims"] == {"5": a["id"]}
        assert call(port, "GET", "/api/party")[1]["claims"] == {"5": a["id"]}
        assert call(port, "POST", "/api/sync", {"key": "bad"})[0] == 403
        assert call(port, "POST", "/api/nothing", {})[0] == 404
        assert call(port, "GET", "/api/nothing")[0] == 404
        assert call(port, "POST", "/api/reset", {})[1]["phase"] == "lobby"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_qr_payload_rows_are_square() -> None:
    q = party.qr_payload("http://192.168.1.5:8090/?party=1")
    assert q["url"].endswith("?party=1")
    assert len(q["rows"]) == len(q["rows"][0]) >= 21
    assert set("".join(q["rows"])) == {"0", "1"}
    assert party.qr_payload("")["rows"] == []
    assert party.qr_payload("x" * 500)["rows"] == []


def test_http_serves_the_qr(tmp_path: Path) -> None:
    server = party.make_party_server(
        tmp_path, 0, party.Party(), host="127.0.0.1", join_url="http://10.0.0.2:8090/?party=1"
    )
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, q = call(port, "GET", "/api/qr")
        assert status == 200
        assert q["url"] == "http://10.0.0.2:8090/?party=1"
        assert len(q["rows"]) >= 21
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_host_actions_are_refused_from_other_addresses(tmp_path: Path) -> None:
    server = party.make_party_server(
        tmp_path, 0, party.Party(), host_ips=frozenset({"10.9.9.9"}), host="127.0.0.1"
    )
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, err = call(port, "POST", "/api/start", {"shift": 0, "difficulty": "easy"})
        assert (status, err) == (403, {"error": "host_only"})
        assert call(port, "POST", "/api/join", {"name": "A"})[0] == 200
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
