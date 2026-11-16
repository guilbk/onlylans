"""Load test for party mode: N virtual phones in one lobby, polling and claiming orders.

``python tools/party_load.py --url http://127.0.0.1:8090 [--players 30] [--seconds 180]
[--interval 0.2] [--json out.json]``. Player 0 creates the lobby, the others join by code, the host
starts the shift, then every player syncs each ``--interval`` seconds and sometimes claims an order
(the API calls of ``game/src/js/80_party.js``). Works with http and https URLs. Exit code 0 if
p95 < 300 ms, no errors and small replies; else 1 with a one-line reason. Standard library only.
"""

from __future__ import annotations

import argparse
import http.client
import json
import random
import statistics
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

EXIT_OK = 0
EXIT_FAIL = 1
MAX_P95_MS = 300.0
MAX_AVG_BYTES = 50_000  # one sync reply; 30 phones x 5 per second multiply it
TIMEOUT_S = 5.0
COUNTDOWN_S = 1.0
CLAIM_CHANCE = 0.05  # per sync tick
HOT_ORDERS = 40  # claims aim at the first orders so players really collide
MAP_SIZE_M = 10_000.0
STEP_M = 15.0  # metres a car moves per tick


@dataclass
class Sample:
    """One finished request."""

    kind: str
    ms: float
    ok: bool
    size: int = 0


