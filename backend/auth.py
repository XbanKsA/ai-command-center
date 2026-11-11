"""
PIN pairing + device tokens.

Flow:
  1. On startup a random 4-digit PIN is generated and printed in the terminal.
  2. The tablet sends the PIN once -> receives a long random device token.
  3. The tablet stores the token and uses it for every later connection,
     so it stays paired even after the server restarts (new PIN each start).

Security:
  - PIN comparison is constant-time.
  - After MAX_PIN_ATTEMPTS wrong PINs, that IP is locked out for LOCKOUT_SECONDS
    (a 4-digit PIN would otherwise be brute-forceable).
  - Only SHA-256 hashes of tokens are written to disk.
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("auth")


class AuthError(Exception):
    def __init__(self, reason: str, retry_after: int = 0):
        super().__init__(reason)
        self.reason = reason
        self.retry_after = retry_after


@dataclass
class _Attempts:
    count: int = 0
    locked_until: float = 0.0


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AuthManager:
    def __init__(self, data_dir: Path, max_attempts: int = 5, lockout_seconds: int = 60,
                 pin: str | None = None):
        self.pin = pin or f"{secrets.randbelow(10_000):04d}"
        self.max_attempts = max_attempts
        self.lockout_seconds = lockout_seconds
        self._file = Path(data_dir) / "paired_devices.json"
        self._lock = threading.Lock()
        self._attempts: dict[str, _Attempts] = {}
        self._devices: dict[str, dict] = self._load()

    # ---------- persistence ----------
    def _load(self) -> dict[str, dict]:
        try:
            if self._file.exists():
                return json.loads(self._file.read_text(encoding="utf-8"))
        except Exception as exc:  # corrupted file -> start fresh, don't crash
            log.warning("Could not read %s (%s); starting with no paired devices", self._file, exc)
        return {}

    def _save(self) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._devices, indent=2), encoding="utf-8")
        tmp.replace(self._file)

    # ---------- PIN pairing ----------
    def pair_with_pin(self, pin: str, client_ip: str, device_name: str = "tablet") -> str:
        """Validate the PIN and return a new device token. Raises AuthError."""
        now = time.time()
        with self._lock:
            att = self._attempts.setdefault(client_ip, _Attempts())
            if att.locked_until > now:
                raise AuthError("locked_out", retry_after=int(att.locked_until - now) + 1)

            pin = str(pin or "").strip()
            if not secrets.compare_digest(pin, self.pin):
                att.count += 1
                remaining = self.max_attempts - att.count
                if remaining <= 0:
                    att.locked_until = now + self.lockout_seconds
                    att.count = 0
                    log.warning("Too many wrong PINs from %s -> locked for %ss", client_ip, self.lockout_seconds)
                    raise AuthError("locked_out", retry_after=self.lockout_seconds)
                log.info("Wrong PIN from %s (%d attempts left)", client_ip, remaining)
                raise AuthError("invalid_pin")

            # success
            self._attempts.pop(client_ip, None)
            token = secrets.token_urlsafe(32)
            self._devices[_hash(token)] = {
                "device_name": (device_name or "tablet")[:64],
                "paired_at": now,
                "last_seen": now,
                "last_ip": client_ip,
            }
            self._save()
            log.info("Device '%s' paired from %s", device_name, client_ip)
            return token

    # ---------- token auth ----------
    def verify_token(self, token: str | None, client_ip: str | None = None) -> bool:
        if not token:
            return False
        key = _hash(token)
        with self._lock:
            dev = self._devices.get(key)
            if not dev:
                return False
            dev["last_seen"] = time.time()
            if client_ip:
                dev["last_ip"] = client_ip
            return True

    def device_name(self, token: str) -> str:
        dev = self._devices.get(_hash(token or ""))
        return dev["device_name"] if dev else "unknown"

    def revoke_all(self) -> int:
        with self._lock:
            n = len(self._devices)
            self._devices = {}
            self._save()
            return n

    def paired_devices(self) -> list[dict]:
        return [dict(v) for v in self._devices.values()]
