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
├── llm.py           Ollama client
├── executor.py      Windows actions: dynamic Start Menu app matching, URLs, media keys, power
├── voice.py         "Hey Jarvis" wake word → Whisper speech-to-text → JARVIS → edge-tts voice
├── hub.py           Connected-tablet manager
├── tools/
│   ├── check_setup.py   Pre-flight check of GPU, Ollama, apps, mic, STT and TTS
│   └── test_client.py   Tablet simulator: discovery → PIN → telemetry → chat
├── tests/           Automated test suite (pytest)
├── setup.bat / check.bat / run.bat
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

**Requirements:** Python 3.11+ ([python.org](https://www.python.org/downloads/), tick *"Add to PATH"*),
[Ollama](https://ollama.com/download), NVIDIA driver, a microphone, and an internet connection
(only for the edge-tts voice and first-time model downloads).

```bat
:: 1. Get the code
git clone https://github.com/XbanKsA/ai-command-center.git
cd ai-command-center\backend

:: 2. Pull the AI model (Ollama must be running, it starts with Windows after install)
ollama pull qwen2.5-coder:3b

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
With the server running, say **"Hey Jarvis"**, wait for the beep, then speak a command:
- "Open Notepad" / "افتح المفكرة"
- "What's my GPU usage?"
- "Turn the volume up"
- "Shut down the computer" → JARVIS asks *"Are you sure?"* → answer "no" (no wake word needed for the answer)

The server window logs every step (wake word → transcript → intent → action).

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
| | `{"type":"telemetry","cpu_percent":…,"ram_percent":…,"gpu_percent":…,"vram_percent":…,"clock":…,"system_uptime":…}` every 1.5 s |
| | `{"type":"jarvis_event",…}` when someone talks to JARVIS on the PC mic |

`jarvis_reply.status` is one of: `done`, `chat`, `needs_confirmation`, `needs_choice` (with `options`),
`needs_clarification`, `cancelled`, `failed`, `error`.

**HTTP (header `Authorization: Bearer <token>`):** `POST /api/pair`, `GET /api/status`, `GET /api/telemetry`,
`GET /api/apps?q=`, `POST /api/chat`, `POST /api/confirm`, `POST /api/launch`,
`POST /api/voice` (raw push-to-talk audio such as webm/ogg/wav, returns the transcript + JARVIS reply), `GET /api/tts?text=` (mp3).
Public: `GET /api/health`, `GET /api/discover`.

**UDP discovery (port 37020):** send `{"service":"ai-command-center","type":"probe"}` as a broadcast and the PC replies with
`{"type":"probe_reply","host":"192.168.x.x","port":8765,"name":"…"}`. It also broadcasts `"type":"announce"` every 2 s.

---

## Configuration
Copy `backend/.env.example` → `backend/.env` (`setup.bat` does this). The most useful settings:

| Setting | Default | |
|---|---|---|
| `OLLAMA_MODEL` | `qwen2.5-coder:3b` | `qwen2.5:7b` is a stronger *conversational* model and fits easily in the RTX 5070's 12 GB |
| `WAKE_THRESHOLD` | `0.5` | higher = fewer false wake-ups |
| `WHISPER_MODEL` | `small` | `medium` is more accurate (especially for Arabic) but slower |
| `WHISPER_DEVICE` | `auto` | uses the GPU only if the CUDA libraries are found, otherwise the CPU (fine for short commands). Optional GPU speech: `pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"` |
| `STT_LANGUAGE` | auto | force `ar` or `en` |
| `MIC_DEVICE` | Windows default | number from `check.bat` |
| `DRY_RUN` | `false` | `true` = log actions only |
| `VOICE_ENABLED` | `true` | |
