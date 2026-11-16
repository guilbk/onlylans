import queue
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import deploy  # noqa: E402


def test_parse_tunnel_url() -> None:
    line = "2026-11-16T18:00:00Z INF |  https://rapid-fox-lamp-zone.trycloudflare.com   |"
    assert deploy.parse_tunnel_url(line) == "https://rapid-fox-lamp-zone.trycloudflare.com"
    assert deploy.parse_tunnel_url("INF Requesting new quick Tunnel") is None
    assert deploy.parse_tunnel_url("POST https://api.trycloudflare.com/tunnel") is None
    assert deploy.parse_tunnel_url("http://a.trycloudflare.com") is None
    both = "https://api.trycloudflare.com then https://a-b.trycloudflare.com"
    assert deploy.parse_tunnel_url(both) == "https://a-b.trycloudflare.com"


def test_tunnel_command_points_at_the_local_port() -> None:
    cmd = deploy.tunnel_command(8123, "/bin/cf")
    assert cmd[0] == "/bin/cf"
    assert cmd[-2:] == ["--url", "http://localhost:8123"]


def test_read_tunnel_url_skips_noise_and_stops_at_the_end() -> None:
    q: queue.Queue[str | None] = queue.Queue()
    for line in ("INF starting", "INF https://x-y.trycloudflare.com ready", "more"):
        q.put(line)
    assert deploy.read_tunnel_url(q, 0.1) == "https://x-y.trycloudflare.com"
    ended: queue.Queue[str | None] = queue.Queue()
    ended.put("noise")
    ended.put(None)
    assert deploy.read_tunnel_url(ended, 0.1) is None
    assert deploy.read_tunnel_url(queue.Queue(), 0.05) is None


def test_start_tunnel_reads_the_address_from_a_child(monkeypatch) -> None:
    script = "print('hi'); print('url https://t-t.trycloudflare.com ok', flush=True)"
    monkeypatch.setattr(
        deploy, "tunnel_command", lambda port, binary: [sys.executable, "-c", script]
    )
    proc, url = deploy.start_tunnel(1, "x")
    deploy.stop_process(proc)
    assert url == "https://t-t.trycloudflare.com"
    assert proc.poll() is not None


def test_stop_process_kills_a_running_child() -> None:
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], text=True)
    deploy.stop_process(proc)
    assert proc.poll() is not None


def test_main_without_cloudflared_fails(monkeypatch, capsys) -> None:
    monkeypatch.setattr(deploy.shutil, "which", lambda name: None)
    assert deploy.main([]) == deploy.EXIT_FAIL
    assert "brew install cloudflared" in capsys.readouterr().err
