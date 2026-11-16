"""Party mode server: everyone at the presentation plays one shift on one map.

``python tools/party.py [--port 8090] [--build] [--dir game] [--open-host]`` serves
``game/index.html`` (like ``tools/serve.py``) plus a small JSON API under ``/api/``. Standard
library only.

The state lives in the pure :class:`Party` class (lobby -> running -> done, players, the set of
taken orders, the start time); the clock is injected so it is tested without a network. The server
decides every order claim: the first claim wins. Game time on the phones follows the server clock
(``now`` and ``start_at`` in every reply). Host-only actions (``/api/start``, ``/api/reset``) are
accepted from the machine the server runs on; ``--open-host`` accepts them from anywhere.
"""

from __future__ import annotations

import argparse
import json
import math
import secrets
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any

from qr import QRError, encode
from serve import (
    BIND_HOST,
    DEFAULT_DIR,
    EXIT_FAIL,
    EXIT_OK,
    LOOPBACK,
    LanServer,
    NoCacheHandler,
    banner,
    build_url,
    detect_lan_ip,
    run_build,
)

DEFAULT_PORT = 8090
MAX_PLAYERS = 60
MAX_NAME = 20
MAX_BODY = 4096
MAX_ORDER = 100_000  # order index per shift; real shifts have about 500
MAX_MONEY = 1_000_000.0
COORD_LIMIT = 1e6  # metres; the map is 15 x 19 km
DEFAULT_DURATION = 180.0  # real seconds of one shift: 7200 game seconds at 40x
DURATION_RANGE = (10.0, 1800.0)
DEFAULT_COUNTDOWN = 5.0
COUNTDOWN_RANGE = (0.0, 30.0)
GRACE_S = 2.0  # after the shift end the phones still post their final money
OFFLINE_S = 8.0  # no sync for this long: shown as offline
DIFFICULTIES = ("easy", "normal", "hard")
DEFAULT_NAME = "Таксист"
# Car colours for the other players (no mint, that is the hero, and no lilac, that is the ghost).
COLORS = (
    "#ff8a3d",
    "#f4d03f",
    "#4db8ff",
    "#ff4d6a",
    "#ff6ec7",
    "#a0e85b",
    "#ffffff",
    "#2ee6d6",
    "#ffb3a7",
    "#c4d4ff",
    "#e0a030",
    "#7fd1ae",
)
HOST_PATHS = ("/api/start", "/api/reset")


class PartyError(Exception):
    """A refused API call: a short machine code and the HTTP status to send."""

    def __init__(self, code: str, status: int = HTTPStatus.BAD_REQUEST) -> None:
        """Remember the code and the status.

        Args:
            code: Short code such as ``"phase"``; the client shows its own text.
            status: HTTP status of the reply.
        """
        super().__init__(code)
        self.code = code
        self.status = int(status)


@dataclass
class Player:
    """One phone in the game."""

    id: int
    key: str
    name: str
    color: str
    x: float | None = None  # unknown until the first sync
    y: float | None = None
    hx: float = 0.0
    hy: float = -1.0
    money: float = 0.0
    trips: int = 0
    seen: float = 0.0


def _number(value: object, lo: float, hi: float) -> float:
    """Validate a JSON number and clamp it.

    Args:
        value: Value from the request body.
        lo: Lower bound.
        hi: Upper bound.

    Returns:
        The value as a float inside ``[lo, hi]``.

    Raises:
        PartyError: If the value is not a finite number.
    """
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise PartyError("bad_value")
    return min(max(float(value), lo), hi)


def clean_name(raw: object) -> str:
    """Make a safe player name: printable, one line, at most ``MAX_NAME`` characters.

    Args:
        raw: The name as typed (any type; non-strings give an empty name).

    Returns:
        The cleaned name, possibly empty.
    """
    if not isinstance(raw, str):
        return ""
    text = "".join(ch if ch.isprintable() else " " for ch in raw)
    return " ".join(text.split())[:MAX_NAME].strip()


