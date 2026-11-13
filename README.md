# AI Command Center

A two-part system:

1. **PC Core (backend)**: **JARVIS**, a voice-enabled local AI agent for Windows. It streams live
   hardware telemetry and runs commands, and it works on its own even when the tablet is off.
2. **Tablet app (frontend)**: a Stream Deck-style launcher with JARVIS chat and an OLED always-on display.
   *(Phase 2, not built yet.)*

> **Status:** Phase 1 (Python backend) is complete. The frontend starts only after the backend has been verified on the PC.

---

## Architecture (Phase 1)

```
backend/
├── main.py          FastAPI server: WebSocket /ws + HTTP API, startup banner with the PIN
├── config.py        All settings (defaults → backend/.env → environment variables)
├── auth.py          Random 4-digit PIN per start, device tokens, brute-force lockout
├── discovery.py     UDP 37020: broadcasts the PC's presence + answers discovery probes
├── telemetry.py     CPU / RAM (psutil) + NVIDIA GPU % / VRAM / temp (nvidia-ml-py), clock, uptime
├── jarvis.py        AI agent: text → structured intent (Ollama JSON schema) → safe execution
├── llm.py           Ollama client (switchable model, thinking on/off, load/unload)
├── modes.py         Auto mode switching: Normal (qwen3.5:9b) <-> Gaming (qwen3.5:4b)
├── games.py         Detects a running game by its program (Steam/Epic/Riot/... game folders)
├── memory.py        Long-term memory: facts, conversation log, routines (local SQLite file)
├── screen.py        Screenshot for "what's on my screen?" (sent only to the local model)
├── executor.py      Windows actions: dynamic Start Menu app matching, URLs, media keys, power
├── voice.py         "Hey Jarvis" wake word → Whisper speech-to-text → JARVIS → edge-tts voice
├── hub.py           Connected-tablet manager
├── tools/
│   ├── check_setup.py   Pre-flight check of GPU, Ollama, apps, mic, STT and TTS
│   └── test_client.py   Tablet simulator: discovery → PIN → telemetry → chat
├── tests/           Automated test suite (pytest)
├── hotkey.py        Global quit shortcut (Ctrl+Shift+Q)
├── setup.bat / check.bat / run.bat / gpu_voice.bat
├── startup_on.bat / startup_off.bat / autostart.bat   (start with Windows)
└── requirements.txt
```

### How JARVIS stays safe
- The LLM can only choose from a **fixed list of intents** (enforced with an Ollama JSON schema).
  Anything else is rejected.
- App names are matched **dynamically** against your Start Menu, using `Get-StartApps` plus `.lnk` shortcuts.
  There are no hardcoded paths. If a name matches several apps (e.g. "visual studio"), JARVIS
  **asks which one** instead of guessing.
- **Closing apps, sleep, shutdown and restart always need confirmation.** Critical Windows processes can never be closed.
- Commands the model is unsure about (confidence < 0.5) are confirmed before they run.
- `DRY_RUN=true` in `.env` makes JARVIS only *log* actions, which is useful for safe testing.

---

## Setup on the PC (Windows 11)

**Models:** `ollama pull qwen3.5:9b` (Normal mode) and `ollama pull qwen3.5:4b` (Gaming mode).
`qwen2.5-coder:3b` is kept as a fallback.

