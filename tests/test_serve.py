import http.client
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import serve  # noqa: E402


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("192.168.1.23", True),
        ("10.0.0.5", True),
        ("172.16.4.4", True),
        ("172.31.255.1", True),
        ("172.32.0.1", False),
        ("8.8.8.8", False),
        ("127.0.0.1", False),
        ("169.254.10.10", False),
        ("0.0.0.0", False),
        ("::1", False),
        ("not an ip", False),
        ("", False),
    ],
)
def test_is_lan_ipv4(text: str, expected: bool) -> None:
    assert serve.is_lan_ipv4(text) is expected


def test_pick_lan_ip_prefers_private() -> None:
    assert serve.pick_lan_ip(["127.0.0.1", "8.8.4.4", "192.168.0.7", "10.1.1.1"]) == "192.168.0.7"


def test_pick_lan_ip_falls_back_to_public_then_loopback() -> None:
    assert serve.pick_lan_ip(["127.0.0.1", "169.254.1.1", "93.184.216.34"]) == "93.184.216.34"
    assert serve.pick_lan_ip(["127.0.0.1", "garbage", "0.0.0.0"]) == "127.0.0.1"
    assert serve.pick_lan_ip([]) == "127.0.0.1"


def test_build_url() -> None:
    assert serve.build_url("192.168.1.23", 8000) == "http://192.168.1.23:8000/"
    assert serve.build_url("10.0.0.2", 80) == "http://10.0.0.2:80/"
    for bad in (0, -1, 65536):
        with pytest.raises(ValueError):
            serve.build_url("10.0.0.2", bad)


def test_detect_lan_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(serve, "route_ip", lambda: "192.168.9.9")
    monkeypatch.setattr(serve, "hostname_ips", lambda: pytest.fail("no lookup needed"))
    assert serve.detect_lan_ip() == "192.168.9.9"
    monkeypatch.setattr(serve, "route_ip", lambda: None)
    monkeypatch.setattr(serve, "hostname_ips", lambda: ["127.0.0.1", "10.2.3.4"])
    assert serve.detect_lan_ip() == "10.2.3.4"
    monkeypatch.setattr(serve, "hostname_ips", lambda: [])
    assert serve.detect_lan_ip() == "127.0.0.1"


def test_route_ip_sends_nothing_and_returns_ipv4_or_none() -> None:
    got = serve.route_ip()
    assert got is None or serve._parse(got) is not None


def test_banner_has_qr_url_and_hint() -> None:
    text = serve.banner("http://192.168.1.23:8000/", ansi=False)
    lines = text.split("\n")
    assert lines[-2:] == ["http://192.168.1.23:8000/", serve.HINT]
    assert any("█" in line for line in lines[:-2])
    assert "\x1b[" not in text
    assert "\x1b[30;47m" in serve.banner("http://10.0.0.2:8000/", ansi=True)


def test_banner_without_qr_when_url_is_too_long() -> None:
    url = "http://" + "a" * 200 + "/"
    assert serve.banner(url, ansi=False) == f"{url}\n{serve.HINT}"


def test_server_serves_files_without_caching(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<p>ланоси</p>", encoding="utf-8")
    server = serve.make_server(tmp_path, 0, host="127.0.0.1")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        conn.request("GET", "/")
        res = conn.getresponse()
        assert res.status == 200
        assert res.getheader("Cache-Control") == "no-store"
        assert "ланоси" in res.read().decode("utf-8")
        conn.request("GET", "/missing.png")
        assert conn.getresponse().status == 404
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_main_rejects_missing_folder(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert serve.main(["--dir", str(tmp_path / "nope")]) == 1
    assert "no such folder" in capsys.readouterr().err


def test_main_stops_on_build_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(serve, "run_build", lambda: 1)
    assert serve.main(["--build", "--dir", str(tmp_path)]) == 1
    assert "build failed" in capsys.readouterr().err


def test_main_reports_a_busy_port(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(serve, "detect_lan_ip", lambda: "192.168.1.2")
    held = serve.make_server(tmp_path, 0)  # same 0.0.0.0 bind as main()
    try:
        port = held.server_address[1]
        assert serve.main(["--dir", str(tmp_path), "--port", str(port)]) == 1
        assert "cannot start" in capsys.readouterr().err
    finally:
        held.server_close()


def test_main_serves_and_prints_the_banner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    class Stop:
        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def server_close(self) -> None:
            pass

    monkeypatch.setattr(serve, "make_server", lambda directory, port: Stop())
    code = serve.main(["--dir", str(tmp_path), "--port", "8123", "--host", "192.168.7.7"])
    out = capsys.readouterr().out
    assert code == 0
    assert "http://192.168.7.7:8123/" in out and serve.HINT in out and "stopped" in out
