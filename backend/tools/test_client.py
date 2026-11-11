"""
Tablet simulator -- test the backend exactly the way the tablet app will use it.

  python tools/test_client.py --check          automatic end-to-end check (discovery, PIN, telemetry, JARVIS)
  python tools/test_client.py                  interactive: discover -> PIN -> chat with JARVIS
  python tools/test_client.py --watch          live telemetry stream
  python tools/test_client.py --discover       only test UDP auto-discovery

Options: --host 192.168.1.20 (skip discovery)  --port 8765  --pin 1234  --forget (drop saved token)

Run it on the PC itself, or copy this file to a laptop on the same Wi-Fi to test over the network
(it only needs:  pip install websockets).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sys
import time
from pathlib import Path

try:
    import websockets
except ImportError:
    sys.exit("Missing package: pip install websockets")

SERVICE_ID = "ai-command-center"
DISCOVERY_PORT = 37020
TOKEN_FILE = Path(__file__).with_name(".token")

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

GREEN, RED, YELLOW, CYAN, DIM, RESET = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[2m", "\033[0m"
if sys.platform == "win32":
    import os
    os.system("")  # enable ANSI colors in Windows terminals


# ------------------------------------------------------------------ discovery
def _broadcast_addrs() -> list[str]:
    addrs = {"255.255.255.255", "127.0.0.1"}
    try:
        import ipaddress
        import psutil
        for ifaddrs in psutil.net_if_addrs().values():
            for a in ifaddrs:
                if a.family == socket.AF_INET and a.netmask and not a.address.startswith("127."):
                    addrs.add(str(ipaddress.IPv4Network(f"{a.address}/{a.netmask}", strict=False).broadcast_address))
    except Exception:
        pass
    return sorted(addrs)


def discover(timeout: float = 4.0, port: int = DISCOVERY_PORT) -> list[dict]:
    """Active probe (fast) + passive listen for announcements. Returns unique servers."""
    found: dict[tuple, dict] = {}
    probe = json.dumps({"service": SERVICE_ID, "type": "probe"}).encode()

    active = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    active.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    active.bind(("0.0.0.0", 0))
    active.settimeout(0.2)

    passive = None
    try:
        passive = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        passive.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        passive.bind(("0.0.0.0", port))
        passive.settimeout(0.2)
    except OSError:
        passive = None

    end = time.time() + timeout
    next_probe = 0.0
    while time.time() < end:
        if time.time() >= next_probe:
            for addr in _broadcast_addrs():
                try:
                    active.sendto(probe, (addr, port))
                except OSError:
                    pass
            next_probe = time.time() + 1.0
        for sock in (active, passive):
            if not sock:
                continue
            try:
                data, src = sock.recvfrom(4096)
                msg = json.loads(data)
                if msg.get("service") == SERVICE_ID and msg.get("type") in ("announce", "probe_reply"):
                    msg["_via"] = f"{msg['type']} from {src[0]}"
                    found.setdefault((msg["host"], msg["port"]), msg)
            except (socket.timeout, OSError, ValueError):
                pass
        if found and time.time() > end - timeout + 1.5:   # got something, don't wait the full timeout
            break
    active.close()
    if passive:
        passive.close()
    # prefer a real LAN address over 127.0.0.1 when both answered
    servers = sorted(found.values(), key=lambda m: m["host"].startswith("127."))
    return servers


# ------------------------------------------------------------------ connection
def load_tokens() -> dict:
    try:
        return json.loads(TOKEN_FILE.read_text())
    except Exception:
        return {}


def save_token(key: str, token: str) -> None:
    tokens = load_tokens()
    tokens[key] = token
    TOKEN_FILE.write_text(json.dumps(tokens, indent=2))


async def connect_and_auth(host: str, port: int, pin: str | None, server_name: str = ""):
    url = f"ws://{host}:{port}/ws"
    try:   # LAN connection: never route through a system HTTP proxy (websockets >= 15)
        ws = await websockets.connect(url, max_size=2**22, proxy=None)
    except TypeError:
        ws = await websockets.connect(url, max_size=2**22)
    hello = json.loads(await ws.recv())
    key = hello.get("server_name") or server_name or host
    token = load_tokens().get(key)

    if token:
        await ws.send(json.dumps({"type": "auth", "token": token}))
        msg = json.loads(await ws.recv())
        if msg["type"] == "auth_ok":
            return ws, msg, "token"
        print(f"{YELLOW}Saved token rejected ({msg.get('reason')}) -- pairing with PIN{RESET}")

    while True:
        code = pin or input(f"{CYAN}Enter the 4-digit PIN shown in the server terminal: {RESET}").strip()
        await ws.send(json.dumps({"type": "auth", "pin": code, "device_name": f"test-client@{socket.gethostname()}"}))
        msg = json.loads(await ws.recv())
        if msg["type"] == "auth_ok":
            save_token(key, msg["token"])
            return ws, msg, "pin"
        reason = msg.get("reason")
        if reason == "locked_out":
            print(f"{RED}Too many wrong PINs. Locked for {msg.get('retry_after')}s.{RESET}")
        else:
            print(f"{RED}Wrong PIN ({reason}).{RESET}")
        if pin:
            raise SystemExit(1)


def fmt_tel(t: dict) -> str:
    gpu = f"GPU {t['gpu_percent']:5.1f}%  VRAM {t['vram_percent']:5.1f}%" if t.get("gpu_percent") is not None else "GPU n/a"
    return (f"{t['clock']}  CPU {t['cpu_percent']:5.1f}%  RAM {t['ram_percent']:5.1f}%  {gpu}  "
            f"up {t['system_uptime']}")


# ------------------------------------------------------------------ modes
async def run_check(host, port, pin, name) -> int:
    results = []

    def ok(label, passed, detail=""):
        results.append(passed)
        print(f"  [{GREEN + 'PASS' if passed else RED + 'FAIL'}{RESET}] {label} {DIM}{detail}{RESET}")

    print(f"\n{CYAN}== End-to-end check against {host}:{port} =={RESET}")
    ws, auth, how = await connect_and_auth(host, port, pin, name)
    ok("WebSocket connect + auth", True, f"(via {how}, server '{auth.get('server_name')}')")

    tel, stamps = [], []
    t0 = time.time()
    while len(tel) < 4 and time.time() - t0 < 12:
        m = json.loads(await asyncio.wait_for(ws.recv(), 10))
        if m["type"] == "telemetry":
            tel.append(m)
            stamps.append(time.time())
    gap = (stamps[-1] - stamps[1]) / 2 if len(stamps) == 4 else 0
    ok("Telemetry stream (live updates)", len(tel) == 4 and 0.5 <= gap <= 2.5, f"(every {gap:.1f}s)")
    if tel:
        t = tel[-1]
        ok("CPU/RAM values valid", 0 <= t["cpu_percent"] <= 100 and 0 < t["ram_percent"] <= 100, fmt_tel(t))
        gpu_ok = t["gpu"]["available"]
        ok("NVIDIA GPU telemetry", gpu_ok, t["gpu"]["name"] or "not detected (install NVIDIA driver / nvidia-ml-py)")

    async def request(payload, rtype, timeout=90):
        payload["request_id"] = rid = f"r{time.time()}"
        await ws.send(json.dumps(payload))
        end = time.time() + timeout
        while time.time() < end:
            m = json.loads(await asyncio.wait_for(ws.recv(), timeout))
            if m["type"] == rtype and m.get("request_id") == rid:
                return m
        raise TimeoutError(rtype)

    pong = await request({"type": "ping"}, "pong")
    ok("Ping / pong", pong["type"] == "pong")

    st = await request({"type": "get_status"}, "status")
    ok("Ollama reachable", st["ollama"]["reachable"], st["ollama"].get("error") or "")
    ok(f"Model '{st['ollama']['model']}' installed", st["ollama"]["model_installed"],
       "" if st["ollama"]["model_installed"] else f"run: ollama pull {st['ollama']['model']}")
    ok("Apps indexed from Start Menu", st["apps_indexed"] > 10, f"({st['apps_indexed']} apps)")
    v = st["voice"]
    ok("Voice: wake word listening", v.get("wake_word") == "listening", str(v.get("wake_word")))
    ok("Voice: speech-to-text loaded", str(v.get("stt", "")).startswith("ready"), str(v.get("stt")))

    if st["ollama"]["model_installed"]:
        t1 = time.time()
        r = await request({"type": "chat", "text": "Say hello in five words."}, "jarvis_reply")
        ok("JARVIS chat answer", r["status"] in ("chat", "done"), f"({time.time() - t1:.1f}s) {r['reply'][:70]}")
        r = await request({"type": "chat", "text": "shut down the computer"}, "jarvis_reply")
        ok("Dangerous command asks for confirmation", r["status"] == "needs_confirmation", r["reply"][:70])
        if r.get("pending_id"):
            c = await request({"type": "confirm", "pending_id": r["pending_id"], "approve": False}, "jarvis_reply")
            ok("Cancel works (PC NOT shut down)", c["status"] == "cancelled")
    await ws.close()

    passed = sum(results)
    color = GREEN if passed == len(results) else YELLOW
    print(f"\n{color}{passed}/{len(results)} checks passed{RESET}\n")
    return 0 if passed == len(results) else 1


async def run_watch(ws, seconds: float):
    end = time.time() + seconds
    while time.time() < end:
        m = json.loads(await ws.recv())
        if m["type"] == "telemetry":
            print(fmt_tel(m))
        elif m["type"] == "jarvis_event":
            print(f"{CYAN}[voice] you: {m['user_text']}  ->  JARVIS: {m['reply']}{RESET}")


async def run_interactive(ws):
    print(f"""{DIM}Type anything to talk to JARVIS. Commands:
  /stats   /status   /apps <name>   /launch <path|url|app>   /yes   /no   /1 /2 /3   /watch   /quit{RESET}""")
    state = {"pending": None, "latest_tel": None}

    async def reader():
        async for raw in ws:
            m = json.loads(raw)
            t = m["type"]
            if t == "telemetry":
                state["latest_tel"] = m
            elif t in ("jarvis_reply", "jarvis_event"):
                prefix = "[voice] " if t == "jarvis_event" else ""
                print(f"\n{CYAN}{prefix}JARVIS ({m['status']}): {m['reply']}{RESET}")
                if m.get("options"):
                    for i, o in enumerate(m["options"], 1):
                        print(f"   /{i}  {o}")
                if m["status"] in ("needs_confirmation", "needs_choice"):
                    state["pending"] = m["pending_id"]
                    print(f"{DIM}   reply /yes or /no{' or /1 /2 /3' if m.get('options') else ''}{RESET}")
                print("> ", end="", flush=True)
            elif t == "launch_result":
                print(f"\n{GREEN if m['ok'] else RED}{m['message']}{RESET}\n> ", end="", flush=True)
            elif t == "apps":
                print()
                for a in m["apps"]:
                    print(f"   {a['name']}  {DIM}({a['kind']}){RESET}")
                print("> ", end="", flush=True)
            elif t == "status":
                print("\n" + json.dumps({k: v for k, v in m.items() if k != "type"}, indent=2, ensure_ascii=False))
                print("> ", end="", flush=True)
            elif t in ("error", "auth_error"):
                print(f"\n{RED}{m}{RESET}\n> ", end="", flush=True)

    task = asyncio.create_task(reader())
    try:
        while True:
            line = (await asyncio.to_thread(input, "> ")).strip()
            if not line:
                continue
            if line in ("/quit", "/exit", "/q"):
                break
            if line == "/stats":
                print(fmt_tel(state["latest_tel"]) if state["latest_tel"] else "no telemetry yet")
            elif line == "/status":
                await ws.send(json.dumps({"type": "get_status"}))
            elif line.startswith("/apps"):
                await ws.send(json.dumps({"type": "list_apps", "query": line[5:].strip()}))
            elif line.startswith("/launch "):
                await ws.send(json.dumps({"type": "launch", "target": line[8:].strip()}))
            elif line in ("/yes", "/no") or line in ("/1", "/2", "/3"):
                if not state["pending"]:
                    print("nothing to confirm")
                    continue
                msg = {"type": "confirm", "pending_id": state["pending"], "approve": line != "/no"}
                if line[1:].isdigit():
                    msg["choice"] = int(line[1:]) - 1
                await ws.send(json.dumps(msg))
                state["pending"] = None
            elif line == "/watch":
                for _ in range(10):
                    if state["latest_tel"]:
                        print(fmt_tel(state["latest_tel"]))
                    await asyncio.sleep(1.5)
            else:
                await ws.send(json.dumps({"type": "chat", "text": line}))
    finally:
        task.cancel()
        await ws.close()


async def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--pin")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--watch", type=float, nargs="?", const=30.0)
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--forget", action="store_true")
    args = ap.parse_args()

    if args.forget and TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
        print("Saved tokens deleted.")

    host, port, name = args.host, args.port, ""
    if not host:
        print(f"{DIM}Searching for the PC on the local network (UDP {DISCOVERY_PORT})...{RESET}")
        servers = discover()
        if not servers:
            print(f"{RED}تعذر الاتصال بالسيرفر! / Could not find the server.{RESET}")
            print("Hint: تأكد أن كلا الجهازين متصلان بنفس شبكة الـ Wi-Fi. "
                  "Also check the server is running and Windows Firewall allows Python (UDP 37020 + TCP 8765).")
            return 2
        for s in servers:
            print(f"{GREEN}Found '{s['name']}' at {s['host']}:{s['port']}{RESET} {DIM}({s['_via']}){RESET}")
        host, port, name = servers[0]["host"], servers[0]["port"], servers[0]["name"]
        if args.discover:
            return 0

    if args.check:
        return await run_check(host, port, args.pin, name)

    try:
        ws, auth, how = await connect_and_auth(host, port, args.pin, name)
    except OSError as exc:
        print(f"{RED}تعذر الاتصال بالسيرفر! ({exc}){RESET}")
        return 2
    print(f"{GREEN}Connected to '{auth.get('server_name')}' (auth via {how}).{RESET}")
    if args.watch:
        await run_watch(ws, args.watch)
        await ws.close()
    else:
        await run_interactive(ws)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        pass
