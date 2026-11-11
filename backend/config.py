"""
Central configuration for the AI Command Center backend.

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
SERVICE_ID = "ai-command-center"


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
    ollama_model: str = field(default_factory=lambda: _get("OLLAMA_MODEL", "qwen2.5-coder:3b"))
    ollama_timeout: float = field(default_factory=lambda: _get_float("OLLAMA_TIMEOUT", 60.0))

    # --- Execution ---
    # DRY_RUN=true -> JARVIS only *logs* actions instead of launching/closing anything.
    dry_run: bool = field(default_factory=lambda: _get_bool("DRY_RUN", False))
    confirm_timeout: int = field(default_factory=lambda: _get_int("CONFIRM_TIMEOUT", 60))

    # --- Voice ---
    voice_enabled: bool = field(default_factory=lambda: _get_bool("VOICE_ENABLED", True))
    wake_word_model: str = field(default_factory=lambda: _get("WAKE_WORD_MODEL", "hey_jarvis"))
    wake_threshold: float = field(default_factory=lambda: _get_float("WAKE_THRESHOLD", 0.5))
    mic_device: str = field(default_factory=lambda: _get("MIC_DEVICE", ""))  # blank = Windows default mic
    whisper_model: str = field(default_factory=lambda: _get("WHISPER_MODEL", "small"))
    whisper_device: str = field(default_factory=lambda: _get("WHISPER_DEVICE", "auto"))  # auto | cuda | cpu
    stt_language: str = field(default_factory=lambda: _get("STT_LANGUAGE", ""))  # blank = auto-detect
    tts_voice: str = field(default_factory=lambda: _get("TTS_VOICE", "en-GB-RyanNeural"))
    tts_voice_arabic: str = field(default_factory=lambda: _get("TTS_VOICE_ARABIC", "ar-SA-HamedNeural"))
    speak_responses: bool = field(default_factory=lambda: _get_bool("SPEAK_RESPONSES", True))

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
