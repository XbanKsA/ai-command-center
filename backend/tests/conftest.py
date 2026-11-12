import json
import socket

import pytest

from executor import AppEntry, AppIndex, Executor
from llm import LLMError


class FakeLLM:
    """Stands in for Ollama. `rules` maps a substring of the user text -> intent dict.
    Also simulates installed / loaded models and their VRAM use for mode-switching tests."""

    SIZES = {"qwen3.5:9b": 8.5, "qwen3.5:4b": 4.5, "qwen2.5-coder:3b": 2.5}   # GB of VRAM when loaded

    def __init__(self, rules=None, fail: str | None = None,
                 installed=("qwen3.5:9b", "qwen3.5:4b", "qwen2.5-coder:3b"), reachable: bool = True):
        import asyncio
        self.rules = rules or {}
        self.fail = fail
        self.calls = []
        self.thinks = []
        self.model = "qwen3.5:9b"
        self.installed = list(installed)
        self.reachable = reachable
        self.loaded: dict[str, float] = {}
        self.events: list[str] = []
        self.lock = asyncio.Lock()

    async def health(self):
        return {"reachable": self.reachable, "model_installed": self.model in self.installed, "model": self.model,
                "models": list(self.installed), "error": None}

    async def installed_models(self):
        if not self.reachable:
            raise ConnectionError("down")
        return list(self.installed)

    async def is_installed(self, model):
        return self.reachable and model in self.installed

    async def loaded_models(self):
        return [{"name": m, "size_vram": int(gb * 1024 ** 3)} for m, gb in self.loaded.items()]

    async def unload(self, model):
        self.events.append(f"unload {model}")
        self.loaded.pop(model, None)
        return True

    async def warm(self, model):
        if model not in self.installed:
            raise LLMError(f"Model '{model}' is not installed. Run: ollama pull {model}")
        self.events.append(f"load {model}")
        self.loaded[model] = self.SIZES.get(model, 3.0)

    async def capabilities(self, model):
        return ["completion", "vision", "thinking"] if model.startswith("qwen3") else ["completion"]

    async def chat(self, messages, schema=None, temperature=0.2, think=None):
        self.calls.append(messages)
        self.thinks.append(think)
        if self.fail:
            raise LLMError(self.fail)
        text = messages[-1]["content"].lower()
        for key, value in self.rules.items():
            if key in text:
                return value if isinstance(value, str) else json.dumps(value)
        return json.dumps({"intent": "chat", "target": "", "reply": "Hello!", "confidence": 0.9})


FAKE_APPS = [
    AppEntry("Google Chrome", "startapp", "Chrome"),
    AppEntry("Spotify", "startapp", "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"),
    AppEntry("Visual Studio Code", "startapp", "Microsoft.VisualStudioCode"),
    AppEntry("Visual Studio 2022", "startapp", "VisualStudio.2022"),
    AppEntry("Uninstall Spotify", "shortcut", r"C:\x\Uninstall Spotify.lnk"),
    AppEntry("Steam", "shortcut", r"C:\x\Steam.lnk"),
    AppEntry("Notepad", "builtin", "notepad.exe"),
    AppEntry("Notepad++", "shortcut", r"C:\x\Notepad++.lnk"),
    AppEntry("Discord", "shortcut", r"C:\x\Discord.lnk"),
]


@pytest.fixture
def fake_index():
    idx = AppIndex()
    idx.entries = list(FAKE_APPS)
    idx.last_refresh = 1e12  # never stale
    return idx


@pytest.fixture
def dry_executor(fake_index):
    return Executor(dry_run=True, app_index=fake_index)


@pytest.fixture
def free_udp_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port
