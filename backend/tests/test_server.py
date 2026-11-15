
import pytest
from fastapi.testclient import TestClient

from config import Settings
from main import create_app
from tests.conftest import FAKE_APPS, FakeLLM


def intent(i, target="", reply="", conf=0.95):
    return {"intent": i, "target": target, "reply": reply, "confidence": conf}


@pytest.fixture
def client(tmp_path, monkeypatch):
    s = Settings()
    s.data_dir = tmp_path
    s.dry_run = True
    s.telemetry_interval = 0.2
    s.max_pin_attempts = 3
    llm = FakeLLM({"spotify": intent("open_app", "spotify", "Opening Spotify."),
                   "shut down": intent("shutdown_pc")})
    app = create_app(s, llm=llm, background=False, pin="4321")
    with TestClient(app) as c:
        app.state.core.executor.apps.entries = list(FAKE_APPS)
        app.state.core.executor.apps.last_refresh = 1e12
        yield c


def recv_until(ws, type_, limit=50):
    for _ in range(limit):
        m = ws.receive_json()
        if m["type"] == type_:
            return m
    raise AssertionError(f"no {type_} message")


def pair_ws(client, pin="4321"):
    ws = client.websocket_connect("/ws").__enter__()
    assert ws.receive_json()["type"] == "hello"
    ws.send_json({"type": "auth", "pin": pin, "device_name": "Test Tablet"})
    return ws


def test_health_and_discover_are_public(client):
    assert client.get("/api/health").json()["pin_required"] is True
    d = client.get("/api/discover").json()
    assert d["service"] == "kageon" and d["ws_path"] == "/ws"


def test_http_requires_token(client):
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/telemetry", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_http_pair_and_use_token(client):
    assert client.post("/api/pair", json={"pin": "0000"}).status_code == 401
    token = client.post("/api/pair", json={"pin": "4321", "device_name": "T"}).json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    assert "cpu_percent" in client.get("/api/telemetry", headers=h).json()
    st = client.get("/api/status", headers=h).json()
    assert st["dry_run"] is True and st["apps_indexed"] == len(FAKE_APPS)
    assert client.get("/api/apps?q=spot", headers=h).json()["apps"][0]["name"] == "Spotify"
    r = client.post("/api/chat", json={"text": "open spotify"}, headers=h).json()
    assert r["status"] == "done"
    assert client.post("/api/launch", json={"target": "steam"}, headers=h).json()["ok"]


def test_http_lockout(client):
    for _ in range(2):
        assert client.post("/api/pair", json={"pin": "1111"}).status_code == 401
    assert client.post("/api/pair", json={"pin": "1111"}).status_code == 429
    assert client.post("/api/pair", json={"pin": "4321"}).status_code == 429


def test_ws_full_flow(client):
    ws = pair_ws(client)
    ok = ws.receive_json()
    assert ok["type"] == "auth_ok" and ok["token"]
    t = recv_until(ws, "telemetry")
    assert {"cpu_percent", "ram_percent", "gpu_percent", "vram_percent", "clock", "system_uptime"} <= t.keys()
    # telemetry keeps streaming
    recv_until(ws, "telemetry")

    ws.send_json({"type": "ping", "request_id": "p1"})
    assert recv_until(ws, "pong")["request_id"] == "p1"

    ws.send_json({"type": "chat", "text": "open spotify", "request_id": "c1"})
    r = recv_until(ws, "assistant_reply")
    assert r["request_id"] == "c1" and r["status"] == "done"

    ws.send_json({"type": "chat", "text": "shut down", "request_id": "c2"})
    r = recv_until(ws, "assistant_reply")
    assert r["status"] == "needs_confirmation"
    ws.send_json({"type": "confirm", "pending_id": r["pending_id"], "approve": False, "request_id": "c3"})
    assert recv_until(ws, "assistant_reply")["status"] == "cancelled"

    ws.send_json({"type": "launch", "target": "https://example.com", "request_id": "l1"})
    lr = recv_until(ws, "launch_result")
    assert lr["ok"] and lr["request_id"] == "l1"

    ws.send_json({"type": "list_apps", "query": "chrome"})
    assert recv_until(ws, "apps")["apps"][0]["name"] == "Google Chrome"

    ws.send_json({"type": "get_status"})
    assert recv_until(ws, "status")["clients"][0]["device_name"] == "Test Tablet"

    ws.send_text("{not json")
    assert recv_until(ws, "error")["error"] == "invalid_json"
    ws.send_json({"type": "self_destruct"})
    assert "unknown" in recv_until(ws, "error")["error"]
    ws.__exit__(None, None, None)


