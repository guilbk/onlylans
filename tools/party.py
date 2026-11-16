"""Party mode server: friends play one shift together on one map, each from their own phone.

``python tools/party.py [--port 8090] [--build] [--dir game]`` serves ``game/index.html`` (like
``tools/serve.py``) plus a small JSON API under ``/api/``. Standard library only.

Anyone can create a room from the game menu and share its 4-letter code. The state of one room
lives in the pure :class:`Party` class (lobby -> running -> done, players, the set of taken orders,
the start time); :class:`Rooms` keeps many of them; the clock is injected so it is tested without
a network. The server decides every order claim: the first claim wins. Game time on the phones
follows the server clock (``now`` and ``start_at`` in every reply). Host-only actions (start and
reset) need the host token that ``/api/create`` returns to the creator.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import secrets
import socket
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

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
MAX_TRIPS = 100_000
MAX_ACTIVE = 3  # booked, not yet picked up: the pickup, the next one, one release in flight
DEFAULT_SIZES = (700,) * 28  # orders per shift when no game data is given; real shifts have ~500
MAX_MONEY = 1_000_000.0
COORD_LIMIT = 1e6  # metres; the map is 15 x 19 km
DEFAULT_DURATION = 180.0  # real seconds of one shift: 7200 game seconds at 40x
DURATION_RANGE = (10.0, 1800.0)
DEFAULT_COUNTDOWN = 3.0  # the phones show 3-2-1
COUNTDOWN_RANGE = (0.0, 30.0)
GRACE_S = 2.0  # after the shift end the phones still post their final money
OFFLINE_S = 8.0  # no sync for this long: shown as offline
LOBBY_DROP_S = 25.0  # a guest who is silent this long leaves the lobby
ROOM_TTL_S = 4 * 3600.0  # an untouched room is forgotten
MAX_ROOMS = 200
CODE_LEN = 4
# Room code letters: no vowels (no words), no I, O, Q (look like 1, 0).
CODE_ALPHABET = "BCDFGHJKLMNPRSTVWXZ"
# Cyrillic letters that look like Latin ones, typed on a Ukrainian keyboard.
LOOKALIKE = str.maketrans("АВЕКМНОРСТХІ", "ABEKMHOPCTXI")
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
    at: float = 0.0  # server time of the last position, for smooth cars on the other phones


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


def order_index(value: object, count: int) -> int:
    """Validate an order index.

    Args:
        value: Value from the request body.
        count: Number of orders in the shift.

    Returns:
        The index.

    Raises:
        PartyError: If it is not an integer in ``[0, count)``.
    """
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < count:
        raise PartyError("bad_value")
    return value


def load_sizes(path: Path) -> tuple[int, ...]:
    """Read the order count of every shift from the game data.

    Args:
        path: ``game_data.json``.

    Returns:
        Orders per shift, or ``DEFAULT_SIZES`` if the file cannot be read.
    """
    try:
        shifts = json.loads(path.read_text(encoding="utf-8"))["shifts"]
        return tuple(len(sh["orders"]) for sh in shifts) or DEFAULT_SIZES
    except (OSError, ValueError, KeyError, TypeError):
        return DEFAULT_SIZES


def clean_code(raw: object) -> str:
    """Normalise a typed room code: upper case, spaces dropped, Cyrillic lookalikes turned Latin.

    Args:
        raw: The code as typed (any type; non-strings give an empty code).

    Returns:
        The code, possibly empty or not a valid room.
    """
    if not isinstance(raw, str):
        return ""
    return "".join(raw.upper().split()).translate(LOOKALIKE)[:CODE_LEN]


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

    def __init__(
        self,
        now: Callable[[], float] = time.time,
        code: str = "",
        sizes: Sequence[int] = DEFAULT_SIZES,
    ) -> None:
        """Create an empty lobby.

        Args:
            now: Clock in seconds (injected for tests).
            code: The room code (shown in every state).
            sizes: Number of orders in each shift (the shifts that can be started).
        """
        self._now = now
        self._sizes = tuple(sizes)
        self.code = code
        self.token = secrets.token_hex(8)  # proves the host; given only to the creator
        self.touched = now()
        self._host_id: int | None = None
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

    def _prune(self) -> None:
        """In the lobby, drop guests who went silent (the host stays)."""
        self.touched = now = self._now()
        if self._phase() != "lobby":
            return
        for p in [p for p in self._players.values() if now - p.seen > LOBBY_DROP_S]:
            if p.id != self._host_id:
                del self._players[p.id]
                del self._by_key[p.key]

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
                "at": p.at,
                "online": now - p.seen <= OFFLINE_S,
            }
            for p in self._players.values()
        ]
        return {
            "room": self.code,
            "host": self._host_id,
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
            self._prune()
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
            self._prune()
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
            if self._host_id is None:
                self._host_id = player.id
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
            self._prune()
            if self._phase() == "done":
                return self._state()  # the final money is what the last sync said
            if "x" in body and "y" in body:
                p.x = _number(body["x"], -COORD_LIMIT, COORD_LIMIT)
                p.y = _number(body["y"], -COORD_LIMIT, COORD_LIMIT)
                p.at = self._now()
            if "hx" in body and "hy" in body:
                p.hx = _number(body["hx"], -1.0, 1.0)
                p.hy = _number(body["hy"], -1.0, 1.0)
            if "money" in body:
                p.money = _number(body["money"], 0.0, MAX_MONEY)
            if "trips" in body:
                p.trips = int(_number(body["trips"], 0, MAX_TRIPS))
            return self._state()

    def claim(self, key: object, order: object) -> tuple[bool, str | None]:
        """Try to take an order; the first claim wins.

        Args:
            key: Secret key of the player.
            order: Order index in the shift (an integer below the shift's order count).

        Returns:
            ``(True, None)`` if the player now owns it (or already did), else ``(False, name)``
            with the name of the player who took it first.

        Raises:
            PartyError: If the key is unknown, the order is invalid, the player holds too many
                bookings, or the shift is not on (countdown and the closing grace do not count).
        """
        with self._lock:
            p = self._player(key)
            n = order_index(order, self._sizes[self._shift])
            now = self._now()
            start = self._start_at
            if start is None or not start <= now < start + self._duration:
                raise PartyError("phase", HTTPStatus.CONFLICT)
            owner = self._claims.get(n)
            if owner is None:
                if self._active(p) >= MAX_ACTIVE:
                    raise PartyError("too_many", HTTPStatus.CONFLICT)
                self._claims[n] = owner = p.id
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
            n = order_index(order, self._sizes[self._shift])
            if self._claims.get(n) != p.id:
                return False
            del self._claims[n]
            return True

    def _active(self, p: Player) -> int:
        """Orders the player booked and has not picked up yet (the reported trips are picked up)."""
        return sum(1 for owner in self._claims.values() if owner == p.id) - p.trips

    def _host(self, token: object) -> None:
        """Check the host token.

        Raises:
            PartyError: If the token is not the host's.
        """
        if not isinstance(token, str) or not secrets.compare_digest(token, self.token):
            raise PartyError("host_only", HTTPStatus.FORBIDDEN)

    def start(
        self,
        token: object,
        shift: object,
        difficulty: object,
        duration: object = DEFAULT_DURATION,
        countdown: object = DEFAULT_COUNTDOWN,
    ) -> dict[str, Any]:
        """Start the shift for everybody after a short countdown (host only).

        Args:
            token: The host token.
            shift: Index of the shift in the game data.
            difficulty: ``easy``, ``normal`` or ``hard``.
            duration: Real seconds the shift lasts.
            countdown: Real seconds until the start.

        Returns:
            The new state.

        Raises:
            PartyError: If the token is wrong, a game is already running, the shift does not exist,
                or a value is invalid.
        """
        with self._lock:
            self._host(token)
            if self._phase() != "lobby":
                raise PartyError("phase", HTTPStatus.CONFLICT)
            if difficulty not in DIFFICULTIES:
                raise PartyError("bad_value")
            self._shift = order_index(shift, len(self._sizes))
            self._difficulty = str(difficulty)
            self._duration = _number(duration, *DURATION_RANGE)
            self._start_at = self._now() + _number(countdown, *COUNTDOWN_RANGE)
            self._claims.clear()
            for p in self._players.values():
                p.money, p.trips = 0.0, 0
            return self._state()

    def reset(self, token: object) -> dict[str, Any]:
        """Back to the lobby (host only): clears claims and money, drops phones that left.

        Args:
            token: The host token.

        Returns:
            The new state.

        Raises:
            PartyError: If the token is wrong.
        """
        with self._lock:
            self._host(token)
            now = self._now()
            for p in [p for p in self._players.values() if now - p.seen > OFFLINE_S]:
                if p.id == self._host_id:
                    continue
                del self._players[p.id]
                del self._by_key[p.key]
            for p in self._players.values():
                p.money, p.trips = 0.0, 0
            self._claims.clear()
            self._start_at = None
            return self._state()


class Rooms:
    """Many parties side by side, found by a 4-letter code."""

    def __init__(
        self,
        now: Callable[[], float] = time.time,
        rng: random.Random | None = None,
        sizes: Sequence[int] = DEFAULT_SIZES,
    ) -> None:
        """Create an empty registry.

        Args:
            now: Clock in seconds (injected for tests).
            rng: Source of room codes (injected for tests).
            sizes: Number of orders in each shift, passed to every room.
        """
        self._now = now
        self._sizes = tuple(sizes)
        self._rng = rng or random.Random()
        self._lock = threading.Lock()
        self._rooms: dict[str, Party] = {}

    def create(self, name: object) -> tuple[Party, Player, dict[str, Any]]:
        """Open a room; its creator joins it as the first player and holds the host token.

        Args:
            name: The creator's wanted name.

        Returns:
            The room, the creator and the new state.

        Raises:
            PartyError: If there are too many rooms.
        """
        with self._lock:
            now = self._now()
            for code in [c for c, r in self._rooms.items() if now - r.touched > ROOM_TTL_S]:
                del self._rooms[code]
            if len(self._rooms) >= MAX_ROOMS:
                raise PartyError("busy", HTTPStatus.SERVICE_UNAVAILABLE)
            code = ""
            while not code or code in self._rooms:
                code = "".join(self._rng.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
            room = Party(self._now, code, self._sizes)
            self._rooms[code] = room
        player, state = room.join(name)
        return room, player, state

    def get(self, code: object) -> Party:
        """Find a room by the code as typed.

        Raises:
            PartyError: If there is no such room.
        """
        with self._lock:
            room = self._rooms.get(clean_code(code))
        if room is None:
            raise PartyError("no_room", HTTPStatus.NOT_FOUND)
        return room


def qr_payload(url: str) -> dict[str, Any]:
    """The QR code of a join link for the projector view and the lobby.

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


def join_link(host_header: str, code: str, lan_base: str = "") -> str:
    """The link that opens a room: the caller's own address, or the LAN one for a loopback caller.

    Args:
        host_header: The ``Host`` header of the request (``name:port``).
        code: The room code.
        lan_base: ``http://LAN-IP:port/`` to use when the caller is on this machine itself.

    Returns:
        ``<base>?room=CODE``.
    """
    name = host_header.rsplit(":", 1)[0].strip("[]")
    local = name in (LOOPBACK, "::1", "localhost")
    base = lan_base if local and lan_base else f"http://{host_header}/"
    return f"{base}?room={code}"


def route_create(rooms: Rooms, body: dict[str, Any]) -> dict[str, Any]:
    """Open a room for the caller (the reply holds the host token; only the creator gets it).

    Args:
        rooms: The registry of parties.
        body: The request body (``name``).

    Returns:
        ``{room, token, id, key, state}``.
    """
    room, player, state = rooms.create(body.get("name"))
    return {
        "room": room.code,
        "token": room.token,
        "id": player.id,
        "key": player.key,
        "state": state,
    }


def route(rooms: Rooms, path: str, body: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a POST to its room.

    Args:
        rooms: The registry of parties.
        path: The URL path.
        body: The JSON body.

    Returns:
        The JSON reply.

    Raises:
        PartyError: If the path is unknown or the party refuses.
    """
    if path == "/api/create":
        return route_create(rooms, body)
    room = rooms.get(body.get("room"))
    key = body.get("key")
    if path == "/api/join":
        player, state = room.join(body.get("name"), key)
        return {"id": player.id, "key": player.key, "state": state}
    if path == "/api/sync":
        return room.sync(key, body)
    if path == "/api/claim":
        ok, by = room.claim(key, body.get("order"))
        return {"ok": ok, "by": by}
    if path == "/api/release":
        return {"ok": room.release(key, body.get("order"))}
    token = body.get("token")
    if path == "/api/start":
        duration = body.get("duration", DEFAULT_DURATION)
        countdown = body.get("countdown", DEFAULT_COUNTDOWN)
        return room.start(token, body.get("shift"), body.get("difficulty"), duration, countdown)
    if path == "/api/reset":
        return room.reset(token)
    raise PartyError("not_found", HTTPStatus.NOT_FOUND)


class PartyHandler(NoCacheHandler):
    """Static files from the game folder plus the JSON API (keep-alive, no Nagle delay).

    ``rooms`` and ``lan_base`` are set by :func:`make_party_server` on a subclass.
    """

    protocol_version = "HTTP/1.1"
    rooms: Rooms
    lan_base = ""

    def setup(self) -> None:
        """Turn off Nagle's algorithm: a small reply must leave at once."""
        super().setup()
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def log_message(self, format: str, *args: object) -> None:
        """Log everything except the 200 ms API polling."""
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
            PartyError: If it is not ``application/json``, or is missing, too large or not an
                object. (A page of another site cannot send that type without a preflight.)
        """
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            raise PartyError("bad_type", HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
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

    def _get_api(self, path: str, code: str) -> dict[str, Any]:
        """Answer ``/api/party`` and ``/api/qr``.

        Raises:
            PartyError: If the path or the room is unknown.
        """
        if path == "/api/party":
            return self.rooms.get(code).state()
        if path == "/api/qr":
            room = self.rooms.get(code)
            return qr_payload(join_link(self.headers.get("Host", ""), room.code, self.lan_base))
        raise PartyError("not_found", HTTPStatus.NOT_FOUND)

    def do_GET(self) -> None:
        """Serve ``/api/party?room=``, ``/api/qr?room=`` or a static file."""
        path, _, query = self.path.partition("?")
        if not path.startswith("/api/"):
            super().do_GET()
            return
        try:
            self._reply(HTTPStatus.OK, self._get_api(path, parse_qs(query).get("room", [""])[0]))
        except PartyError as err:
            self._reply(err.status, {"error": err.code})

    def do_POST(self) -> None:
        """Run one API action."""
        try:
            body = self._body()
            self._reply(HTTPStatus.OK, route(self.rooms, self.path.split("?", 1)[0], body))
        except PartyError as err:
            self._reply(err.status, {"error": err.code})


def make_party_server(
    directory: Path,
    port: int,
    rooms: Rooms,
    host: str = BIND_HOST,
    lan_base: str = "",
) -> LanServer:
    """Create (but do not start) the party server.

    Args:
        directory: Folder with ``index.html``.
        port: TCP port; 0 lets the OS pick a free one.
        rooms: The registry of parties.
        host: Interface to bind.
        lan_base: URL of this server on the LAN, for links shown on this machine itself.

    Returns:
        The bound server.
    """
    handler = type("BoundPartyHandler", (PartyHandler,), {"rooms": rooms, "lan_base": lan_base})

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
    ap = argparse.ArgumentParser(description="Party mode: rooms for friends, each on a phone")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="TCP port (default 8090)")
    ap.add_argument("--build", action="store_true", help="run pipeline.build_game first")
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="folder to serve")
    ap.add_argument("--host", default=None, help="address to show in the URL (default: detect)")
    ap.add_argument("--plain", action="store_true", help="no ANSI colours around the QR code")
    args = ap.parse_args(argv)
    if args.build and run_build() != 0:
        print("build failed, not serving", file=sys.stderr)
        return EXIT_FAIL
    if not (args.dir / "index.html").is_file():
        print(f"no game in {args.dir} (run with --build)", file=sys.stderr)
        return EXIT_FAIL
    try:
        lan = args.host or detect_lan_ip()
        base = build_url(lan, args.port)
        server = make_party_server(
            args.dir, args.port, Rooms(sizes=load_sizes(args.dir / "game_data.json")), lan_base=base
        )
    except (OSError, ValueError) as err:
        print(f"cannot start the server: {err}", file=sys.stderr)
        return EXIT_FAIL
    print(banner(base, ansi=not args.plain and sys.stdout.isatty()))
    print("Гра разом: у меню натисни «Гра разом» і створи лобі, або відкрий ?party=1")
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
