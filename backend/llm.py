"""Minimal async client for the local Ollama server (http://127.0.0.1:11434)."""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger("llm")


class LLMError(Exception):
    pass


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: float = 60.0, keep_alive: str = "-1"):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        ka = str(keep_alive).strip()
        self.keep_alive = int(ka) if ka.lstrip("-").isdigit() else ka

    async def health(self) -> dict:
        """{'reachable': bool, 'model_installed': bool, 'models': [...], 'error': str|None}"""
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(f"{self.base_url}/api/tags")
                r.raise_for_status()
                models = [m.get("name", "") for m in r.json().get("models", [])]
            wanted = self.model if ":" in self.model else f"{self.model}:latest"
            return {"reachable": True, "model_installed": wanted in models, "model": self.model,
                    "models": models, "error": None}
        except Exception as exc:
            return {"reachable": False, "model_installed": False, "model": self.model,
                    "models": [], "error": str(exc) or exc.__class__.__name__}

    async def chat(self, messages: list[dict], schema: dict | None = None, temperature: float = 0.2) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {"temperature": temperature},
        }
        if schema is not None:
            payload["format"] = schema   # Ollama structured outputs (JSON schema)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.post(f"{self.base_url}/api/chat", json=payload)
        except httpx.ConnectError as exc:
            raise LLMError("Ollama is not running (start the Ollama app).") from exc
        except httpx.TimeoutException as exc:
            raise LLMError("Ollama took too long to answer.") from exc
        if r.status_code == 404:
            raise LLMError(f"Model '{self.model}' is not installed. Run: ollama pull {self.model}")
        if r.status_code >= 400:
            raise LLMError(f"Ollama error {r.status_code}: {r.text[:200]}")
        return r.json().get("message", {}).get("content", "")