**Requirements:** Python 3.11+ ([python.org](https://www.python.org/downloads/), tick *"Add to PATH"*),
[Ollama](https://ollama.com/download), NVIDIA driver, a microphone, and an internet connection
(only for the edge-tts voice and first-time model downloads).

```bat
:: 1. Get the code
git clone https://github.com/XbanKsA/ai-command-center.git
cd ai-command-center\backend

:: 2. Pull the AI models (Ollama must be running, it starts with Windows after install)
ollama pull qwen3.5:9b
ollama pull qwen3.5:4b

:: 3. Install everything (creates backend\.venv)
setup.bat

:: 4. Verify the hardware, AI and voice + download the voice models
check.bat

:: 5. Start JARVIS
run.bat
```

When the server starts, it prints a banner with the **PIN ACCESS CODE**. That is the code you enter on the tablet.

**Windows Firewall:** on first start Windows asks whether Python may use the network. Click **Allow** on
**Private networks**. Your Wi-Fi must be set to *Private* (Settings → Network → Wi-Fi → your network).
If you missed the prompt, run this in an **admin** terminal:

```bat
netsh advfirewall firewall add rule name="AI Command Center TCP" dir=in action=allow protocol=TCP localport=8765 profile=private
netsh advfirewall firewall add rule name="AI Command Center UDP" dir=in action=allow protocol=UDP localport=37020 profile=private
```

### Start automatically with Windows
Run `startup_on.bat` once. From then on JARVIS starts **minimized** about 15 seconds after you log in
(the taskbar window titled *JARVIS - AI Command Center* shows the PIN and logs). `startup_off.bat` turns it off.
If Ollama is still starting up, JARVIS waits for it automatically.

### Getting updates
Inside the `ai-command-center` folder, run `git pull` (or click **Sync / Pull** in VS Code's Source Control panel), then restart JARVIS.

---

## Testing & verifying Phase 1

### 1. Automated tests (no hardware needed)
```bat
cd backend
.venv\Scripts\activate
python -m pytest -q
```
Expected result: all tests pass. They cover PIN auth and lockout, UDP discovery, telemetry, app matching,
JARVIS intent handling and confirmations, and the full WebSocket/HTTP protocol.

### 2. Pre-flight check (real hardware)
Stop the server first, then run `check.bat`. It checks:
Python and packages · RTX GPU telemetry · Ollama + model + a structured-intent test · Start Menu app scan ·
microphone list · wake-word model · Whisper on GPU/CPU · **a live mic test** (say something, it shows the transcript) ·
**a voice test** (JARVIS speaks through your speakers).

### 3. End-to-end check (server running)
Start `run.bat`, then open a **second** terminal:
```bat
cd backend
.venv\Scripts\activate
python tools\test_client.py --check
```
This acts exactly like the tablet. It finds the PC by **UDP auto-discovery**, asks for the **PIN** from the
server window, then checks the **telemetry stream**, ping, Ollama, app index, voice status, a JARVIS chat
reply, and a *shutdown request that must ask for confirmation* (it's cancelled automatically, so your PC
won't shut down).

Run it a second time: it reconnects **without the PIN**, using the saved device token.

Other modes:
```bat
python tools\test_client.py --discover     :: only test auto-discovery
python tools\test_client.py --watch        :: live telemetry for 30 s
python tools\test_client.py                :: interactive chat with JARVIS (/yes /no /apps /launch /quit)
```
**Test over Wi-Fi:** copy `tools/test_client.py` to a laptop on the same network, run `pip install websockets psutil`, then
`python test_client.py --check`. That proves discovery and pairing work across devices.

### 4. Voice test
The wake word is **"Hey Jarvis"** (openWakeWord's pre-trained `hey_jarvis` model). It also usually reacts
to "Hi Jarvis" or just "Jarvis". With the server running, say it, wait for the beep, then speak a command:
- "Open Notepad" / "افتح المفكرة"
- "What's my GPU usage?"
- "Turn the volume up"
- "Shut down the computer" → JARVIS asks *"Are you sure?"* → answer "no" (no wake word needed for the answer)

- "Open YouTube, Instagram and WhatsApp on Chrome" / "افتح يوتيوب وانستقرام في كروم"
- "Close Spotify" → "Are you sure you want to close Spotify?" → "Yes" / "Yes, close it" / "نعم"

The server window logs every step, plus a **timing line** for each command, e.g.
`Timing: you spoke 1.8s | speech-to-text 0.45s (cpu) | JARVIS 0.00s (rules) | voice 0.80s | reply started 2.0s after you stopped talking`.
That shows exactly which stage is slow.

**Quit JARVIS:** press **Ctrl+Shift+Q** from any app (change it with `QUIT_HOTKEY` in `.env`), or press Ctrl+C in the server window.

### Speed tips
- Simple commands (open / close / volume / media / yes / no) skip the AI model and run instantly ("via rules" in the log).
- `gpu_voice.bat` (optional) lets speech recognition run on the RTX GPU instead of the CPU. This is the biggest speed-up.
- `END_SILENCE_MS=500` in `.env` makes JARVIS start processing sooner after you stop talking (it may cut off slow speakers).
- `WHISPER_MODEL=base` is faster on the CPU but less accurate, especially in Arabic.

---

## AI modes: Normal / Gaming (auto switching)

| Mode | Model | VRAM | When |
|---|---|---|---|
| **Normal** | `qwen3.5:9b` | ~8–9 GB | free VRAM is plentiful |
| **Gaming** | `qwen3.5:4b` | ~4.5 GB | a game (or other app) is using the GPU |
| Fallback | `qwen2.5-coder:3b` | ~2.5 GB | only if a mode's model isn't downloaded |

Only one model is loaded at a time. On every switch, JARVIS waits for any reply in progress, **unloads** the old model,
**warm-loads** the new one, logs the switch with a timestamp, and says "Gaming mode on…" / "Back to normal mode…".
Announcements are never repeated within 60 s, and `ANNOUNCE_MODE_CHANGES=false` turns them off.

**Auto detection:** two triggers, checked every 5 s.
1. **A game program starts.** Anything running from a Steam / Epic / Riot / EA / Ubisoft / GOG / Xbox games folder
   (e.g. Deadlock's `steamapps\common\Deadlock\…\project8.exe`) switches to Gaming **immediately**, before the game
   has loaded much. Launchers, Steam itself and Wallpaper Engine are ignored. Add games installed elsewhere with
   `GAME_PROCESSES=minecraft.exe, …`, and exclude tools with `GAME_IGNORE=…`.
2. **VRAM backup:** JARVIS measures *free VRAM for others*: the GPU's free VRAM **plus** what its own model and
   Whisper use (so the 9B never pushes JARVIS into gaming mode by itself). If that drops below what the 9B really needs
   (measured, ~5.6 GB) + 1.5 GB headroom (≈ **7.1 GB**), it switches to Gaming.

Back to Normal only when **no game is running** and VRAM has stayed free for **30 s** (prevents flip-flopping).
With no NVIDIA GPU/pynvml, it relies on game detection only. You can set fixed thresholds with `VRAM_GAMING_BELOW_GB=7.5` etc.

**Manual override:** say **"gaming mode"**, **"normal mode"** or **"auto mode"** (or Arabic: "وضع الألعاب", "الوضع العادي",
"الوضع التلقائي"). A manual choice stays (even after a restart) until you say "auto mode".
Ask **"which model are you using?"** / "وش الموديل اللي تستخدمه؟" to hear the current model and mode.

**Thinking:** off by default, so voice replies are fast. Say "**think about it**", "think carefully", "deep analysis" or "فكر فيها"
to turn it on for that one request.

All settings are in `.env`: `MODEL_NORMAL`, `MODEL_GAMING`, `MODEL_FALLBACK`, `GAME_DETECTION`, `GAME_PROCESSES`,
`GAME_IGNORE`, `VRAM_GAMING_BELOW_GB` / `VRAM_NORMAL_ABOVE_GB` (`auto` or GB), `VRAM_HEADROOM_GB`, `VRAM_HYSTERESIS_GB`,
`NORMAL_AFTER_SECONDS`, `VRAM_POLL_SECONDS`, `ANNOUNCE_MODE_CHANGES`, `ANNOUNCE_MIN_INTERVAL`, `THINK_DEFAULT`,
`UNLOAD_ON_EXIT`, `ENGLISH_ONLY`.

### Test checklist for the modes
1. **Start JARVIS** (`run.bat`). The banner shows all three models `OK` and `Mode: AUTO`. The log shows
   `STARTUP: NORMAL mode … loaded qwen3.5:9b`.
2. **Ask** "Hey Jarvis, which model are you using?" → *"I'm using qwen3.5:9b, the full model, in normal mode, switching automatically."*
3. **Start a game.** Within ~5 s of launch the log shows `Game detected: Deadlock (project8.exe)` and
   `MODE SWITCH NORMAL -> GAMING … game started`, and JARVIS says *"Gaming mode on…"*. Check `ollama ps`: only `qwen3.5:4b` is loaded.
4. **Close the game.** The log shows `Game closed`, and about 30 s later `MODE SWITCH GAMING -> NORMAL` and *"Back to normal mode…"* (or a log line
   saying the announcement was skipped, if the last one was under 60 s ago).
5. **Manual override:** say "gaming mode", start no game, wait a minute: it stays in gaming mode. Restart JARVIS: still gaming.
   Say "auto mode": it goes back to normal.
6. **Tablet / API:** `python tools\test_client.py`, then `/mode`, `/mode gaming`, `/mode auto`. Each change shows `[mode] …` live.
7. **Thinking:** "Hey Jarvis, think about it: is 12 GB of VRAM enough for gaming?" The log shows `LLM (qwen3.5:…, thinking)`;
   a normal question doesn't say "thinking".
8. **Exit** with Ctrl+Shift+Q, then run `ollama ps`. Nothing is loaded (VRAM freed).

If a game isn't detected, add its `.exe` name to `GAME_PROCESSES`. If something that isn't a game keeps JARVIS in gaming
mode, the log names it (`Game detected: …`), so add it to `GAME_IGNORE`. For VRAM-based switching, compare the
`VRAM free for others: X GB` lines in the log with the thresholds.

---

## Search, play, and your screen

- **"Play bad romance by Lady Gaga"** opens the **first YouTube video** directly. Add "on YouTube Music" or
  "on Spotify" to use those instead (Spotify searches inside the app if it's installed). `PLAY_SITE` sets the default.
- **"Search for a cat video"** searches **YouTube**, because videos, songs, trailers and tutorials go to YouTube. Anything else goes to Google.
  "Search … on Amazon / GitHub / Reddit / Steam / Maps / Images" works too.
- **"What's on my screen?" / "What does this error say?"** makes JARVIS take a screenshot and ask the vision model
  (qwen3.5 can read images). The screenshot is **only sent to your local Ollama** and is never saved. It needs Pillow,
  so run `setup.bat` once after updating.

---

## Memory & routines

Everything stays on your PC in `backend/data/memory.db`, which is never uploaded to GitHub.

| Say | What happens |
|---|---|
| "Remember that my games are on the D drive" | Saved. Relevant memories are given to the AI with every question. |
| "What do you remember?" / "What do you remember about my games?" | Lists them. |
| "Forget my birthday" / "Forget that" | Deletes that memory (or the last one). |
| "Forget everything" | Asks first, then deletes all memories **and** the conversation history (routines are kept). |
| "What did we talk about yesterday?" | Every exchange is logged, so JARVIS keeps context after restarts and can look back. |
| "When I say *gaming time*, open Steam and Discord, gaming mode, and volume up" | Creates a **routine**. |
| "Gaming time" (or "run gaming time") | Runs every step. Risky steps still ask "Are you sure?". |
| "What routines do I have?" / "Delete the gaming time routine" | Lists / removes routines. |

Settings: `MEMORY_ENABLED`, `MEMORY_MAX_FACTS`.

---

## WebSocket protocol (for the tablet app)

Connect to `ws://<pc-ip>:8765/ws`. The first message must be `auth`:

| Client → server | Server → client |
|---|---|
| `{"type":"auth","pin":"1234","device_name":"Tab S9"}` | `{"type":"auth_ok","token":"…"}`. **Save the token** |
| `{"type":"auth","token":"<saved>"}` | `{"type":"auth_ok"}` or `{"type":"auth_error","reason":"invalid_token"}` |
| `{"type":"chat","text":"open spotify","request_id":"1"}` | `{"type":"jarvis_reply","request_id":"1","status":"done","reply":"…"}` |
| `{"type":"confirm","pending_id":"…","approve":true,"choice":0}` | `jarvis_reply` |
| `{"type":"launch","target":"C:\\Games\\game.exe"}` | `{"type":"launch_result","ok":true,…}` |
| `{"type":"list_apps","query":"chr"}` | `{"type":"apps","apps":[…]}` |
| `{"type":"get_status"}` / `{"type":"ping"}` | `status` / `pong` |
| `{"type":"get_memory"}` | `{"type":"memory","facts":[…],"routines":[…],"conversations":n}` |
| `{"type":"get_mode"}` | `{"type":"mode","label":"qwen3.5:4b, Gaming mode (auto)","mode":"gaming","requested":"auto",…}` |
| `{"type":"set_mode","mode":"auto"\|"gaming"\|"normal"}` | `mode` (also **pushed to every tablet on each change**, and once right after connecting) |
| | `{"type":"telemetry","cpu_percent":…,"ram_percent":…,"gpu_percent":…,"vram_percent":…,"clock":…,"system_uptime":…}` every 1.5 s |
| | `{"type":"jarvis_event",…}` when someone talks to JARVIS on the PC mic |

`jarvis_reply.status` is one of: `done`, `chat`, `needs_confirmation`, `needs_choice` (with `options`),
`needs_clarification`, `cancelled`, `failed`, `error`.

**HTTP (header `Authorization: Bearer <token>`):** `POST /api/pair`, `GET /api/status`, `GET /api/telemetry`,
`GET /api/apps?q=`, `GET /api/mode`, `POST /api/mode` (`{"mode":"gaming"}`),
`GET /api/memory` (facts + routines), `POST /api/memory/facts` (`{"text":…}`), `DELETE /api/memory/facts/{id}`,
`POST /api/routines` (`{"trigger":…,"steps":[…]}`), `DELETE /api/routines/{id}`, `POST /api/chat`, `POST /api/confirm`, `POST /api/launch`,
`POST /api/voice` (raw push-to-talk audio such as webm/ogg/wav, returns the transcript + JARVIS reply), `GET /api/tts?text=` (mp3).
Public: `GET /api/health`, `GET /api/discover`.

**UDP discovery (port 37020):** send `{"service":"ai-command-center","type":"probe"}` as a broadcast and the PC replies with
`{"type":"probe_reply","host":"192.168.x.x","port":8765,"name":"…"}`. It also broadcasts `"type":"announce"` every 2 s.

---

## Configuration
Copy `backend/.env.example` → `backend/.env` (`setup.bat` does this). The most useful settings:

| Setting | Default | |
|---|---|---|
| `MODEL_NORMAL` / `MODEL_GAMING` | `qwen3.5:9b` / `qwen3.5:4b` | see *AI modes* above |
| `GAME_DETECTION` / `GAME_PROCESSES` | `true` / empty | switch to gaming mode when a game program starts |
| `VRAM_GAMING_BELOW_GB` / `VRAM_NORMAL_ABOVE_GB` | `auto` | VRAM backup thresholds (auto = from the 9B's real size) |
| `ENGLISH_ONLY` | `true` | always understand speech as English |
| `WAKE_THRESHOLD` | `0.5` | higher = fewer false wake-ups |
| `WHISPER_MODEL` | `small` | `medium` is more accurate (especially for Arabic) but slower |
| `WHISPER_DEVICE` | `auto` | uses the GPU only if the CUDA libraries are found, otherwise the CPU (fine for short commands). Optional GPU speech: `pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"` |
| `STT_LANGUAGE` | auto | force `ar` or `en` |
| `MIC_DEVICE` | Windows default | number from `check.bat` |
| `DRY_RUN` | `false` | `true` = log actions only |
| `QUIT_HOTKEY` | `ctrl+shift+q` | global shortcut to shut JARVIS down |
| `END_SILENCE_MS` | `700` | silence needed before JARVIS processes your command |
| `FAST_COMMANDS` | `true` | instant local handling of simple commands |
| `OLLAMA_KEEP_ALIVE` | `-1` | keep the model loaded in VRAM forever (no reload delay) |
| `VOICE_ENABLED` | `true` | |
