"""
KAGEON -- PC backend

Run:   python main.py
Then:  read the 4-digit PIN printed in the terminal and enter it on the tablet.

WebSocket protocol (ws://<pc-ip>:8765/ws) -- all messages are JSON objects with a "type":

  client -> server                                   server -> client
  ------------------------------------------------   -----------------------------------------------
  {"type":"auth","pin":"1234","device_name":"Tab"}   {"type":"auth_ok","token":"...","server_name":..}
  {"type":"auth","token":"<saved token>"}            {"type":"auth_error","reason":..,"retry_after":..}
  {"type":"ping"}                                    {"type":"pong"}
  {"type":"chat","text":"open spotify","request_id":"x"}  {"type":"assistant_reply","request_id":"x", ...}
  {"type":"confirm","pending_id":"..","approve":true,"choice":0}   {"type":"assistant_reply", ...}
  {"type":"launch","target":"C:\\\\Games\\\\x.exe","request_id":"y"}  {"type":"launch_result", ...}
  {"type":"get_telemetry"} / {"type":"get_status"}   {"type":"telemetry", ...} / {"type":"status", ...}
  {"type":"list_apps","query":"chr"}                 {"type":"apps","apps":[...]}
  {"type":"get_mode"}                                {"type":"mode","label":"qwen3.5:4b, Gaming mode (auto)",...}
  {"type":"set_mode","mode":"auto|gaming|normal"}    {"type":"mode", ...}   (also pushed on every change)
  {"type":"media_key","key":"play_pause"}            {"type":"media_result","key":..,"ok":..}  (silent: no chat)
  {"type":"notify_settings","enabled":..,"apps":[..]} {"type":"notify_status","status":..,"apps":[..]}
                                                     {"type":"pc_notification","app":..,"title":..}  (only
                                                      to tablets that turned it on, only apps they picked)
                                                     {"type":"media","playing":..,"title":..}  (pushed on change)
                                                     {"type":"telemetry", ...}   (pushed every 1.5 s)
                                                     {"type":"assistant_event", ...} (PC voice activity)
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from contextlib import asynccontextmanager
from typing import Callable

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from auth import AuthError, AuthManager
from config import SERVICE_ID, VERSION, Settings, get_settings, resolve_wake_model
from discovery import DiscoveryService, build_announcement, get_lan_ips
from executor import AppIndex, Executor
from files import FileManager
from games import GameDetector
from hotkey import GlobalHotkey
from hub import Client, Hub
from assistant import Assistant
from llm import OllamaClient
from media_watch import MediaWatcher
from notify_watch import NotificationWatcher, allowed_for
from memory import MemoryStore
from modes import ModeManager
from telemetry import TelemetryCollector
from voice import VoiceEngine

log = logging.getLogger("main")
AUTH_TIMEOUT = 30


def setup_logging(level: str) -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    logging.basicConfig(level=level.upper(), format="%(asctime)s %(levelname)-7s %(name)-9s %(message)s",
                        datefmt="%H:%M:%S")
    for noisy in ("httpx", "httpcore", "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def print_banner(s: Settings, pin: str, ollama: dict, gpu: str | None, hotkey: GlobalHotkey | None = None,
                 modes: ModeManager | None = None) -> None:
    ips = get_lan_ips()
    line = "=" * 60
    spaced_pin = "  ".join(pin)
    print(f"\n{line}\n   KAGEON  //  CORE v{VERSION}\n{line}")
    print(f"   PIN ACCESS CODE :   {spaced_pin}")
    print(f"{line}")
    for ip in ips:
        print(f"   WebSocket       :   ws://{ip}:{s.port}/ws")
    print(f"   Discovery (UDP) :   port {s.discovery_port} {'ON' if s.discovery_enabled else 'OFF'}")
    if not ollama.get("reachable"):
        print("   Ollama          :   NOT RUNNING (the model will load when Ollama starts)")
    else:
        installed = set(ollama.get("models", []))
        full = lambda m: m if ":" in m else f"{m}:latest"
        for role, m in (("Normal model", s.model_normal), ("Gaming model", s.model_gaming),
                        ("Fallback model", s.model_fallback)):
            ok = full(m) in installed
            print(f"   {role:<16}:   {m}  {'OK' if ok else 'MISSING -> run: ollama pull ' + m}")
    if modes is not None:
        if modes.requested == "auto" and modes.auto_available:
            games = "when a game starts or " if s.game_detection else "when "
            print(f"   Mode            :   AUTO (gaming {games}free VRAM < {modes.gaming_below} GB; "
                  f"normal {s.normal_after_seconds:.0f}s after)")
        elif modes.requested == "auto":
            print("   Mode            :   MANUAL (auto needs an NVIDIA GPU) - say 'gaming mode' / 'normal mode'")
        else:
            print(f"   Mode            :   {modes.requested.upper()} (manual - say 'auto mode' to switch back)")
    print(f"   GPU telemetry   :   {gpu or 'not available'}")
    if not s.voice_enabled:
        voice_line = "OFF"
    else:
        _, phrase, custom = resolve_wake_model(s.wake_word_model)
        voice_line = f"ON (say: {phrase})" if custom else f"ON (say: {phrase} -- temporary until Hey Kageon is trained)"
    print(f"   Voice           :   {voice_line}")
    if hotkey is not None:
        hk = f"{s.quit_hotkey.upper()} = quit Kageon" if hotkey.active else f"off ({hotkey.error})"
        print(f"   Quit shortcut   :   {hk}")
    if s.dry_run:
        print("   DRY RUN         :   ON (actions are only logged)")
    print(f"{line}\n", flush=True)


class State:
    settings: Settings
    auth: AuthManager
    telemetry: TelemetryCollector
    executor: Executor
    llm: OllamaClient
    assistant: Assistant
    hub: Hub
    voice: VoiceEngine
    discovery: DiscoveryService | None = None
    hotkey: GlobalHotkey | None = None
    modes: ModeManager
    memory: MemoryStore | None = None
    media: MediaWatcher
    notify: NotificationWatcher
    media_state: dict
    tasks: list[asyncio.Task]


def create_app(settings: Settings | None = None, llm: OllamaClient | None = None,
               background: bool = True, pin: str | None = None,
               on_quit: Callable[[], None] | None = None,
               on_ready: Callable[[dict], None] | None = None) -> FastAPI:
    """background=False disables UDP discovery, voice, hotkey and the Ollama warm-up (used by tests).
    on_quit is called (from any thread) when the quit hotkey is pressed.
    on_ready gets {"pin", "wake_phrase"} once the server is up (used by the tray icon)."""
    settings = settings or get_settings()
    st = State()
    st.settings = settings
    st.tasks = []

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        loop = asyncio.get_running_loop()
        st.auth = AuthManager(settings.data_dir, settings.max_pin_attempts, settings.lockout_seconds, pin=pin)
        st.telemetry = TelemetryCollector()
        st.executor = Executor(dry_run=settings.dry_run, app_index=AppIndex(), play_site=settings.play_site,
                           files=FileManager(settings.allowed_folders, settings.data_dir / "file_actions.json",
                                             dry_run=settings.dry_run))
        st.memory = MemoryStore(settings.data_dir / "memory.db") if settings.memory_enabled else None
        st.llm = llm or OllamaClient(settings.ollama_url, settings.model_normal, settings.ollama_timeout,
                                     settings.ollama_keep_alive, settings.think_default, settings.think_timeout)
        st.hub = Hub()
        st.media = MediaWatcher()
        st.notify = NotificationWatcher()
        st.media_state = {"available": False}
        st.voice = VoiceEngine(settings, loop, on_command=lambda text: st.assistant.handle_text(text, "voice"),
                               vram_reader=st.telemetry.vram_info)

        async def push_mode(state: dict):
            await st.hub.broadcast({"type": "mode", **state})
        st.modes = ModeManager(settings, st.llm, st.telemetry.vram_info, settings.data_dir,
                               announce=st.voice.announce if background else None, on_change=push_mode,
                               own_extra_vram=lambda: st.voice.stt.vram_bytes,
                               busy=lambda: bool(st.voice.status.get("busy")),
                               game_detector=GameDetector(settings.game_processes, settings.game_ignore)
                               if settings.game_detection else None)
        st.assistant = Assistant(st.llm, st.executor, st.telemetry, settings.confirm_timeout,
                           fast_commands=settings.fast_commands, modes=st.modes, memory=st.memory,
                           screen_max_side=settings.screen_max_side, max_memory_facts=settings.memory_max_facts)

        async def push_voice_events(resp: dict):
            if resp.get("source") == "voice":
                await st.hub.broadcast({"type": "assistant_event", **resp})
        st.assistant.add_listener(push_voice_events)

        st.tasks.append(asyncio.create_task(asyncio.to_thread(st.executor.apps.refresh)))
        st.tasks.append(asyncio.create_task(telemetry_loop()))
        if background:
            st.tasks.append(asyncio.create_task(media_loop()))
            st.tasks.append(asyncio.create_task(notify_loop()))

        if background and settings.discovery_enabled:
            st.discovery = DiscoveryService(settings.discovery_port, settings.port, settings.server_name,
                                            settings.broadcast_interval)
            try:
                await st.discovery.start()
            except OSError as exc:
                log.error("Discovery could not bind UDP %d: %s", settings.discovery_port, exc)
                st.discovery = None

        ollama = await st.llm.health() if background else {"reachable": False, "model_installed": False}
        if background:
            st.voice.start()
            # choose + load the right model (normal/gaming) and watch VRAM; waits for Ollama if it isn't up yet
            st.tasks.append(asyncio.create_task(st.modes.start()))
            if settings.quit_hotkey.strip() and on_quit:
                def quit_now():
                    log.info("Quit shortcut pressed -- shutting Kageon down")
                    on_quit()
                st.hotkey = GlobalHotkey(settings.quit_hotkey, quit_now)
                st.hotkey.start()
        print_banner(settings, st.auth.pin, ollama, st.telemetry.gpu_name, st.hotkey, st.modes)
        log.info("Server ready on port %d", settings.port)
        if on_ready:
            on_ready({"pin": st.auth.pin,
                      "wake_phrase": st.voice.wake_phrase if settings.voice_enabled else None})
        try:
            yield
        finally:
            for t in st.tasks:
                t.cancel()
            if background:
                await st.modes.stop(unload=settings.unload_on_exit)
            st.voice.stop()
            if st.memory:
                st.memory.close()
            if st.hotkey:
                st.hotkey.stop()
            if st.discovery:
                await st.discovery.stop()
            st.telemetry.close()

    async def telemetry_loop():
        while True:
            try:
                if st.hub.clients:
                    await st.hub.broadcast({"type": "telemetry", **st.telemetry.snapshot()})
            except Exception as exc:
                log.debug("telemetry loop: %s", exc)
            await asyncio.sleep(settings.telemetry_interval)

    async def refresh_media() -> None:
        """Read what's playing; tell the tablets only when it changed."""
        state = await st.media.read()
        if state != st.media_state:
            st.media_state = state
            await st.hub.broadcast({"type": "media", **state})

    async def media_loop():
        while True:
            try:
                if st.hub.clients:
                    await refresh_media()
            except Exception as exc:
                log.debug("media loop: %s", exc)
            await asyncio.sleep(settings.media_interval)

    def notify_status() -> dict:
        return {"type": "notify_status", "status": st.notify.status, "apps": st.notify.apps}

    async def check_notifications() -> None:
        """Read new PC notifications and pass each one only to the tablets that asked for that app."""
        apps_before = list(st.notify.apps)
        for n in await st.notify.poll():
            for c in list(st.hub.clients.values()):
                if allowed_for(c.notify, n["app"]):
                    await st.hub.send(c, {"type": "pc_notification", **n})
        if st.notify.apps != apps_before:   # a new app showed up: let the tablets offer it
            await st.hub.broadcast(notify_status())

    async def notify_loop():
        while True:
            try:
                if any(c.notify and c.notify.get("enabled") for c in st.hub.clients.values()):
                    await check_notifications()
            except Exception as exc:
                log.debug("notify loop: %s", exc)
            await asyncio.sleep(settings.notify_interval)

    app = FastAPI(title="Kageon Core", version=VERSION, lifespan=lifespan)
    app.state.core = st
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    # ------------------------------------------------------------------ helpers
    async def status_payload() -> dict:
        disc = st.discovery
        return {
            "service": SERVICE_ID, "version": VERSION, "server_name": settings.server_name,
            "lan_ips": get_lan_ips(), "port": settings.port, "dry_run": settings.dry_run,
            "ollama": await st.llm.health(),
            "mode": st.modes.status(),
            "gpu": {"available": st.telemetry.gpu_available, "name": st.telemetry.gpu_name,
                    "error": st.telemetry.gpu_error},
            "voice": st.voice.status,
            "quit_hotkey": {"keys": settings.quit_hotkey, "active": bool(st.hotkey and st.hotkey.active),
                            "error": st.hotkey.error if st.hotkey else None},
            "apps_indexed": len(st.executor.apps.entries), "app_index_errors": st.executor.apps.errors,
            "discovery": {"enabled": disc is not None, "port": settings.discovery_port,
                          "announcements_sent": disc.announcements_sent if disc else 0,
                          "probes_answered": disc.probes_answered if disc else 0},
            "clients": st.hub.summary(), "paired_devices": len(st.auth.paired_devices()),
            "memory": ({"facts": len(st.memory.facts()), "routines": len(st.memory.routines()),
                        "conversations": st.memory.count_conversations()} if st.memory else None),
        }

    def require_token(request: Request) -> str:
        header = request.headers.get("authorization", "")
        token = header[7:] if header.lower().startswith("bearer ") else request.query_params.get("token")
        if not st.auth.verify_token(token, request.client.host if request.client else None):
            raise HTTPException(status_code=401, detail="Not paired. Send the PIN to /api/pair first.")
        return token

    # ------------------------------------------------------------------ HTTP API
    @app.get("/api/health")
    async def health():
        return {"status": "ok", "service": SERVICE_ID, "version": VERSION,
                "server_name": settings.server_name, "pin_required": True}

    @app.get("/api/discover")
    async def discover(request: Request):
        return build_announcement(request.url.hostname or "", settings.port, settings.server_name)

    @app.post("/api/pair")
    async def pair(request: Request):
        body = await request.json()
        try:
            token = st.auth.pair_with_pin(str(body.get("pin", "")), request.client.host,
                                          str(body.get("device_name", "tablet")))
        except AuthError as e:
            code = 429 if e.reason == "locked_out" else 401
            raise HTTPException(code, detail={"reason": e.reason, "retry_after": e.retry_after})
        return {"token": token, "server_name": settings.server_name}

    @app.get("/api/status")
    async def status(_=Depends(require_token)):
        return await status_payload()

    @app.get("/api/telemetry")
    async def telemetry(_=Depends(require_token)):
        return st.telemetry.snapshot()

    @app.get("/api/apps")
    async def apps(q: str = "", limit: int = 20, _=Depends(require_token)):
        return {"apps": st.executor.apps.search(q, limit)}

    @app.post("/api/chat")
    async def chat(request: Request, _=Depends(require_token)):
        body = await request.json()
        return await st.assistant.handle_text(str(body.get("text", "")), "tablet")

    @app.post("/api/confirm")
    async def confirm(request: Request, _=Depends(require_token)):
        b = await request.json()
        return await st.assistant.confirm(str(b.get("pending_id", "")), bool(b.get("approve")), "tablet", b.get("choice"))

    @app.post("/api/launch")
    async def launch(request: Request, _=Depends(require_token)):
        b = await request.json()
        res = await asyncio.to_thread(st.executor.launch_target, str(b.get("target", "")))
        return {"ok": res.ok, "message": res.message, "data": res.data}

    @app.get("/api/mode")
    async def get_mode(_=Depends(require_token)):
        return st.modes.status()

    @app.post("/api/mode")
    async def set_mode(request: Request, _=Depends(require_token)):
        """Body: {"mode": "auto" | "gaming" | "normal"}. Manual choices stick until "auto" is set."""
        b = await request.json()
        try:
            return await st.modes.set_mode(str(b.get("mode", "")), source="tablet")
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    def need_memory() -> MemoryStore:
        if not st.memory:
            raise HTTPException(404, "Memory is turned off (MEMORY_ENABLED=false)")
        return st.memory

    @app.get("/api/memory")
    async def memory_get(_=Depends(require_token)):
        """All remembered facts and routines (for the tablet's memory screen)."""
        return need_memory().summary()

    @app.post("/api/memory/facts")
    async def memory_add(request: Request, _=Depends(require_token)):
        text = str((await request.json()).get("text", "")).strip()
        try:
            fact_id, updated = need_memory().add_fact(text)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"id": fact_id, "updated": updated}

    @app.delete("/api/memory/facts/{fact_id}")
    async def memory_delete(fact_id: int, _=Depends(require_token)):
        if not need_memory().delete_fact(fact_id):
            raise HTTPException(404, "No such memory")
        return {"deleted": fact_id}

    @app.post("/api/routines")
    async def routine_add(request: Request, _=Depends(require_token)):
        """Body: {"trigger": "gaming time", "steps": ["open steam", "open discord", "gaming mode"]}"""
        b = await request.json()
        steps = b.get("steps") or []
        try:
            rid, updated = need_memory().add_routine(str(b.get("trigger", "")), [str(x) for x in steps])
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"id": rid, "updated": updated}

    @app.delete("/api/routines/{routine_id}")
    async def routine_delete(routine_id: int, _=Depends(require_token)):
        if not need_memory().delete_routine_id(routine_id):
            raise HTTPException(404, "No such routine")
        return {"deleted": routine_id}

    @app.post("/api/voice")
    async def voice_upload(request: Request, _=Depends(require_token)):
        """Push-to-talk from the tablet: raw audio body (webm/ogg/wav/mp3...) -> transcript -> Kageon."""
        audio = await request.body()
        if not audio:
            raise HTTPException(400, "Empty audio body")
        try:
            text, lang = await asyncio.to_thread(st.voice.stt.transcribe, audio)
        except Exception as exc:
            raise HTTPException(500, f"Speech recognition failed: {exc}")
        if not text:
            return {"transcript": "", "language": lang, "reply": None}
        return {"transcript": text, "language": lang, "reply": await st.assistant.handle_text(text, "tablet_voice")}

    @app.get("/api/tts")
    async def tts(text: str, _=Depends(require_token)):
        try:
            mp3 = await st.voice.tts.synthesize(text[:1000])
        except Exception as exc:
            raise HTTPException(502, f"TTS failed (internet needed for edge-tts): {exc}")
        return Response(content=mp3, media_type="audio/mpeg")

    # ------------------------------------------------------------------ WebSocket
    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        ip = ws.client.host if ws.client else "?"

        async def send(msg: dict):
            await ws.send_text(json.dumps(msg, ensure_ascii=False, default=str))

        await send({"type": "hello", "service": SERVICE_ID, "version": VERSION,
                    "server_name": settings.server_name, "auth_required": True})

        # ---- authentication phase
        client: Client | None = None
        try:
            deadline = asyncio.get_running_loop().time() + AUTH_TIMEOUT
            while client is None:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                msg = await _recv_json(ws, timeout=remaining)
                if msg is None:
                    await send({"type": "error", "error": "invalid_json"})
                    continue
                if msg.get("type") != "auth":
                    await send({"type": "auth_error", "reason": "auth_required"})
                    continue
                if msg.get("token"):
                    if st.auth.verify_token(msg["token"], ip):
                        client = Client(ws, ip, st.auth.device_name(msg["token"]))
                        await send({"type": "auth_ok", "server_name": settings.server_name,
                                    "device_name": client.device_name})
                    else:
                        await send({"type": "auth_error", "reason": "invalid_token"})
                    continue
                try:
                    name = str(msg.get("device_name") or "tablet")
                    token = st.auth.pair_with_pin(str(msg.get("pin", "")), ip, name)
                    client = Client(ws, ip, name)
                    await send({"type": "auth_ok", "token": token, "server_name": settings.server_name,
                                "device_name": name})
                except AuthError as e:
                    await send({"type": "auth_error", "reason": e.reason, "retry_after": e.retry_after})
        except (asyncio.TimeoutError, WebSocketDisconnect):
            try:
                await ws.close(code=4401)
            except Exception:
                pass
            return

        # ---- authenticated session
        st.hub.add(client)
        await st.hub.send(client, {"type": "telemetry", **st.telemetry.snapshot()})
        await st.hub.send(client, {"type": "mode", **st.modes.status()})
        await st.hub.send(client, {"type": "media", **st.media_state})
        await st.hub.send(client, notify_status())
        pending_tasks: set[asyncio.Task] = set()

        def spawn(coro):
            t = asyncio.create_task(coro)
            pending_tasks.add(t)
            t.add_done_callback(pending_tasks.discard)

        async def do_chat(text: str, rid):
            resp = await st.assistant.handle_text(text, "tablet")
            await st.hub.send(client, {"type": "assistant_reply", "request_id": rid, **resp})

        async def do_confirm(pid: str, approve: bool, choice, rid):
            resp = await st.assistant.confirm(pid, approve, "tablet", choice)
            await st.hub.send(client, {"type": "assistant_reply", "request_id": rid, **resp})

        async def do_set_mode(mode: str, rid):
            try:
                state = await st.modes.set_mode(mode, source="tablet")
                await st.hub.send(client, {"type": "mode", "request_id": rid, **state})
            except ValueError as exc:
                await st.hub.send(client, {"type": "error", "request_id": rid, "error": str(exc)})

        async def do_media_key(key: str, rid):
            res = await asyncio.to_thread(st.executor.media, key)
            await st.hub.send(client, {"type": "media_result", "request_id": rid, "key": key, "ok": res.ok,
                                       "message": res.message})
            if res.ok and background:
                await asyncio.sleep(0.4)  # give the player a moment, then show its new state
                await refresh_media()

        async def do_launch(target: str, rid):
            res = await asyncio.to_thread(st.executor.launch_target, target)
            await st.hub.send(client, {"type": "launch_result", "request_id": rid, "ok": res.ok,
                                       "message": res.message, "data": res.data})

        try:
            while True:
                msg = await _recv_json(ws)
                if msg is None:
                    await st.hub.send(client, {"type": "error", "error": "invalid_json"})
                    continue
                t, rid = msg.get("type"), msg.get("request_id")
                if t == "ping":
                    await st.hub.send(client, {"type": "pong", "request_id": rid})
                elif t == "chat":
                    spawn(do_chat(str(msg.get("text", "")), rid))
                elif t == "confirm":
                    spawn(do_confirm(str(msg.get("pending_id", "")), bool(msg.get("approve")), msg.get("choice"), rid))
                elif t == "launch":
                    spawn(do_launch(str(msg.get("target", "")), rid))
                elif t == "get_telemetry":
                    await st.hub.send(client, {"type": "telemetry", "request_id": rid, **st.telemetry.snapshot()})
                elif t == "get_status":
                    await st.hub.send(client, {"type": "status", "request_id": rid, **(await status_payload())})
                elif t == "get_memory":
                    await st.hub.send(client, {"type": "memory", "request_id": rid,
                                               **(st.memory.summary() if st.memory else {"enabled": False})})
                elif t == "get_mode":
                    await st.hub.send(client, {"type": "mode", "request_id": rid, **st.modes.status()})
                elif t == "set_mode":
                    spawn(do_set_mode(str(msg.get("mode", "")), rid))
                elif t == "notify_settings":
                    apps = msg.get("apps") if isinstance(msg.get("apps"), list) else []
                    client.notify = {"enabled": bool(msg.get("enabled")), "apps": [str(a) for a in apps][:100]}
                    if client.notify["enabled"] and st.notify.status == "starting" and background:
                        await st.notify.poll()   # first use: Windows asks for permission now
                    await st.hub.send(client, notify_status())
                elif t == "media_key":
                    spawn(do_media_key(str(msg.get("key", "")), rid))
                elif t == "list_apps":
                    await st.hub.send(client, {"type": "apps", "request_id": rid,
                                               "apps": st.executor.apps.search(str(msg.get("query", "")))})
                elif t == "auth":
                    await st.hub.send(client, {"type": "auth_ok", "server_name": settings.server_name,
                                               "device_name": client.device_name})
                else:
                    await st.hub.send(client, {"type": "error", "error": f"unknown message type: {t}",
                                               "request_id": rid})
        except WebSocketDisconnect:
            pass
        finally:
            st.hub.remove(ws)
            for task in pending_tasks:
                task.cancel()

    return app


