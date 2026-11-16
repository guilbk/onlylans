"""Load test for party mode: N virtual players in one room, like a battle of cars.

``python tools/party_load.py --url http://127.0.0.1:8123 [--players 30] [--seconds 180]`` works
against a local server or a public tunnel URL. Every virtual phone keeps one connection, polls
``/api/sync`` every 200 ms with its position, and books (and sometimes gives back) orders.
Prints p50/p95/max latency, errors, reply bytes and requests per second. Standard library only.
"""

from __future__ import annotations

import argparse
import http.client
import json
import math
import random
import sys
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from urllib.parse import urlsplit

EXIT_OK = 0
EXIT_FAIL = 1
POLL_S = 0.2
CLAIM_EVERY_S = 3.0  # one booking attempt per phone this often
RELEASE_SHARE = 0.2  # share of bookings that are given back
TIMEOUT_S = 10.0
JSON = {"Content-Type": "application/json"}


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile.

    Args:
        values: Samples (any order).
        q: Percentile in ``[0, 100]``.

    Returns:
        The sample at rank ``ceil(q/100 * n)``, or 0.0 if there are no samples.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


@dataclass
class Stats:
    """Samples collected by all virtual players (guarded by a lock)."""

    latencies: list[float] = field(default_factory=list)  # seconds
    errors: int = 0
    nbytes: int = 0
    first_error: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, latency: float, size: int) -> None:
        """Record one good reply."""
        with self.lock:
            self.latencies.append(latency)
            self.nbytes += size

    def fail(self, why: str) -> None:
        """Record one failed request."""
        with self.lock:
            self.errors += 1
            self.first_error = self.first_error or why


def summarize(stats: Stats, elapsed: float) -> dict[str, float | int]:
    """Turn the samples into the numbers of the report.

    Args:
        stats: The collected samples.
        elapsed: Real seconds the test ran.

    Returns:
        ``requests``, ``errors``, ``p50_ms``, ``p95_ms``, ``max_ms``, ``bytes``,
        ``avg_reply_bytes`` and ``rps``.
    """
    n = len(stats.latencies)
    ms = [v * 1000 for v in stats.latencies]
    return {
        "requests": n + stats.errors,
        "errors": stats.errors,
        "p50_ms": round(percentile(ms, 50), 1),
        "p95_ms": round(percentile(ms, 95), 1),
        "max_ms": round(max(ms, default=0.0), 1),
        "bytes": stats.nbytes,
        "avg_reply_bytes": round(stats.nbytes / n) if n else 0,
        "rps": round((n + stats.errors) / elapsed, 1) if elapsed > 0 else 0.0,
    }