class Party:
    """The whole game state, without any network code. Every method takes the lock."""

    def __init__(self, now: Callable[[], float] = time.time) -> None:
        """Create an empty lobby.

        Args:
            now: Clock in seconds (injected for tests).
        """
        self._now = now
        self._lock = threading.Lock()
        self._players: dict[int, Player] = {}
        self._by_key: dict[str, Player] = {}
        self._claims: dict[int, int] = {}  # order index -> player id
        self._next_id = 1
        self._start_at: float | None = None
        self._duration = DEFAULT_DURATION
        self._shift = 0
        self._difficulty = "normal"

    # -- internals (lock held) --

    def _phase(self) -> str:
        """Current phase: ``lobby``, ``running`` (countdown included) or ``done``."""
        if self._start_at is None:
            return "lobby"
        if self._now() >= self._start_at + self._duration + GRACE_S:
            return "done"
        return "running"

    def _player(self, key: object) -> Player:
        """Find a player by secret key.

        Raises:
            PartyError: If the key is unknown.
        """
        found = self._by_key.get(key) if isinstance(key, str) else None
        if found is None:
            raise PartyError("unknown_player", HTTPStatus.FORBIDDEN)
        found.seen = self._now()
        return found

    def _unique_name(self, wanted: str) -> str:
        """Give a free name: the wanted one, ``Таксист N`` when empty, or with a number appended."""
        taken = {p.name.casefold() for p in self._players.values()}
        base = wanted or DEFAULT_NAME
        name = f"{base} {self._next_id}" if not wanted else base
        n = 2
        while name.casefold() in taken:
            name = f"{base[: MAX_NAME - 4]} {n}"
            n += 1
        return name

    def _state(self) -> dict[str, Any]:
        """The public state (the secret keys are left out)."""
        now = self._now()
        players = [
            {
                "id": p.id,
                "name": p.name,
                "color": p.color,
                "x": None if p.x is None or p.y is None else round(p.x, 1),
                "y": None if p.x is None or p.y is None else round(p.y, 1),
                "hx": round(p.hx, 3),
                "hy": round(p.hy, 3),
                "money": round(p.money, 2),
                "trips": p.trips,
                "online": now - p.seen <= OFFLINE_S,
            }
            for p in self._players.values()
        ]
        return {
            "phase": self._phase(),
            "now": now,
            "start_at": self._start_at,
            "duration": self._duration,
            "shift": self._shift,
            "difficulty": self._difficulty,
            "players": players,
            "claims": {str(o): pid for o, pid in self._claims.items()},
        }

    # -- API --

    def state(self) -> dict[str, Any]:
        """Return the public state (phase, server time, players, claims).

        Returns:
            A JSON-ready dictionary.
        """
        with self._lock:
            return self._state()

    def join(self, name: object, key: object = None) -> tuple[Player, dict[str, Any]]:
        """Add a player, or welcome back a known one (same secret key).

        Args:
            name: Wanted name; empty gives ``Таксист N``; a taken name gets a number.
            key: Secret key of an earlier join of this phone, if any.

        Returns:
            The player and the new state.

        Raises:
            PartyError: If the game is over, or the room is full.
        """
        with self._lock:
            known = self._by_key.get(key) if isinstance(key, str) else None
            if known is not None:
                known.seen = self._now()
                return known, self._state()
            if self._phase() == "done":
                raise PartyError("phase", HTTPStatus.CONFLICT)
            if len(self._players) >= MAX_PLAYERS:
                raise PartyError("full", HTTPStatus.CONFLICT)
            player = Player(
                id=self._next_id,
                key=secrets.token_hex(8),
                name=self._unique_name(clean_name(name)),
                color=COLORS[(self._next_id - 1) % len(COLORS)],
                seen=self._now(),
            )
            self._next_id += 1
            self._players[player.id] = player
            self._by_key[player.key] = player
            return player, self._state()

    def sync(self, key: object, body: dict[str, Any]) -> dict[str, Any]:
        """Store a phone's position and money and return the state.

        Args:
            key: Secret key of the player.
            body: ``x``, ``y``, ``hx``, ``hy``, ``money``, ``trips`` (all optional).

        Returns:
            The new state.

        Raises:
            PartyError: If the key is unknown or a value is not a number.
        """
        with self._lock:
            p = self._player(key)
            if "x" in body and "y" in body:
                p.x = _number(body["x"], -COORD_LIMIT, COORD_LIMIT)
                p.y = _number(body["y"], -COORD_LIMIT, COORD_LIMIT)
            if "hx" in body and "hy" in body:
                p.hx = _number(body["hx"], -1.0, 1.0)
                p.hy = _number(body["hy"], -1.0, 1.0)
            if "money" in body:
                p.money = _number(body["money"], 0.0, MAX_MONEY)
            if "trips" in body:
                p.trips = int(_number(body["trips"], 0, MAX_ORDER))
            return self._state()

    def claim(self, key: object, order: object) -> tuple[bool, str | None]:
        """Try to take an order; the first claim wins.

        Args:
            key: Secret key of the player.
            order: Order index in the shift.

        Returns:
            ``(True, None)`` if the player now owns it (or already did), else ``(False, name)``
            with the name of the player who took it first.

        Raises:
            PartyError: If the key is unknown, the order is invalid or the game is not running.
        """
        with self._lock:
            p = self._player(key)
            if self._phase() != "running":
                raise PartyError("phase", HTTPStatus.CONFLICT)
            n = int(_number(order, 0, MAX_ORDER))
            owner = self._claims.setdefault(n, p.id)
            if owner == p.id:
                return True, None
            return False, self._players[owner].name

    def release(self, key: object, order: object) -> bool:
        """Give an order back (the player drove elsewhere); only the owner can.

        Args:
            key: Secret key of the player.
            order: Order index in the shift.

        Returns:
            ``True`` if the claim was removed.

        Raises:
            PartyError: If the key is unknown or the order is invalid.
        """
        with self._lock:
            p = self._player(key)
            n = int(_number(order, 0, MAX_ORDER))
            if self._claims.get(n) != p.id:
                return False
            del self._claims[n]
            return True

    def start(
        self,
        shift: object,
        difficulty: object,
        duration: object = DEFAULT_DURATION,
        countdown: object = DEFAULT_COUNTDOWN,
    ) -> dict[str, Any]:
        """Start the shift for everybody after a short countdown (host only).

        Args:
            shift: Index of the shift in the game data.
            difficulty: ``easy``, ``normal`` or ``hard``.
            duration: Real seconds the shift lasts.
            countdown: Real seconds until the start.

        Returns:
            The new state.

        Raises:
            PartyError: If a game is already running, or a value is invalid.
        """
        with self._lock:
            if self._phase() != "lobby":
                raise PartyError("phase", HTTPStatus.CONFLICT)
            if difficulty not in DIFFICULTIES:
                raise PartyError("bad_value")
            self._shift = int(_number(shift, 0, 1000))
            self._difficulty = str(difficulty)
            self._duration = _number(duration, *DURATION_RANGE)
            self._start_at = self._now() + _number(countdown, *COUNTDOWN_RANGE)
            self._claims.clear()
            for p in self._players.values():
                p.money, p.trips = 0.0, 0
            return self._state()

    def reset(self) -> dict[str, Any]:
        """Back to the lobby (host only): clears claims and money, drops phones that left.

        Returns:
            The new state.
        """
        with self._lock:
            now = self._now()
            for p in [p for p in self._players.values() if now - p.seen > OFFLINE_S]:
                del self._players[p.id]
                del self._by_key[p.key]
            for p in self._players.values():
                p.money, p.trips = 0.0, 0
            self._claims.clear()
            self._start_at = None
            return self._state()