async def _recv_json(ws: WebSocket, timeout: float | None = None) -> dict | None:
    raw = await (asyncio.wait_for(ws.receive_text(), timeout) if timeout else ws.receive_text())
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


if __name__ == "__main__":
    import argparse
    import threading
    import time

    import uvicorn

    from tray import Tray, port_in_use, redirect_output_to_log

    _parser = argparse.ArgumentParser(description="Kageon core server")
    _parser.add_argument("--autostart", action="store_true",
                         help="started at Windows login: waits AUTOSTART_DELAY seconds first (Wi-Fi, audio, Ollama)")
    _args = _parser.parse_args()

    _settings = get_settings()
    _log_path = None
    if _args.autostart or sys.stdout is None:          # pythonw.exe: no console window
        _log_path = _settings.data_dir / "kageon.log"
        redirect_output_to_log(_log_path)
    setup_logging(_settings.log_level)
    _server: uvicorn.Server | None = None
    _quit = threading.Event()

    def _request_quit() -> None:
        _quit.set()
        if _server is not None:
            _server.should_exit = True       # uvicorn notices within ~0.1 s and shuts down cleanly

    _tray = Tray(on_quit=_request_quit, log_path=_log_path) if _settings.tray_enabled else None
    if _tray:
        _tray.start()

    def _finish(code: int = 0) -> None:
        if _tray:
            _tray.stop()
        sys.exit(code)

    if port_in_use(_settings.port):
        log.error("Kageon is already running (port %d is in use) -- not starting a second copy", _settings.port)
        if _tray and _tray.icon:
            _tray.notify("Kageon is already running", "Look for the crescent icon near the clock.")
            time.sleep(5)                             # let the notification show before the icon goes away
        _finish(1)

    if _args.autostart and _settings.autostart_delay > 0:
        log.info("Started with Windows -- waiting %ds for Wi-Fi, audio and Ollama", _settings.autostart_delay)
        if _quit.wait(_settings.autostart_delay):      # "Quit Kageon" pressed while waiting
            _finish(0)

    _config = uvicorn.Config(create_app(_settings, on_quit=_request_quit, on_ready=_tray.ready if _tray else None),
                             host=_settings.host, port=_settings.port,
                             log_level=_settings.log_level, ws_ping_interval=20, ws_ping_timeout=20)
    _server = uvicorn.Server(_config)
    if not _quit.is_set():
        _server.run()
    print("Kageon stopped. Goodbye.")
    _finish(0)
