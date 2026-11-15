"""
Global keyboard shortcut (default Ctrl+Shift+Q) that works from any app -- uses the Windows
RegisterHotKey API directly, no extra package needed.
"""
from __future__ import annotations

import logging
import sys
import threading
from typing import Callable

log = logging.getLogger("hotkey")

MODIFIERS = {"ctrl": 0x0002, "control": 0x0002, "shift": 0x0004, "alt": 0x0001, "win": 0x0008}
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012


def parse_hotkey(spec: str) -> tuple[int, int]:
    """'ctrl+shift+q' -> (modifier flags, virtual-key code). Raises ValueError if invalid."""
    parts = [p.strip().lower() for p in (spec or "").split("+") if p.strip()]
    if not parts:
        raise ValueError("empty hotkey")
    mods, key = 0, parts[-1]
    for p in parts[:-1]:
        if p not in MODIFIERS:
            raise ValueError(f"unknown modifier '{p}'")
        mods |= MODIFIERS[p]
    if len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    elif key in ("esc", "escape"):
        vk = 0x1B
    elif key in ("pause", "break"):
        vk = 0x13
    else:
        raise ValueError(f"unsupported key '{key}'")
    if mods == 0:
        raise ValueError("a hotkey needs at least one modifier (ctrl / shift / alt / win)")
    return mods, vk


class GlobalHotkey:
    def __init__(self, spec: str, callback: Callable[[], None]):
        self.spec = spec
        self.callback = callback
        self.active = False
        self.error: str | None = None
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()

    def start(self) -> bool:
        if sys.platform != "win32":
            self.error = "global hotkeys are only supported on Windows"
            return False
        try:
            self._mods, self._vk = parse_hotkey(self.spec)
        except ValueError as exc:
            self.error = str(exc)
            log.warning("Invalid QUIT_HOTKEY '%s': %s", self.spec, exc)
            return False
        self._thread = threading.Thread(target=self._loop, name="hotkey", daemon=True)
        self._thread.start()
        self._ready.wait(2)
        return self.active

    def _loop(self) -> None:
        import ctypes
        from ctypes import wintypes
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, 1, self._mods | MOD_NOREPEAT, self._vk):
            self.error = f"{self.spec} is already used by another program"
            log.warning("Could not register hotkey %s (already in use by another app?)", self.spec)
            self._ready.set()
            return
        self.active = True
        self._ready.set()
        log.info("Global hotkey %s registered (quits Kageon)", self.spec.upper())
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    log.info("%s pressed", self.spec.upper())
                    try:
                        self.callback()
                    except Exception:
                        log.exception("hotkey callback failed")
        finally:
            user32.UnregisterHotKey(None, 1)
            self.active = False

    def stop(self) -> None:
        if self._thread_id and self.active:
            import ctypes
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
