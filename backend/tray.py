"""System-tray icon (Windows notification area) for Kageon.

Shows the Kageon icon (dark crescent on blue) next to the clock with a right-click menu
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

BLUE = (69, 124, 253, 255)   # Kageon blue, the app's default accent
INK = (5, 12, 30, 255)       # the dark moon
LOG_MAX_BYTES = 2 * 1024 * 1024


def make_icon_image(size: int = 64):
    """The Kageon icon: a dark crescent moon on a blue rounded square.

    Same drawing as assets/kageon.ico, the tablet app icon and the favicon. Drawn 8x bigger
    and scaled down, so the edges stay smooth even at 16 px.
    """
    from PIL import Image, ImageDraw

    big = size * 8
    u = big / 100                                    # the design is 100 units across
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, big - 1, big - 1), radius=22 * u, fill=BLUE)

    # The moon: a circle (centre 50,50, radius 27) with a bite taken out of its top right
    # (centre 69.7,30.3, radius 21) - the same shape as the app's Logo.
    moon = Image.new("L", (big, big), 0)
    m = ImageDraw.Draw(moon)
    m.ellipse(((50 - 27) * u, (50 - 27) * u, (50 + 27) * u, (50 + 27) * u), fill=255)
    m.ellipse(((69.68 - 21) * u, (30.32 - 21) * u, (69.68 + 21) * u, (30.32 + 21) * u), fill=0)
    img.paste(Image.new("RGBA", (big, big), INK), (0, 0), moon)
    return img.resize((size, size), Image.LANCZOS)


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
