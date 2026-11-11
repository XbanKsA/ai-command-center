import json
import socket

import pytest

from executor import AppEntry, AppIndex, Executor
from llm import LLMError


class FakeLLM:
    """Stands in for Ollama. `rules` maps a substring of the user text -> intent dict."""

    def __init__(self, rules=None, fail: str | None = None):
        self.rules = rules or {}
        self.fail = fail
        self.calls = []
        self.model = "fake"

    async def health(self):
        return {"reachable": True, "model_installed": True, "model": "fake", "models": ["fake"], "error": None}

    async def chat(self, messages, schema=None, temperature=0.2):
        self.calls.append(messages)
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
