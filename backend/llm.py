"""Async client for the local Ollama server (http://127.0.0.1:11434).

The active model can be swapped at runtime (see modes.py). `lock` is held while a request is
running, so a model swap waits for an in-flight reply instead of cutting it off.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

log = logging.getLogger("llm")


class LLMError(Exception):
    pass


def _full_name(model: str) -> str:
    return model if ":" in model else f"{model}:latest"


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: float = 60.0, keep_alive: str = "-1",
                 think_default: bool = False, think_timeout: float = 180.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.think_default = think_default
        self.think_timeout = think_timeout
        ka = str(keep_alive).strip()
        self.keep_alive = int(ka) if ka.lstrip("-").isdigit() else ka
        self.lock = asyncio.Lock()
        self._caps: dict[str, list[str]] = {}

    # ------------------------------------------------------------------ info
    async def health(self) -> dict:
        """{'reachable', 'model_installed', 'model', 'models', 'error'} for the CURRENT model."""
        try:
            models = await self.installed_models()
            return {"reachable": True, "model_installed": _full_name(self.model) in models, "model": self.model,
                    "models": models, "error": None}
        except Exception as exc:
            return {"reachable": False, "model_installed": False, "model": self.model,
                    "models": [], "error": str(exc) or exc.__class__.__name__}

    async def installed_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{self.base_url}/api/tags")
            r.raise_for_status()
            return [m.get("name", "") for m in r.json().get("models", [])]

    async def is_installed(self, model: str) -> bool:
        try:
            return _full_name(model) in await self.installed_models()
        except Exception:
            return False

    async def loaded_models(self) -> list[dict]:
        """Models currently in memory: [{'name', 'size_vram' (bytes)}]. Empty list if Ollama is down."""
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(f"{self.base_url}/api/ps")
                r.raise_for_status()
                return [{"name": m.get("name", ""), "size_vram": int(m.get("size_vram") or 0)}
                        for m in r.json().get("models", [])]
        except Exception:
            return []

    async def capabilities(self, model: str) -> list[str]:
        """e.g. ['completion', 'vision', 'thinking'] (cached). Empty if unknown."""
        if model in self._caps:
            return self._caps[model]
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(f"{self.base_url}/api/show", json={"model": model})
                r.raise_for_status()
                caps = list(r.json().get("capabilities") or [])
        except Exception:
            return []
        self._caps[model] = caps
        return caps

    # ------------------------------------------------------------------ load / unload
    async def unload(self, model: str) -> bool:
        """Free a model's VRAM right now (keep_alive=0)."""
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(f"{self.base_url}/api/generate", json={"model": model, "keep_alive": 0})
            return r.status_code < 400
        except Exception as exc:
            log.debug("unload %s failed: %s", model, exc)
            return False

    async def warm(self, model: str) -> None:
        """Load a model into VRAM with an empty request, so the first real reply is fast."""
        try:
            async with httpx.AsyncClient(timeout=max(self.timeout, 120)) as c:
                r = await c.post(f"{self.base_url}/api/generate", json={"model": model, "keep_alive": self.keep_alive})
        except httpx.ConnectError as exc:
            raise LLMError("Ollama is not running (start the Ollama app).") from exc
        except httpx.TimeoutException as exc:
            raise LLMError(f"Loading {model} took too long.") from exc
        if r.status_code == 404:
            raise LLMError(f"Model '{model}' is not installed. Run: ollama pull {model}")
        if r.status_code >= 400:
            raise LLMError(f"Ollama error {r.status_code}: {r.text[:200]}")

    # ------------------------------------------------------------------ chat
    async def chat(self, messages: list[dict], schema: dict | None = None, temperature: float = 0.2,
                   think: bool | None = None) -> str:
        """Send a chat request to the current model. Messages may include "images": [base64] for vision."""
        async with self.lock:
            return await self._chat(messages, schema, temperature, think)

    async def _chat(self, messages, schema, temperature, think) -> str:
        model = self.model
        think = self.think_default if think is None else think
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {"temperature": temperature},
        }
        if schema is not None:
            payload["format"] = schema   # Ollama structured outputs (JSON schema)
        # only send "think" to models that support it (older models reject the field)
        if "thinking" in await self.capabilities(model):
            payload["think"] = bool(think)
        timeout = self.think_timeout if think else self.timeout
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(f"{self.base_url}/api/chat", json=payload)
        except httpx.ConnectError as exc:
            raise LLMError("Ollama is not running (start the Ollama app).") from exc
        except httpx.TimeoutException as exc:
            raise LLMError("Ollama took too long to answer.") from exc
        if r.status_code == 404:
            raise LLMError(f"Model '{model}' is not installed. Run: ollama pull {model}")
        if r.status_code >= 400:
            raise LLMError(f"Ollama error {r.status_code}: {r.text[:200]}")
        return r.json().get("message", {}).get("content", "")