def test_ws_token_reconnect(client):
    ws = pair_ws(client)
    token = ws.receive_json()["token"]
    ws.__exit__(None, None, None)

    with client.websocket_connect("/ws") as ws2:
        ws2.receive_json()
        ws2.send_json({"type": "auth", "token": token})
        ok = ws2.receive_json()
        assert ok["type"] == "auth_ok" and "token" not in ok and ok["device_name"] == "Test Tablet"


def test_ws_rejects_wrong_pin_and_unauthenticated_commands(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "chat", "text": "open spotify"})
        assert ws.receive_json() == {"type": "auth_error", "reason": "auth_required"}
        ws.send_json({"type": "auth", "pin": "9999"})
        m = ws.receive_json()
        assert m["type"] == "auth_error" and m["reason"] == "invalid_pin"
        ws.send_json({"type": "auth", "token": "fake"})
        assert ws.receive_json()["reason"] == "invalid_token"


def test_ws_lockout(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        reasons = []
        for _ in range(4):
            ws.send_json({"type": "auth", "pin": "0000"})
            reasons.append(ws.receive_json()["reason"])
        assert reasons == ["invalid_pin", "invalid_pin", "locked_out", "locked_out"]



def test_mode_http_and_ws(client):
    token = client.post("/api/pair", json={"pin": "4321"}).json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/mode").status_code == 401
    st = client.get("/api/mode", headers=h).json()
    assert st["requested"] in ("auto", "gaming", "normal") and "label" in st
    st = client.post("/api/mode", json={"mode": "gaming"}, headers=h).json()
    assert st["requested"] == "gaming" and st["mode"] == "gaming" and st["model"] == "qwen3.5:4b"
    assert st["label"] == "qwen3.5:4b, Gaming mode (manual)"
    assert client.post("/api/mode", json={"mode": "turbo"}, headers=h).status_code == 400
    assert client.get("/api/status", headers=h).json()["mode"]["label"] == st["label"]

    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "auth", "token": token})
        assert ws.receive_json()["type"] == "auth_ok"
        assert recv_until(ws, "mode")["mode"] == "gaming"        # pushed right after connecting
        ws.send_json({"type": "set_mode", "mode": "normal", "request_id": "m1"})
        msgs = [recv_until(ws, "mode") for _ in range(2)]        # broadcast + direct reply
        assert {m.get("request_id") for m in msgs} == {None, "m1"}
        assert all(m["mode"] == "normal" and m["model"] == "qwen3.5:9b" for m in msgs)
        ws.send_json({"type": "get_mode", "request_id": "m2"})
        assert recv_until(ws, "mode")["request_id"] == "m2"
        ws.send_json({"type": "chat", "text": "which model are you using", "request_id": "c"})
        assert "qwen3.5:9b" in recv_until(ws, "assistant_reply")["reply"]



def test_memory_api(client):
    token = client.post("/api/pair", json={"pin": "4321"}).json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/memory").status_code == 401
    fid = client.post("/api/memory/facts", json={"text": "My games are on D"}, headers=h).json()["id"]
    rid = client.post("/api/routines", json={"trigger": "gaming time", "steps": ["open steam"]}, headers=h).json()["id"]
    m = client.get("/api/memory", headers=h).json()
    assert m["facts"][0]["text"] == "My games are on D." and m["routines"][0]["steps"] == ["open steam"]
    r = client.post("/api/chat", json={"text": "gaming time"}, headers=h).json()
    assert r["via"] == "routine" and r["status"] == "done"
    assert client.delete(f"/api/memory/facts/{fid}", headers=h).status_code == 200
    assert client.delete(f"/api/routines/{rid}", headers=h).status_code == 200
    assert client.delete(f"/api/routines/{rid}", headers=h).status_code == 404
    assert client.post("/api/routines", json={"trigger": "x", "steps": []}, headers=h).status_code == 400
    st = client.get("/api/status", headers=h).json()
    assert st["memory"]["facts"] == 0 and st["memory"]["conversations"] >= 1