def split_url(url: str) -> tuple[bool, str, int]:
    """Split a base URL.

    Args:
        url: ``http://host:port`` or ``https://host``.

    Returns:
        ``(is_https, host, port)``.

    Raises:
        ValueError: If the scheme is not http or https or there is no host.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"not an http(s) URL: {url!r}")
    return (
        parts.scheme == "https",
        parts.hostname,
        parts.port or (443 if parts.scheme == "https" else 80),
    )


def position(index: int, t: float) -> dict[str, float]:
    """A deterministic drive: each player circles a different point of the map.

    Args:
        index: Player number.
        t: Seconds since the start.

    Returns:
        ``x``, ``y``, ``hx``, ``hy`` (metres and a unit heading) and ``money``.
    """
    a = t * 0.3 + index
    return {
        "x": round(3000 * math.cos(index) + 800 * math.cos(a), 1),
        "y": round(3000 * math.sin(index) + 800 * math.sin(a), 1),
        "hx": round(-math.sin(a), 2),
        "hy": round(math.cos(a), 2),
        "money": round(t * 0.4, 2),
    }


def next_action(rng: random.Random, held: list[int], size: int) -> tuple[str, int]:
    """Choose a booking action: release one of the held orders, or claim a random order.

    Args:
        rng: Random source.
        held: Orders this player booked successfully.
        size: Orders in the shift.

    Returns:
        ``("release", order)`` or ``("claim", order)``.
    """
    if held and rng.random() < RELEASE_SHARE:
        return "release", held.pop(rng.randrange(len(held)))
    return "claim", rng.randrange(size)


class Client:
    """One keep-alive connection to the server."""

    def __init__(self, https: bool, host: str, port: int, stats: Stats) -> None:
        """Remember where to connect."""
        self._make = lambda: (http.client.HTTPSConnection if https else http.client.HTTPConnection)(
            host, port, timeout=TIMEOUT_S
        )
        self._conn = self._make()
        self._stats = stats

    def call(self, method: str, path: str, body: dict | None = None) -> dict | None:
        """Send one request; record its latency (or the error); reconnect after a failure.

        Returns:
            The JSON reply, or ``None`` on a network error or a non-200 status.
        """
        data = json.dumps(body, separators=(",", ":")) if body is not None else None
        t0 = time.perf_counter()
        try:
            self._conn.request(method, path, body=data, headers=JSON if data else {})
            resp = self._conn.getresponse()
            raw = resp.read()
            dt = time.perf_counter() - t0
            if resp.status != 200:
                # A refused claim ("phase", "too_many") is a normal answer, not a fault.
                if resp.status == 409 and path == "/api/claim":
                    self._stats.add(dt, len(raw))
                    return None
                self._stats.fail(f"{method} {path} -> {resp.status}")
                return None
            self._stats.add(dt, len(raw))
            return json.loads(raw)
        except (OSError, http.client.HTTPException, ValueError) as err:
            self._stats.fail(f"{method} {path}: {type(err).__name__}")
            self._conn.close()
            self._conn = self._make()
            return None

    def close(self) -> None:
        """Close the connection."""
        self._conn.close()


def player_loop(
    index: int,
    target: tuple[bool, str, int],
    room: str,
    key: str,
    size: int,
    stop_at: float,
    stats: Stats,
    seed: int,
) -> None:
    """Run one virtual phone until ``stop_at`` (``time.monotonic``)."""
    client = Client(*target, stats)
    rng = random.Random(seed + index)
    held: list[int] = []
    begin = time.monotonic()
    next_claim = begin + CLAIM_EVERY_S * rng.random()
    next_poll = begin + POLL_S * rng.random()
    while (now := time.monotonic()) < stop_at:
        if now < next_poll:
            time.sleep(min(next_poll - now, 0.05))
            continue
        next_poll += POLL_S
        client.call("POST", "/api/sync", {"room": room, "key": key, **position(index, now - begin)})
        if now >= next_claim:
            next_claim = now + CLAIM_EVERY_S
            kind, order = next_action(rng, held, size)
            reply = client.call("POST", f"/api/{kind}", {"room": room, "key": key, "order": order})
            if kind == "claim" and reply and reply.get("ok"):
                held.append(order)
                held[:] = held[-3:]
    client.close()


def run(
    url: str, players: int, seconds: float, shift: int = 0, seed: int = 1
) -> dict[str, float | int]:
    """Create a room, join the players, start a shift and hammer the server.

    Args:
        url: Base URL of the party server.
        players: Number of virtual phones (the first is the host).
        seconds: How long the shift (and the test) lasts.
        shift: Shift index to start.
        seed: Random seed.

    Returns:
        The summary of :func:`summarize`, plus ``players``.

    Raises:
        RuntimeError: If the room cannot be set up.
    """
    target = split_url(url)
    setup = Stats()
    admin = Client(*target, setup)
    made = admin.call("POST", "/api/create", {"name": "load-0"})
    if not made:
        raise RuntimeError(f"cannot create a room: {setup.first_error}")
    room, keys = made["room"], [made["key"]]
    for i in range(1, players):
        joined = admin.call("POST", "/api/join", {"room": room, "name": f"load-{i}"})
        if not joined:
            raise RuntimeError(f"cannot join player {i}: {setup.first_error}")
        keys.append(joined["key"])
    start = {"room": room, "token": made["token"], "shift": shift, "difficulty": "normal"}
    started = admin.call("POST", "/api/start", {**start, "duration": seconds, "countdown": 0})
    if not started:
        raise RuntimeError(f"cannot start: {setup.first_error}")
    size = 500
    stats = Stats()
    t0 = time.monotonic()
    stop_at = t0 + seconds
    threads = [
        threading.Thread(
            target=player_loop, args=(i, target, room, k, size, stop_at, stats, seed), daemon=True
        )
        for i, k in enumerate(keys)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    admin.close()
    out = summarize(stats, time.monotonic() - t0)
    out["players"] = players
    out["first_error"] = stats.first_error
    return out


def main(argv: list[str] | None = None) -> int:
    """Command line entry point.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        0 if there were no errors, 1 otherwise.
    """
    ap = argparse.ArgumentParser(description="Load test for the party server")
    ap.add_argument("--url", required=True, help="server base URL, local or a tunnel")
    ap.add_argument("--players", type=int, default=30)
    ap.add_argument("--seconds", type=float, default=180.0)
    ap.add_argument("--json", action="store_true", help="print the result as one JSON line")
    args = ap.parse_args(argv)
    try:
        result = run(args.url, max(1, args.players), max(10.0, args.seconds))
    except (RuntimeError, ValueError) as err:
        print(f"load test failed: {err}", file=sys.stderr)
        return EXIT_FAIL
    if args.json:
        print(json.dumps(result))
    else:
        for name, value in result.items():
            print(f"{name:>16}: {value}")
    return EXIT_OK if result["errors"] == 0 else EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
