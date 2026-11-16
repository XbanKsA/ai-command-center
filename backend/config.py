"""
Central configuration for the Kageon backend.

Values come from (highest priority first):
  1. Real environment variables
  2. backend/.env file (copy .env.example -> .env to customize)
  3. The defaults below
"""
from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
VERSION = "1.0.0"
SERVICE_ID = "kageon"
# Old discovery ID from before the rename - still answered so older app builds can find the PC
LEGACY_SERVICE_IDS = ("ai-command-center",)

# Wake word: our own "Hey Kageon" model, trained with openWakeWord (see models/README.md).
CUSTOM_WAKE_MODEL = BACKEND_DIR / "models" / "hey_kageon.onnx"
# Ready-made openWakeWord model used ONLY until hey_kageon.onnx exists (no built-in model exists for a new name).
FALLBACK_WAKE_MODEL = "hey_jarvis"
FALLBACK_WAKE_PHRASE = "Hey Jarvis"


def resolve_wake_model(setting: str) -> tuple[str, str, bool]:
    """WAKE_WORD_MODEL setting -> (model to load, phrase to say, is_custom_model).

    "auto" (default) = models/hey_kageon.onnx when it exists, otherwise the temporary fallback.
    Anything else = a path to an .onnx file or the name of a built-in openWakeWord model.
    """
    value = (setting or "").strip()
    if value.lower() in ("", "auto", FALLBACK_WAKE_MODEL):   # old .env files still say hey_jarvis
        if CUSTOM_WAKE_MODEL.exists():
            return str(CUSTOM_WAKE_MODEL), "Hey Kageon", True
        return FALLBACK_WAKE_MODEL, FALLBACK_WAKE_PHRASE, False
    path = Path(value)
    if not path.is_absolute():
        path = BACKEND_DIR / path
    if value.lower().endswith((".onnx", ".tflite")):
        return str(path), "Hey " + path.stem.replace("hey_", "").replace("_", " ").title(), True
    return value, value.replace("_", " ").title(), False