def qr_payload(url: str) -> dict[str, Any]:
    """The QR code of the player URL for the host's big screen.

    Args:
        url: URL the phones should open (empty: no code).

    Returns:
        ``{"url", "rows"}`` where ``rows`` are strings of ``1`` (dark) and ``0`` (light) modules;
        ``rows`` is empty if there is no URL or it is too long for the encoder.
    """
    try:
        matrix = encode(url, "M") if url else []
    except QRError:
        matrix = []
    return {"url": url, "rows": ["".join("1" if m else "0" for m in row) for row in matrix]}


def make_handler(
    party: Party, host_ips: frozenset[str], open_host: bool, join_url: str = ""
) -> type:
    """Build the request handler class bound to a party.

    Args:
        party: The game state.
        host_ips: Client addresses allowed to start and reset the game.
        open_host: Allow host actions from any address.
        join_url: URL of the players' page, served as a QR code at ``/api/qr``.

    Returns:
        A handler class for :class:`serve.LanServer`.
    """

    class PartyHandler(NoCacheHandler):
        """Static files from the game folder plus the JSON API."""

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            """Log everything except the 500 ms API polling."""
            if not self.path.startswith("/api/"):
                super().log_message(format, *args)

        def _reply(self, status: int, payload: dict[str, Any]) -> None:
            """Send a JSON reply."""
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict[str, Any]:
            """Read the JSON object of a POST.

            Raises:
                PartyError: If the body is missing, too large or not a JSON object.
            """
            try:
                size = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                size = -1
            if not 0 <= size <= MAX_BODY:
                raise PartyError("bad_body", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            try:
                body = json.loads(self.rfile.read(size) or b"{}")
            except ValueError as err:
                raise PartyError("bad_body") from err
            if not isinstance(body, dict):
                raise PartyError("bad_body")
            return body

        def do_GET(self) -> None:  # noqa: N802
            """Serve ``/api/party`` or a static file."""
            path = self.path.split("?", 1)[0]
            if path == "/api/party":
                self._reply(HTTPStatus.OK, party.state())
            elif path == "/api/qr":
                self._reply(HTTPStatus.OK, qr_payload(join_url))
            elif path.startswith("/api/"):
                self._reply(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            else:
                super().do_GET()

        def do_POST(self) -> None:  # noqa: N802
            """Run one API action."""
            path = self.path.split("?", 1)[0]
            try:
                if path in HOST_PATHS and not (
                    open_host or self.client_address[0] in host_ips
                ):
                    raise PartyError("host_only", HTTPStatus.FORBIDDEN)
                self._reply(HTTPStatus.OK, self._route(path, self._body()))
            except PartyError as err:
                self._reply(err.status, {"error": err.code})

        def _route(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
            """Dispatch a POST to the party.

            Raises:
                PartyError: If the path is unknown or the party refuses.
            """
            key = body.get("key")
            if path == "/api/join":
                player, state = party.join(body.get("name"), key)
                return {"id": player.id, "key": player.key, "state": state}
            if path == "/api/sync":
                return party.sync(key, body)
            if path == "/api/claim":
                ok, by = party.claim(key, body.get("order"))
                return {"ok": ok, "by": by}
            if path == "/api/release":
                return {"ok": party.release(key, body.get("order"))}
            if path == "/api/start":
                return party.start(
                    body.get("shift"),
                    body.get("difficulty"),
                    body.get("duration", DEFAULT_DURATION),
                    body.get("countdown", DEFAULT_COUNTDOWN),
                )
            if path == "/api/reset":
                return party.reset()
            raise PartyError("not_found", HTTPStatus.NOT_FOUND)

    return PartyHandler


def make_party_server(
    directory: Path,
    port: int,
    party: Party,
    host_ips: frozenset[str] = frozenset({LOOPBACK, "::1"}),
    open_host: bool = False,
    host: str = BIND_HOST,
    join_url: str = "",
) -> LanServer:
    """Create (but do not start) the party server.

    Args:
        directory: Folder with ``index.html``.
        port: TCP port; 0 lets the OS pick a free one.
        party: The game state.
        host_ips: Client addresses allowed to start and reset the game.
        open_host: Allow host actions from any address.
        host: Interface to bind.
        join_url: URL of the players' page for the QR code on the host screen.

    Returns:
        The bound server.
    """
    handler = make_handler(party, host_ips, open_host, join_url)

    def build(*args: Any, **kwargs: Any) -> Any:
        """Create a handler that serves ``directory``."""
        return handler(*args, directory=str(directory), **kwargs)

    return LanServer((host, port), build)


def main(argv: list[str] | None = None) -> int:
    """Command line entry point.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        0 after a clean stop (Ctrl+C), 1 if the build or the server could not start.
    """
    ap = argparse.ArgumentParser(description="Party mode: one map for everybody, from the phones")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="TCP port (default 8090)")
    ap.add_argument("--build", action="store_true", help="run pipeline.build_game first")
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="folder to serve")
    ap.add_argument("--host", default=None, help="address to show in the URL (default: detect)")
    ap.add_argument("--plain", action="store_true", help="no ANSI colours around the QR code")
    ap.add_argument("--open-host", action="store_true", help="host actions from any address")
    args = ap.parse_args(argv)
    if args.build and run_build() != 0:
        print("build failed, not serving", file=sys.stderr)
        return EXIT_FAIL
    if not (args.dir / "index.html").is_file():
        print(f"no game in {args.dir} (run with --build)", file=sys.stderr)
        return EXIT_FAIL
    try:
        lan = args.host or detect_lan_ip()
        player_url = build_url(lan, args.port) + "?party=1"
        host_url = build_url(LOOPBACK, args.port) + "?party=1&host=1"
        ips = frozenset({LOOPBACK, "::1", lan})
        server = make_party_server(
            args.dir, args.port, Party(), ips, args.open_host, join_url=player_url
        )
    except (OSError, ValueError) as err:
        print(f"cannot start the server: {err}", file=sys.stderr)
        return EXIT_FAIL
    print(banner(player_url, ansi=not args.plain and sys.stdout.isatty()))
    print(f"Ведучий (ноутбук): {host_url}")
    print(f"Party on {BIND_HOST}:{args.port}; Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
