"""Tracks authenticated WebSocket clients and pushes messages to them safely."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field

from fastapi import WebSocket

log = logging.getLogger("hub")


@dataclass
class Client:
    ws: WebSocket
    ip: str
    device_name: str
    connected_at: float = field(default_factory=time.time)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    notify: dict | None = None  # this tablet's PC-notification choice: {"enabled": bool, "apps": [names]}


class Hub:
    def __init__(self):
        self.clients: dict[int, Client] = {}

    def add(self, client: Client) -> None:
        self.clients[id(client.ws)] = client
        log.info("Tablet connected: %s (%s) -- %d client(s)", client.device_name, client.ip, len(self.clients))

    def remove(self, ws: WebSocket) -> None:
        c = self.clients.pop(id(ws), None)
        if c:
            log.info("Tablet disconnected: %s (%s) -- %d client(s)", c.device_name, c.ip, len(self.clients))

    async def send(self, client: Client, message: dict) -> bool:
        try:
            async with client.lock:
                await client.ws.send_text(json.dumps(message, ensure_ascii=False, default=str))
            return True
        except Exception:
            self.remove(client.ws)
            return False

    async def broadcast(self, message: dict) -> None:
        for c in list(self.clients.values()):
            await self.send(c, message)

    def summary(self) -> list[dict]:
        return [{"device_name": c.device_name, "ip": c.ip, "connected_at": c.connected_at}
                for c in self.clients.values()]