def _load_dotenv(path: Path) -> dict[str, str]:
    """Tiny .env parser (KEY=VALUE lines, # comments). No extra dependency needed."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


_DOTENV = _load_dotenv(BACKEND_DIR / ".env")


def _get(key: str, default: str) -> str:
    return os.environ.get(key, _DOTENV.get(key, default))


def _get_bool(key: str, default: bool) -> bool:
    return _get(key, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _get_int(key: str, default: int) -> int:
    return int(_get(key, str(default)))


def _get_float(key: str, default: float) -> float:
    return float(_get(key, str(default)))


@dataclass
class Settings:
    # --- Server ---
    host: str = field(default_factory=lambda: _get("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _get_int("PORT", 8765))
    server_name: str = field(default_factory=lambda: _get("SERVER_NAME", socket.gethostname()))
    data_dir: Path = field(default_factory=lambda: Path(_get("DATA_DIR", str(BACKEND_DIR / "data"))))
    log_level: str = field(default_factory=lambda: _get("LOG_LEVEL", "info"))

    # --- Discovery ---
    discovery_enabled: bool = field(default_factory=lambda: _get_bool("DISCOVERY_ENABLED", True))
    discovery_port: int = field(default_factory=lambda: _get_int("DISCOVERY_PORT", 37020))
    broadcast_interval: float = field(default_factory=lambda: _get_float("BROADCAST_INTERVAL", 2.0))

    # --- Auth ---
    max_pin_attempts: int = field(default_factory=lambda: _get_int("MAX_PIN_ATTEMPTS", 5))
    lockout_seconds: int = field(default_factory=lambda: _get_int("LOCKOUT_SECONDS", 60))

    # --- Telemetry ---
    telemetry_interval: float = field(default_factory=lambda: _get_float("TELEMETRY_INTERVAL", 1.5))

    # --- Local AI (Ollama) ---
    ollama_url: str = field(default_factory=lambda: _get("OLLAMA_URL", "http://127.0.0.1:11434"))
    # Two-model auto mode switching (only one is loaded at a time)
    model_normal: str = field(default_factory=lambda: _get("MODEL_NORMAL", "qwen3.5:9b"))
    model_gaming: str = field(default_factory=lambda: _get("MODEL_GAMING", "qwen3.5:4b"))
    # used if the mode's model isn't downloaded (OLLAMA_MODEL kept for older .env files)
    model_fallback: str = field(default_factory=lambda: _get("MODEL_FALLBACK", _get("OLLAMA_MODEL", "qwen2.5-coder:3b")))
    ollama_timeout: float = field(default_factory=lambda: _get_float("OLLAMA_TIMEOUT", 60.0))
    # how long Ollama keeps the model in VRAM: -1 = forever (fastest replies), or e.g. 30m
    ollama_keep_alive: str = field(default_factory=lambda: _get("OLLAMA_KEEP_ALIVE", "-1"))
    # free the model's VRAM when Kageon exits
    unload_on_exit: bool = field(default_factory=lambda: _get_bool("UNLOAD_ON_EXIT", True))
    # "thinking" makes replies smarter but much slower: off unless you say "think about it"
    think_default: bool = field(default_factory=lambda: _get_bool("THINK_DEFAULT", False))
    think_timeout: float = field(default_factory=lambda: _get_float("THINK_TIMEOUT", 180.0))

    # --- Modes: auto | gaming | normal (a manual choice is remembered until you set auto again) ---
    mode_default: str = field(default_factory=lambda: _get("MODE_DEFAULT", "auto"))
    # free VRAM is measured as if Kageon's own model were NOT loaded (so it only reacts to games/apps)
    # "auto" = based on how much VRAM the normal model really needs (measured) + VRAM_HEADROOM_GB.
    # Or set a fixed number of GB.
    vram_gaming_below_gb: str = field(default_factory=lambda: _get("VRAM_GAMING_BELOW_GB", "auto"))
    vram_normal_above_gb: str = field(default_factory=lambda: _get("VRAM_NORMAL_ABOVE_GB", "auto"))
    vram_headroom_gb: float = field(default_factory=lambda: _get_float("VRAM_HEADROOM_GB", 1.5))
    vram_hysteresis_gb: float = field(default_factory=lambda: _get_float("VRAM_HYSTERESIS_GB", 1.0))
    vram_poll_seconds: float = field(default_factory=lambda: _get_float("VRAM_POLL_SECONDS", 5.0))
    normal_after_seconds: float = field(default_factory=lambda: _get_float("NORMAL_AFTER_SECONDS", 30.0))
    # switch to gaming mode as soon as a game PROGRAM starts (Steam/Epic/Riot/... game folders)
    game_detection: bool = field(default_factory=lambda: _get_bool("GAME_DETECTION", True))
    # extra games installed elsewhere, e.g. "minecraft.exe, javaw.exe"
    game_processes: str = field(default_factory=lambda: _get("GAME_PROCESSES", ""))
    # programs in game folders that should NOT count as a game
    game_ignore: str = field(default_factory=lambda: _get("GAME_IGNORE", ""))
    announce_mode_changes: bool = field(default_factory=lambda: _get_bool("ANNOUNCE_MODE_CHANGES", True))
    announce_min_interval: float = field(default_factory=lambda: _get_float("ANNOUNCE_MIN_INTERVAL", 60.0))

    @property
    def ollama_model(self) -> str:      # backwards compatibility
        return self.model_normal

    # --- Execution ---
    # DRY_RUN=true -> Kageon only *logs* actions instead of launching/closing anything.
    dry_run: bool = field(default_factory=lambda: _get_bool("DRY_RUN", False))
    confirm_timeout: int = field(default_factory=lambda: _get_int("CONFIRM_TIMEOUT", 60))
    # understand simple commands (open/close/volume/yes/no) instantly without asking the LLM
    fast_commands: bool = field(default_factory=lambda: _get_bool("FAST_COMMANDS", True))
    # global keyboard shortcut that shuts Kageon down (blank = disabled)
    quit_hotkey: str = field(default_factory=lambda: _get("QUIT_HOTKEY", "ctrl+shift+q"))
    # crescent icon near the clock with Show PIN / Open log / Quit, plus a "Kageon is running" notification
    tray_enabled: bool = field(default_factory=lambda: _get_bool("TRAY_ENABLED", True))
    # seconds to wait after Windows login before starting (Wi-Fi, audio and Ollama need a moment)
    autostart_delay: int = field(default_factory=lambda: _get_int("AUTOSTART_DELAY", 15))

    # --- Memory (stays on this PC: data/memory.db) ---
    memory_enabled: bool = field(default_factory=lambda: _get_bool("MEMORY_ENABLED", True))
    memory_max_facts: int = field(default_factory=lambda: _get_int("MEMORY_MAX_FACTS", 20))  # facts sent per request

    # --- Media & screen ---
    play_site: str = field(default_factory=lambda: _get("PLAY_SITE", "youtube"))  # youtube | youtube music | spotify
    screen_max_side: int = field(default_factory=lambda: _get_int("SCREEN_MAX_SIDE", 1280))

    # --- Voice ---
    voice_enabled: bool = field(default_factory=lambda: _get_bool("VOICE_ENABLED", True))
    wake_word_model: str = field(default_factory=lambda: _get("WAKE_WORD_MODEL", "auto"))
    wake_threshold: float = field(default_factory=lambda: _get_float("WAKE_THRESHOLD", 0.5))
    mic_device: str = field(default_factory=lambda: _get("MIC_DEVICE", ""))  # blank = Windows default mic
    # silence (ms) after you stop talking before Kageon starts processing
    end_silence_ms: int = field(default_factory=lambda: _get_int("END_SILENCE_MS", 700))
    whisper_model: str = field(default_factory=lambda: _get("WHISPER_MODEL", "small"))
    whisper_device: str = field(default_factory=lambda: _get("WHISPER_DEVICE", "auto"))  # auto | cuda | cpu
    stt_language: str = field(default_factory=lambda: _get("STT_LANGUAGE", ""))  # blank = see ENGLISH_ONLY
    # true = always transcribe speech as English (no wrong-language guesses). false = auto-detect (EN/AR)
    english_only: bool = field(default_factory=lambda: _get_bool("ENGLISH_ONLY", True))
    tts_voice: str = field(default_factory=lambda: _get("TTS_VOICE", "en-GB-RyanNeural"))
    tts_voice_arabic: str = field(default_factory=lambda: _get("TTS_VOICE_ARABIC", "ar-SA-HamedNeural"))
    speak_responses: bool = field(default_factory=lambda: _get_bool("SPEAK_RESPONSES", True))

    @property
    def speech_language(self) -> str:
        """Language forced on Whisper: STT_LANGUAGE if set, else 'en' when ENGLISH_ONLY, else auto ('')."""
        return self.stt_language.strip() or ("en" if self.english_only else "")

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
