import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import party_load  # noqa: E402


def test_percentile_nearest_rank() -> None:
    data = list(range(1, 101))
    assert party_load.percentile(data, 50) == 50
    assert party_load.percentile(data, 95) == 95
    assert party_load.percentile(data, 100) == 100
    assert party_load.percentile([3.0], 95) == 3.0
    assert party_load.percentile([], 95) == 0.0
    assert party_load.percentile([5, 1, 3], 0) == 1


def test_summarize_counts_errors_and_rate() -> None:
    s = party_load.Stats()
    for i in range(1, 101):
        s.add(i / 1000, 200)
    s.fail("boom")
    out = party_load.summarize(s, 10.0)
    assert out["errors"] == 1
    assert out["requests"] == 101
    assert out["p50_ms"] == 50.0
    assert out["p95_ms"] == 95.0
    assert out["max_ms"] == 100.0
    assert out["avg_reply_bytes"] == 200
    assert out["rps"] == 10.1
    assert s.first_error == "boom"
    assert party_load.summarize(party_load.Stats(), 0)["rps"] == 0.0


def test_split_url() -> None:
    assert party_load.split_url("http://127.0.0.1:8123") == (False, "127.0.0.1", 8123)
    assert party_load.split_url("https://a-b.trycloudflare.com/") == (
        True,
        "a-b.trycloudflare.com",
        443,
    )
    with pytest.raises(ValueError):
        party_load.split_url("ftp://x")
    with pytest.raises(ValueError):
        party_load.split_url("nonsense")


def test_position_is_deterministic_and_players_differ() -> None:
    assert party_load.position(3, 1.5) == party_load.position(3, 1.5)
    assert party_load.position(1, 0)["x"] != party_load.position(2, 0)["x"]
    p = party_load.position(0, 10)
    assert abs(p["hx"]) <= 1 and abs(p["hy"]) <= 1


def test_next_action_releases_only_what_is_held() -> None:
    rng = random.Random(1)
    assert party_load.next_action(rng, [], 500)[0] == "claim"
    kinds = {party_load.next_action(random.Random(i), [7, 8], 500)[0] for i in range(50)}
    assert kinds == {"claim", "release"}
    held = [4]
    seen = [party_load.next_action(random.Random(i), held, 500) for i in range(30)]
    assert all(0 <= o < 500 for _, o in seen)


def test_run_against_a_real_server_has_no_errors(tmp_path: Path) -> None:
    import threading

    import party

    (tmp_path / "index.html").write_text("x", encoding="utf-8")
    server = party.make_party_server(tmp_path, 0, party.Rooms(), host="127.0.0.1")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        out = party_load.run(url, players=5, seconds=2.0)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert out["errors"] == 0, out["first_error"]
    assert out["requests"] > 20
    assert out["players"] == 5