@dataclass
class Tally:
    """Thread-safe collector of samples and claim outcomes."""

    samples: list[Sample] = field(default_factory=list)
    claims_ok: int = 0
    claims_lost: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, sample: Sample) -> None:
        """Record one request."""
        with self.lock:
            self.samples.append(sample)

    def claim(self, won: bool) -> None:
        """Record one claim answer."""
        with self.lock:
            if won:
                self.claims_ok += 1
            else:
                self.claims_lost += 1


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile.

    Args:
        values: Samples (any order, may be empty).
        pct: Percent, 0..100.

    Returns:
        The value at that rank; 0.0 for an empty list.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = -(-len(ordered) * pct // 100)  # ceil
    return ordered[min(max(int(rank), 1), len(ordered)) - 1]


def summarize(samples: list[Sample], claims_ok: int, claims_lost: int) -> dict[str, float]:
    """Reduce samples to the numbers of the report.

    Args:
        samples: All requests.
        claims_ok: Claims the server accepted.
        claims_lost: Claims another player won first.

    Returns:
        Requests, p50/p95/p99/max latency in ms, error share (0..1), claims and average reply bytes.
    """
    ms = [s.ms for s in samples]
    n = len(samples)
    return {
        "requests": n,
        "p50": percentile(ms, 50),
        "p95": percentile(ms, 95),
        "p99": percentile(ms, 99),
        "max": max(ms, default=0.0),
        "error_share": sum(1 for s in samples if not s.ok) / n if n else 1.0,
        "claims_ok": claims_ok,
        "claims_lost": claims_lost,
        "avg_bytes": statistics.fmean(s.size for s in samples) if n else 0.0,
    }


def verdict(summary: dict[str, float]) -> tuple[int, str]:
    """Pass or fail.

    Args:
        summary: Output of :func:`summarize`.

    Returns:
        ``(exit code, one-line reason)``; the reason is empty on success.
    """
    if summary["requests"] == 0 or summary["error_share"] > 0:
        return EXIT_FAIL, f"errors: {summary['error_share'] * 100:.2f}% of requests failed"
    if summary["p95"] >= MAX_P95_MS:
        return EXIT_FAIL, f"latency: p95 {summary['p95']:.0f} ms >= {MAX_P95_MS:.0f} ms"
    if summary["avg_bytes"] > MAX_AVG_BYTES:
        return EXIT_FAIL, f"response size: avg {summary['avg_bytes']:.0f} B > {MAX_AVG_BYTES} B"
    return EXIT_OK, ""


def format_summary(summary: dict[str, float]) -> str:
    """Render the short table.

    Args:
        summary: Output of :func:`summarize`.

    Returns:
        A multi-line string.
    """
    rows = [
        ("requests", f"{summary['requests']:.0f}"),
        ("p50 ms", f"{summary['p50']:.1f}"),
        ("p95 ms", f"{summary['p95']:.1f}"),
        ("p99 ms", f"{summary['p99']:.1f}"),
        ("max ms", f"{summary['max']:.1f}"),
        ("error share", f"{summary['error_share'] * 100:.2f}%"),
        ("claims ok/lost", f"{summary['claims_ok']:.0f}/{summary['claims_lost']:.0f}"),
        ("avg reply bytes", f"{summary['avg_bytes']:.0f}"),
    ]
    return "\n".join(f"{k:<16}{v:>10}" for k, v in rows)


def plan_claim(rng: random.Random) -> int | None:
    """Decide whether this tick claims an order, and which.

    Args:
        rng: Random source (seeded in tests).

    Returns:
        An order index among the hot ones, or ``None`` for no claim.
    """
    return rng.randrange(HOT_ORDERS) if rng.random() < CLAIM_CHANCE else None


def step_position(rng: random.Random, x: float, y: float) -> tuple[float, float]:
    """Move a virtual car one tick, kept inside the map.

    Args:
        rng: Random source.
        x: Current x in metres.
        y: Current y in metres.

    Returns:
        The new ``(x, y)`` in metres.
    """
    nx = min(max(x + rng.uniform(-STEP_M, STEP_M), 0.0), MAP_SIZE_M)
    ny = min(max(y + rng.uniform(-STEP_M, STEP_M), 0.0), MAP_SIZE_M)
    return nx, ny


class Client:
    """One keep-alive connection that times every request into a tally."""

    def __init__(self, base_url: str, tally: Tally) -> None:
        """Remember the target; the connection opens on the first request."""
        parts = urlsplit(base_url)
        self.https = parts.scheme == "https"
        self.netloc = parts.netloc
        self.tally = tally
        self.conn: http.client.HTTPConnection | None = None

    def _connect(self) -> http.client.HTTPConnection:
        """Open a connection (http or https) with the request timeout."""
        cls = http.client.HTTPSConnection if self.https else http.client.HTTPConnection
        return cls(self.netloc, timeout=TIMEOUT_S)

    def call(
        self, kind: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Send one request, record its latency, and return the JSON object (or ``None``).

        Args:
            kind: Label of the sample.
            path: URL path with query.
            body: JSON body for a POST; ``None`` makes a GET.

        Returns:
            The decoded reply, or ``None`` if the request failed in any way.
        """
        t0 = time.perf_counter()
        size, ok, data = 0, False, None
        try:
            if self.conn is None:
                self.conn = self._connect()
            headers = {"Content-Type": "application/json"} if body is not None else {}
            payload = json.dumps(body) if body is not None else None
            self.conn.request("POST" if body is not None else "GET", path, payload, headers)
            resp = self.conn.getresponse()
            raw = resp.read()
            size = len(raw)
            data = json.loads(raw)
            ok = 200 <= resp.status < 300 and isinstance(data, dict)
        except (OSError, http.client.HTTPException, ValueError):
            if self.conn is not None:
                self.conn.close()
            self.conn = None  # reconnect next time
        self.tally.add(Sample(kind, (time.perf_counter() - t0) * 1000.0, ok, size))
        return data if ok else None


def play(client: Client, room: str, key: str, stop_at: float, interval: float, seed: int) -> None:
    """One phone's shift: sync every ``interval`` s, now and then claim and release an order."""
    rng = random.Random(seed)
    x = y = MAP_SIZE_M / 2
    who = {"room": room, "key": key}
    while time.monotonic() < stop_at:
        t0 = time.monotonic()
        x, y = step_position(rng, x, y)
        client.call("sync", "/api/sync", {**who, "x": round(x), "y": round(y)})
        order = plan_claim(rng)
        if order is not None:
            r = client.call("claim", "/api/claim", {**who, "order": order})
            if r is not None:
                client.tally.claim(bool(r.get("ok")))
                if r.get("ok"):  # drive off: keeps the player under the bookings limit
                    client.call("release", "/api/release", {**who, "order": order})
        time.sleep(max(0.0, interval - (time.monotonic() - t0)))


def run(url: str, players: int, seconds: float, interval: float) -> Tally:
    """Create the lobby, join everybody, start the shift and play it.

    Args:
        url: Base URL of the party server.
        players: Number of virtual phones (>= 1).
        seconds: Length of the shift in real seconds.
        interval: Seconds between two syncs of one phone.

    Returns:
        The tally of all requests (setup requests included).
    """
    tally = Tally()
    host = Client(url, tally)
    made = host.call("create", "/api/create", {"name": "load0"})
    if made is None:
        return tally
    room, token, keys = made["room"], made["token"], [made["key"]]
    for i in range(1, players):
        joined = Client(url, tally).call("join", "/api/join", {"room": room, "name": f"load{i}"})
        if joined is not None:
            keys.append(joined["key"])
    start = {
        "room": room,
        "token": token,
        "shift": 0,
        "difficulty": "normal",
        "duration": seconds + 5.0,
        "countdown": COUNTDOWN_S,
    }
    host.call("start", "/api/start", start)
    time.sleep(COUNTDOWN_S + 0.2)
    stop_at = time.monotonic() + seconds
    threads = [
        threading.Thread(target=play, args=(Client(url, tally), room, k, stop_at, interval, i))
        for i, k in enumerate(keys)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return tally


def main(argv: list[str] | None = None) -> int:
    """Command line entry point.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        0 if the run passes the thresholds, 1 otherwise.
    """
    ap = argparse.ArgumentParser(description="Load test for party mode")
    ap.add_argument("--url", required=True, help="server URL, http or https")
    ap.add_argument("--players", type=int, default=30)
    ap.add_argument("--seconds", type=float, default=180.0)
    ap.add_argument("--interval", type=float, default=0.2, help="seconds between syncs")
    ap.add_argument("--json", type=Path, default=None, help="also write the summary to this file")
    args = ap.parse_args(argv)
    tally = run(args.url, max(1, args.players), args.seconds, args.interval)
    summary = summarize(tally.samples, tally.claims_ok, tally.claims_lost)
    print(format_summary(summary))
    code, reason = verdict(summary)
    if args.json:
        out = {**summary, "pass": code == EXIT_OK, "reason": reason}
        args.json.write_text(json.dumps(out, sort_keys=True, indent=2), encoding="utf-8")
    print("PASS" if code == EXIT_OK else f"FAIL: {reason}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
