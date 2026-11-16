import socket
import sys

from fastapi.testclient import TestClient

from config import Settings
from main import create_app
from tray import Tray, make_icon_image, port_in_use, redirect_output_to_log
from conftest import FakeLLM


def test_icon_is_a_cyan_crescent_with_transparency():
    img = make_icon_image(64)
    assert img.size == (64, 64) and img.mode == "RGBA"
    alphas = [px[3] for px in img.getdata()]
    assert 0 in alphas and 255 in alphas                     # transparent corners + solid moon
    assert img.getpixel((14, 40))[:3] == (34, 211, 238)     # left side of the crescent is cyan
    assert img.getpixel((50, 20))[3] == 0                    # the "bite" on the right is see-through


def test_output_goes_to_log_file_and_rotates(tmp_path, monkeypatch):
    log = tmp_path / "kageon.log"
    log.write_bytes(b"x" * (2 * 1024 * 1024 + 1))            # previous run's log is too big
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    f = redirect_output_to_log(log)
    try:
        print("PIN ACCESS CODE :   123 456")
        assert not sys.stdout.isatty()                       # uvicorn checks this; must not crash
    finally:
        f.close()
    assert "123 456" in log.read_text(encoding="utf-8")
    assert (tmp_path / "kageon.log.old").stat().st_size > 2 * 1024 * 1024


def test_port_in_use():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert port_in_use(port)
    finally:
        srv.close()
    assert not port_in_use(port)


def test_tray_without_windows_is_harmless(tmp_path):
    quits = []
    t = Tray(on_quit=lambda: quits.append(1), log_path=tmp_path / "kageon.log")
    if sys.platform != "win32":
        assert t.start() is False and t.error
    t.ready({"pin": "123456", "wake_phrase": "Hey Kageon"})  # no icon -> no crash
    assert t.pin == "123456" and t.status == "running"
    t._quit()
    import time
    for _ in range(50):
        if quits:
            break
        time.sleep(0.01)
    assert quits == [1]
    t.stop()


def test_server_reports_ready_with_pin(tmp_path):
    s = Settings()
    s.data_dir = tmp_path
    s.dry_run = True
    seen = []
    app = create_app(s, llm=FakeLLM(), background=False, pin="4321", on_ready=seen.append)
    with TestClient(app):
        pass
    assert seen and seen[0]["pin"] == "4321"
