"""One command for the battle: party server + public https link, no account needed.

``python tools/deploy.py [--build] [--port 8123] [--dir game]`` builds the game if asked, opens a
Cloudflare quick tunnel (``cloudflared tunnel --url http://localhost:PORT``), reads the
``https://<words>.trycloudflare.com`` address it prints, starts the party server with that
address in every join link and QR code, shows the QR of the public link and runs until Ctrl+C.
Needs ``cloudflared`` (``brew install cloudflared``). Standard library only.
"""

from __future__ import annotations

import argparse
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from party import Rooms, load_sizes, make_party_server
from serve import (
    BIND_HOST,
    DEFAULT_DIR,
    EXIT_FAIL,
    EXIT_OK,
    banner,
    build_url,
    detect_lan_ip,
    run_build,
)

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


def caffeinate_command(pid: int, platform: str = sys.platform) -> list[str] | None:
    """The command that keeps a Mac awake while this process lives.

    Args:
        pid: Process id to follow (``caffeinate`` exits with it).
        platform: ``sys.platform``.

    Returns:
        ``caffeinate -dimsu -w PID`` on macOS, else ``None``.
    """
    return ["caffeinate", "-dimsu", "-w", str(pid)] if platform == "darwin" else None


def keep_awake() -> subprocess.Popen[str] | None:
    """Start ``caffeinate`` on macOS (no display, idle, disk or system sleep while running).

    Returns:
        The process, or ``None`` on other systems or if it cannot start.
    """
    cmd = caffeinate_command(os.getpid())
    if not cmd or not shutil.which(cmd[0]):
        return None
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def watch_tunnel(
    state: dict[str, object], port: int, binary: str, show: Callable[[str], None]
) -> None:
    """Restart cloudflared once if it dies and tell the server and the user the new address.

    Args:
        state: Shared dict with ``proc`` (the tunnel), ``server`` (has ``public_url``) and
            ``stop`` (``threading.Event``).
        port: Local port to expose again.
        binary: Path of ``cloudflared``.
        show: Called with the new public URL (prints the QR).
    """
    stop = state["stop"]
    assert isinstance(stop, threading.Event)
    proc = state["proc"]
    assert isinstance(proc, subprocess.Popen)
    while proc.poll() is None:
        if stop.wait(1.0):
            return
    if stop.is_set():
        return
    print("the tunnel stopped, starting it once more", file=sys.stderr)
    proc, url = start_tunnel(port, binary)
    state["proc"] = proc
    if url:
        state["server"].public_url = url  # type: ignore[attr-defined]
        show(url)
    else:
        print("the tunnel did not come back; players on the old link are lost", file=sys.stderr)


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
    ap.add_argument(
        "--via",
        choices=("tunnel", "lan"),
        default="tunnel",
        help="tunnel: public https link (default); lan: no tunnel, QR with the LAN IP",
    )
    ap.add_argument("--plain", action="store_true", help="no ANSI colours around the QR code")
    args = ap.parse_args(argv)
    binary = shutil.which("cloudflared") or ""
    if args.via == "tunnel" and not binary:
        print("cloudflared not found: brew install cloudflared (or use --via lan)", file=sys.stderr)
        return EXIT_FAIL
    if args.build and run_build() != 0:
        print("build failed, not serving", file=sys.stderr)
        return EXIT_FAIL
    if not (args.dir / "index.html").is_file():
        print(f"no game in {args.dir} (run with --build)", file=sys.stderr)
        return EXIT_FAIL
    awake = keep_awake()
    proc: subprocess.Popen[str] | None = None
    public = ""
    lan = ""
    if args.via == "tunnel":
        proc, found = start_tunnel(args.port, binary)
        if not found:
            stop_process(proc)
            print(
                "no public address from cloudflared (api.trycloudflare.com blocked or offline?);"
                " try --via lan",
                file=sys.stderr,
            )
            return EXIT_FAIL
        public = found
    else:
        lan = build_url(detect_lan_ip(), args.port)
    try:
        rooms = Rooms(sizes=load_sizes(args.dir / "game_data.json"))
        server = make_party_server(
            args.dir, args.port, rooms, BIND_HOST, lan_base=lan, public_url=public
        )
    except OSError as err:
        if proc:
            stop_process(proc)
        print(f"cannot start the server: {err}", file=sys.stderr)
        return EXIT_FAIL
    ansi = not args.plain and sys.stdout.isatty()

    def show(url: str) -> None:
        """Print the QR and the address."""
        print(banner(url + "/" if not url.endswith("/") else url, ansi=ansi), flush=True)
        print(f"Open: {url}  (local: http://localhost:{args.port}/); Ctrl+C to stop", flush=True)

    show(public or lan)
    state: dict[str, object] = {"proc": proc, "server": server, "stop": threading.Event()}
    if proc:
        threading.Thread(
            target=watch_tunnel, args=(state, args.port, binary, show), daemon=True
        ).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        state["stop"].set()  # type: ignore[attr-defined]
        server.server_close()
        for child in (state["proc"], awake):
            if child:
                stop_process(child)  # type: ignore[arg-type]
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
