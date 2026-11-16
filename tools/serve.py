"""Serve the built game to a phone on the same Wi-Fi and print its URL as a terminal QR code.

``python tools/serve.py [--port 8000] [--build] [--dir game]`` optionally rebuilds the game, then
serves the folder on 0.0.0.0 (threaded ``http.server``). No network calls are made to find the
LAN address: a UDP socket "connect" to a private address only asks the OS for its route.
"""

from __future__ import annotations

import argparse
import functools
import ipaddress
import socket
import socketserver
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from qr import QRError, encode, render_text

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PORT = 8000
DEFAULT_DIR = Path("game")
BIND_HOST = "0.0.0.0"  # all interfaces: the phone must reach it over the LAN
PROBE_ADDR = ("10.255.255.255", 1)  # private, never contacted: UDP connect sends no packet
LOOPBACK = "127.0.0.1"
PORT_MAX = 65535
HINT = "Відкрий на телефоні в тій самій Wi-Fi"
EXIT_OK = 0
EXIT_FAIL = 1


class NoCacheHandler(SimpleHTTPRequestHandler):
    """Static file handler that tells the phone browser never to cache (always the fresh build)."""

    def end_headers(self) -> None:
        """Add ``Cache-Control: no-store`` before the headers are sent."""
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class LanServer(ThreadingHTTPServer):
    """Threaded server that binds without the reverse DNS lookup ``HTTPServer`` does."""

    daemon_threads = True

    def server_bind(self) -> None:
        """Bind and record the address; skips ``getfqdn``, which blocks without DNS."""
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


def _usable(ip: ipaddress.IPv4Address) -> bool:
    """Whether an address is neither loopback, unspecified nor link-local.

    Args:
        ip: IPv4 address.

    Returns:
        ``True`` if a phone could plausibly reach it.
    """
    return not (ip.is_loopback or ip.is_unspecified or ip.is_link_local)


def _parse(text: str) -> ipaddress.IPv4Address | None:
    """Parse an IPv4 address.

    Args:
        text: Candidate text.

    Returns:
        The address, or ``None`` if the text is not an IPv4 address.
    """
    try:
        return ipaddress.IPv4Address(text)
    except ValueError:
        return None


def is_lan_ipv4(text: str) -> bool:
    """Whether a string is a private, non-loopback, non-link-local IPv4 address.

    Args:
        text: Candidate address such as ``"192.168.1.23"``.

    Returns:
        ``True`` for RFC 1918 addresses (10/8, 172.16/12, 192.168/16), ``False`` otherwise
        (including text that is not an IPv4 address).
    """
    ip = _parse(text)
    return ip is not None and ip.is_private and _usable(ip)


def pick_lan_ip(candidates: list[str]) -> str:
    """Choose the address to show on the QR code.

    Args:
        candidates: Addresses in order of preference.

    Returns:
        The first private LAN address; else the first usable non-loopback IPv4; else
        ``127.0.0.1``.
    """
    for text in candidates:
        if is_lan_ipv4(text):
            return text
    for text in candidates:
        ip = _parse(text)
        if ip is not None and _usable(ip):
            return text
    return LOOPBACK


def route_ip() -> str | None:
    """Ask the OS which local address it would use to reach a private network (no packets sent).

    Returns:
        The local IPv4 address, or ``None`` if there is no route.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(PROBE_ADDR)
            return str(sock.getsockname()[0])
        except OSError:
            return None


def hostname_ips() -> list[str]:
    """IPv4 addresses the machine's hostname resolves to (local resolver only).

    Returns:
        Addresses, possibly empty.
    """
    try:
        return socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        return []


def detect_lan_ip() -> str:
    """Find this machine's LAN IPv4 without network calls.

    Returns:
        The route address if it is private, else the best of route and hostname addresses, else
        loopback.
    """
    found = route_ip()
    if found is not None and is_lan_ipv4(found):
        return found  # the common case: no hostname lookup (it can be slow without DNS)
    return pick_lan_ip(([found] if found else []) + hostname_ips())


def build_url(host: str, port: int) -> str:
    """Make the URL the phone should open.

    Args:
        host: IPv4 address or host name.
        port: TCP port, 1..65535.

    Returns:
        ``http://host:port/``.

    Raises:
        ValueError: If the port is out of range.
    """
    if not 0 < port <= PORT_MAX:
        raise ValueError(f"port must be 1..{PORT_MAX}, got {port}")
    return f"http://{host}:{port}/"


def make_server(directory: Path, port: int, host: str = BIND_HOST) -> LanServer:
    """Create (but do not start) a threaded static file server.

    Args:
        directory: Folder to serve.
        port: TCP port; 0 lets the OS pick a free one.
        host: Interface to bind.

    Returns:
        The bound server.
    """
    handler = functools.partial(NoCacheHandler, directory=str(directory))
    return LanServer((host, port), handler)


def run_build(root: Path = REPO_ROOT) -> int:
    """Run ``python -m pipeline.build_game`` from the repository root.

    Args:
        root: Repository root (working directory of the build).

    Returns:
        The build's exit code.
    """
    cmd = [sys.executable, "-m", "pipeline.build_game"]
    return subprocess.run(cmd, cwd=root, check=False).returncode


def banner(url: str, ansi: bool) -> str:
    """Text shown to the user: QR code, URL and the Ukrainian hint.

    Args:
        url: URL to open on the phone.
        ansi: Draw the code black on white with ANSI colours.

    Returns:
        Multi-line text (the QR code is left out if the URL is too long for it).
    """
    try:
        code = render_text(encode(url, "M"), ansi=ansi)
    except QRError:
        return "\n".join([url, HINT])
    return "\n".join([code, url, HINT])


def main(argv: list[str] | None = None) -> int:
    """Command line entry point.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        0 after a clean stop (Ctrl+C), 1 if the build or the server could not start.
    """
    ap = argparse.ArgumentParser(description="Serve the game to a phone with a QR code")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="TCP port (default 8000)")
    ap.add_argument("--build", action="store_true", help="run pipeline.build_game first")
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="folder to serve")
    ap.add_argument("--host", default=None, help="address to show in the URL (default: detect)")
    ap.add_argument("--plain", action="store_true", help="no ANSI colours around the QR code")
    args = ap.parse_args(argv)
    if args.build and run_build() != 0:
        print("build failed, not serving", file=sys.stderr)
        return EXIT_FAIL
    if not args.dir.is_dir():
        print(f"no such folder: {args.dir}", file=sys.stderr)
        return EXIT_FAIL
    try:
        url = build_url(args.host or detect_lan_ip(), args.port)
        server = make_server(args.dir, args.port)
    except (OSError, ValueError) as err:
        print(f"cannot start the server: {err}", file=sys.stderr)
        return EXIT_FAIL
    print(banner(url, ansi=not args.plain and sys.stdout.isatty()))
    print(f"Serving {args.dir} on {BIND_HOST}:{args.port}; Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
