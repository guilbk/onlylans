"""One command for the battle: party server + public https link, no account needed.

``python tools/deploy.py [--build] [--port 8123] [--dir game]`` builds the game if asked, opens a
Cloudflare quick tunnel (``cloudflared tunnel --url http://localhost:PORT``), reads the
``https://<words>.trycloudflare.com`` address it prints, starts the party server with that
address in every join link and QR code, shows the QR of the public link and runs until Ctrl+C.
Needs ``cloudflared`` (``brew install cloudflared``). Standard library only.
"""

from __future__ import annotations

import argparse
import queue
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from party import Rooms, load_sizes, make_party_server
from serve import BIND_HOST, DEFAULT_DIR, EXIT_FAIL, EXIT_OK, banner, run_build

DEFAULT_PORT = 8123
TUNNEL_WAIT_S = 45.0  # how long to wait for cloudflared to print its address
TUNNEL_RE = re.compile(r"https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com")
IGNORED_HOSTS = ("api.trycloudflare.com",)  # cloudflared logs its own API address too


def parse_tunnel_url(line: str) -> str | None:
    """Find the public address in one line of cloudflared output.

    Args:
        line: A log line.

    Returns:
        ``https://<words>.trycloudflare.com``, or ``None`` if the line has none (the API address
        of Cloudflare itself does not count).
    """
    for found in TUNNEL_RE.findall(line):
        if found.removeprefix("https://") not in IGNORED_HOSTS:
            return found
    return None


def tunnel_command(port: int, binary: str = "cloudflared") -> list[str]:
    """The command that opens a quick tunnel to a local port.

    Args:
        port: Local TCP port of the party server.
        binary: The ``cloudflared`` executable.

    Returns:
        The argument list.
    """
    return [binary, "tunnel", "--no-autoupdate", "--url", f"http://localhost:{port}"]


def read_tunnel_url(lines: queue.Queue[str | None], timeout: float) -> str | None:
    """Wait for the public address in the lines of cloudflared output.

    Args:
        lines: Output lines; ``None`` marks the end of the output.
        timeout: Seconds to wait for the next line.

    Returns:
        The address, or ``None`` if the output ended or went silent first.
    """
    while True:
        try:
            line = lines.get(timeout=timeout)
        except queue.Empty:
            return None
        if line is None:
            return None
        url = parse_tunnel_url(line)
        if url:
            return url


def _pump(proc: subprocess.Popen[str], lines: queue.Queue[str | None]) -> None:
    """Copy the tunnel's output to a queue (and keep draining it so it never blocks)."""
    assert proc.stdout is not None
    for line in proc.stdout:
        lines.put(line)
    lines.put(None)


def start_tunnel(port: int, binary: str) -> tuple[subprocess.Popen[str], str | None]:
    """Start cloudflared and wait for the public address.

    Args:
        port: Local port to expose.
        binary: Path of ``cloudflared``.

    Returns:
        The running process and the address (``None`` if it never appeared).
    """
    proc = subprocess.Popen(
        tunnel_command(port, binary),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    lines: queue.Queue[str | None] = queue.Queue()
    threading.Thread(target=_pump, args=(proc, lines), daemon=True).start()
    return proc, read_tunnel_url(lines, TUNNEL_WAIT_S)


def stop_process(proc: subprocess.Popen[str]) -> None:
    """Stop a child process politely, then hard."""
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def main(argv: list[str] | None = None) -> int:
    """Command line entry point.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        0 after Ctrl+C, 1 if something could not start.
    """
    ap = argparse.ArgumentParser(description="Party server + public https link for the battle")
    ap.add_argument("--build", action="store_true", help="run pipeline.build_game first")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="local port (default 8123)")
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="folder to serve")
    ap.add_argument("--plain", action="store_true", help="no ANSI colours around the QR code")
    args = ap.parse_args(argv)
    binary = shutil.which("cloudflared")
    if not binary:
        print("cloudflared not found: brew install cloudflared", file=sys.stderr)
        return EXIT_FAIL
    if args.build and run_build() != 0:
        print("build failed, not serving", file=sys.stderr)
        return EXIT_FAIL
    if not (args.dir / "index.html").is_file():
        print(f"no game in {args.dir} (run with --build)", file=sys.stderr)
        return EXIT_FAIL
    proc, public = start_tunnel(args.port, binary)
    if not public:
        stop_process(proc)
        print("no public address from cloudflared (offline?)", file=sys.stderr)
        return EXIT_FAIL
    try:
        rooms = Rooms(sizes=load_sizes(args.dir / "game_data.json"))
        server = make_party_server(args.dir, args.port, rooms, BIND_HOST, public_url=public)
    except OSError as err:
        stop_process(proc)
        print(f"cannot start the server: {err}", file=sys.stderr)
        return EXIT_FAIL
    print(banner(public + "/", ansi=not args.plain and sys.stdout.isatty()))
    print(f"Public: {public}/  (local: http://localhost:{args.port}/); Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
        stop_process(proc)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
