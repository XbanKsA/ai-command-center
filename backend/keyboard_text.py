"""Type text into the window in front, like a very fast keyboard (Windows SendInput, any language/emoji)."""
from __future__ import annotations

import logging
import sys
import time

log = logging.getLogger("keyboard")
IS_WINDOWS = sys.platform == "win32"

VK_RETURN, VK_TAB, VK_CONTROL = 0x0D, 0x09, 0x11
KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0002, 0x0004
CHUNK = 40                     # characters per burst; some apps drop keys if flooded


def _api():
    import ctypes
    from ctypes import wintypes

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = (("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", wintypes.WPARAM))

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = (("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", wintypes.WPARAM))

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = (("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD))

    class _U(ctypes.Union):
        _fields_ = (("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT))

    class INPUT(ctypes.Structure):
        _fields_ = (("type", wintypes.DWORD), ("u", _U))

    return ctypes, INPUT, KEYBDINPUT


def key_events(text: str) -> list[tuple[int, int, int]]:
    """text -> [(virtual_key, scan_code, flags)] pairs of down/up events (testable without Windows)."""
    events = []
    for ch in text.replace("\r\n", "\n"):
        if ch in "\n\t":
            vk = VK_RETURN if ch == "\n" else VK_TAB
            events += [(vk, 0, 0), (vk, 0, KEYEVENTF_KEYUP)]
            continue
        data = ch.encode("utf-16-le")                         # emoji = two UTF-16 units
        for i in range(0, len(data), 2):
            unit = int.from_bytes(data[i:i + 2], "little")
            events += [(0, unit, KEYEVENTF_UNICODE), (0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)]
    return events


def send_keys(text: str) -> None:
    ctypes, INPUT, KEYBDINPUT = _api()
    events = key_events(text)
    per_burst = CHUNK * 2
    for start in range(0, len(events), per_burst):
        batch = events[start:start + per_burst]
        arr = (INPUT * len(batch))()
        for i, (vk, scan, flags) in enumerate(batch):
            arr[i].type = 1                                   # INPUT_KEYBOARD
            arr[i].u.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
        if ctypes.windll.user32.SendInput(len(batch), arr, ctypes.sizeof(INPUT)) != len(batch):
            raise OSError("Windows blocked the typing (is an admin window in front?)")
        time.sleep(0.01)


def press_ctrl(key: str) -> None:
    import ctypes
    u = ctypes.windll.user32
    vk = ord(key.upper())
    u.keybd_event(VK_CONTROL, 0, 0, 0)
    u.keybd_event(vk, 0, 0, 0)
    u.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
    u.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def foreground_title() -> str:
    import ctypes
    u = ctypes.windll.user32
    hwnd = u.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(512)
    u.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def wait_for_window(words: list[str], timeout: float = 8.0) -> bool:
    """Wait until the window in front has one of `words` in its title (e.g. 'notepad')."""
    words = [w.lower() for w in words if w]
    end = time.time() + timeout
    while time.time() < end:
        title = foreground_title().lower()
        if any(w in title for w in words):
            return True
        time.sleep(0.15)
    return False
