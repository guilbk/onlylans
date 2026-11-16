import json
import random
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import party  # noqa: E402
import party_load as pl  # noqa: E402


def sample(ms: float, ok: bool = True, size: int = 100) -> pl.Sample:
    return pl.Sample("sync", ms, ok, size)


def test_percentile_known_lists() -> None:
    xs = [float(i) for i in range(1, 101)]
    assert pl.percentile(xs, 50) == 50
    assert pl.percentile(xs, 95) == 95
    assert pl.percentile(xs, 99) == 99
    assert pl.percentile(xs, 100) == 100
    assert pl.percentile([7.0], 99) == 7
    assert pl.percentile([], 50) == 0
    assert pl.percentile([3.0, 1.0, 2.0], 50) == 2


def test_summarize() -> None:
    s = pl.summarize([sample(10), sample(20), sample(30, ok=False, size=300)], 2, 1)
    assert s["requests"] == 3 and s["max"] == 30
    assert s["error_share"] == pytest.approx(1 / 3)
    assert s["avg_bytes"] == pytest.approx(500 / 3)
    assert (s["claims_ok"], s["claims_lost"]) == (2, 1)
    assert pl.summarize([], 0, 0)["error_share"] == 1.0


@pytest.mark.parametrize(
    ("p95", "err", "size", "code", "word"),
    [
        (299.9, 0.0, 1000, 0, ""),
        (300.0, 0.0, 1000, 1, "latency"),
        (10.0, 0.001, 1000, 1, "errors"),
        (10.0, 0.0, pl.MAX_AVG_BYTES, 0, ""),
        (10.0, 0.0, pl.MAX_AVG_BYTES + 1, 1, "response size"),
    ],
)
def test_verdict_boundaries(p95: float, err: float, size: int, code: int, word: str) -> None:
    s = {"requests": 10, "p95": p95, "error_share": err, "avg_bytes": size}
    got, reason = pl.verdict(s)
    assert got == code and word in reason


def test_verdict_no_requests_fails() -> None:
    assert pl.verdict(pl.summarize([], 0, 0))[0] == 1


def test_format_summary() -> None:
    text = pl.format_summary(pl.summarize([sample(12.34)], 4, 5))
    assert "requests" in text and "12.3" in text and "4/5" in text and "0.00%" in text


def test_plan_claim_and_step() -> None:
    rng = random.Random(1)
    hits = [p for p in (pl.plan_claim(rng) for _ in range(2000)) if p is not None]
    assert 0 < len(hits) < 400 and all(0 <= p < pl.HOT_ORDERS for p in hits)
    x, y = pl.step_position(rng, 0.0, pl.MAP_SIZE_M)
    assert 0 <= x <= pl.STEP_M and pl.MAP_SIZE_M - pl.STEP_M <= y <= pl.MAP_SIZE_M


def test_end_to_end_three_players(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    server = party.make_party_server(tmp_path, 0, party.Rooms(), host="127.0.0.1")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    out = tmp_path / "out.json"
    try:
        port = server.server_address[1]
        argv = ["--url", f"http://127.0.0.1:{port}", "--players", "3", "--seconds", "3"]
        pl.main([*argv, "--interval", "0.1", "--json", str(out)])
    finally:
        server.shutdown()
        server.server_close()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["requests"] > 3 * 20
    assert data["error_share"] == 0
