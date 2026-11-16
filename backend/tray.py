"""System-tray icon (Windows notification area) for Kageon.

Shows a small crescent icon next to the clock with a right-click menu
(Show PIN / Open log / Quit Kageon) and a Windows notification when Kageon is ready.

When Kageon starts with Windows it runs with pythonw.exe: no console window that can be
closed by mistake. Everything that would have been printed (banner with the PIN, logs) goes
to data/kageon.log instead, which "Open log" opens.

pystray is optional: if it isn't installed, Kageon still runs, just without a tray icon.
"""
from __future__ import annotations

import logging
import os
import socket
import sys
import threading
from pathlib import Path
from typing import Callable

log = logging.getLogger("tray")

CYAN = (34, 211, 238, 255)
LOG_MAX_BYTES = 2 * 1024 * 1024


def make_icon_image(size: int = 64):
    """A cyan crescent moon (the "shadow" in Kageon) on a transparent background."""
    from PIL import Image, ImageDraw

    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    pad = size // 16
    draw.ellipse((pad, pad, size - pad, size - pad), fill=255)                       # full moon
    shift = size * 0.30
    draw.ellipse((pad + shift, pad - shift * 0.35, size - pad + shift, size - pad - shift * 0.35), fill=0)  # bite
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (size, size), CYAN), (0, 0), mask)
    return img


def redirect_output_to_log(path: Path):
    """No console (pythonw / autostart): send print() and logging to a file instead.

    Keeps the previous run's log as kageon.log.old once the file passes 2 MB.
    Returns the opened file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.exists() and path.stat().st_size > LOG_MAX_BYTES:
            path.replace(path.with_suffix(path.suffix + ".old"))
    except OSError:
        pass
    f = open(path, "a", encoding="utf-8", errors="replace", buffering=1)   # line-buffered
    sys.stdout = f
    sys.stderr = f
    return f


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """True if something already listens on the port (most likely another Kageon)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


class Tray:
    def __init__(self, on_quit: Callable[[], None], log_path: Path | None = None):
        self.on_quit = on_quit
        self.log_path = log_path
        self.status = "starting..."
        self.pin: str | None = None
        self.icon = None
        self.error: str | None = None

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> bool:
        if sys.platform != "win32":
            self.error = "tray icon is Windows-only"
            return False
        try:
            import pystray
        except ImportError:
            self.error = "pystray not installed (run setup.bat again)"
            log.warning("No tray icon: %s", self.error)
            return False

        item = pystray.MenuItem
        menu = pystray.Menu(
            item(lambda _: f"Kageon - {self.status}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            item("Show PIN", self._show_pin, default=True, enabled=lambda _: self.pin is not None),
            item("Open log", self._open_log, enabled=lambda _: self.log_path is not None),
            pystray.Menu.SEPARATOR,
            item("Quit Kageon", self._quit),
        )
        try:
            self.icon = pystray.Icon("kageon", make_icon_image(), "Kageon - starting...", menu)
            self.icon.run_detached()          # Windows: runs the icon in its own thread
        except Exception as exc:              # never let the tray stop the server
            self.error = str(exc)
            self.icon = None
            log.warning("No tray icon: %s", exc)
            return False
        return True

    def stop(self) -> None:
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass
            self.icon = None

    # ------------------------------------------------------------------ events
    def ready(self, info: dict) -> None:
        """Called by the server once it is up (from the server thread)."""
        self.pin = info.get("pin")
        self.set_status("running")
        lines = ["Running in the background (icon near the clock)."]
        if self.pin:
            lines.append(f"Tablet PIN: {self.pin}")
        if info.get("wake_phrase"):
            lines.append(f'Say "{info["wake_phrase"]}"')
        self.notify("Kageon is running", "\n".join(lines))

    def set_status(self, status: str) -> None:
        self.status = status
        if self.icon is not None:
            try:
                self.icon.title = f"Kageon - {status}"
                self.icon.update_menu()
            except Exception:
                pass

    def notify(self, title: str, message: str) -> None:
        if self.icon is None:
            return
        try:
            self.icon.notify(message, title)
        except Exception as exc:
            log.debug("notification failed: %s", exc)

    # ------------------------------------------------------------------ menu actions
    def _show_pin(self, *_):
        if self.pin:
            self.notify("Kageon PIN", f"Tablet pairing PIN: {self.pin}")

    def _open_log(self, *_):
        if self.log_path and self.log_path.exists():
            os.startfile(self.log_path)   # opens in Notepad (Windows only)

    def _quit(self, *_):
        self.set_status("stopping...")
        threading.Thread(target=self.on_quit, daemon=True).start()
