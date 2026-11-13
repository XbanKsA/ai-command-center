"""
Detect a running game by its program, so JARVIS can switch to gaming mode the moment a game
starts -- before it has loaded much into VRAM. (Many games, Deadlock included, size their VRAM
use to whatever is free, so VRAM alone reacts late.)

A process counts as a game if:
  * it runs from a game-library folder (Steam, Epic, Riot, EA, Ubisoft, GOG, Xbox ...), or
  * its name is listed in GAME_PROCESSES (for games installed anywhere else)
and it is not a launcher / helper / always-on tool (built-in list + GAME_IGNORE).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable, Iterable

import psutil

log = logging.getLogger("games")

# path fragments (lower-case, backslashes) of game library folders
GAME_FOLDERS = [
    r"\steamapps\common",
    r"\epic games",
    r"\riot games",
    r"\ea games",
    r"\electronic arts",
    r"\ubisoft game launcher\games",
    r"\gog galaxy\games",
    r"\gog games",
    r"\xboxgames",
    r"\battle.net\games",
    r"\rockstar games",
]

# folders INSIDE game libraries that hold launchers / background services, not games
IGNORE_FOLDERS = [
    r"\epic games\launcher",
    r"\epic games\epic online services",
    r"\epic games\epicgameslauncher",
    r"\electronic arts\ea desktop",
    r"\ea games\ea desktop",
    r"\riot games\riot client",
    r"\riot games\riot vanguard",
    r"\steamapps\common\steamworks shared",
    r"\steamapps\common\steamvr",
    r"\steamapps\common\steam controller configs",
    r"\steamapps\common\wallpaper_engine",
    r"\ubisoft game launcher\games\..",       # never matches a game; launcher itself is outside \games
]

# launchers, overlays, helpers and always-on tools that live in game folders but aren't games
DEFAULT_IGNORE = {
    "epiconlineservices.exe", "epiconlineserviceshost.exe", "eosoverlayrenderer-win64-shipping.exe",
    "eosoverlayrenderer-win32-shipping.exe", "unrealcefsubprocess.exe",
    "eacefsubprocess.exe", "eaconnect_microsoft.exe", "ealauncher.exe", "eadm.exe",
    "steam.exe", "steamwebhelper.exe", "steamservice.exe", "gameoverlayui.exe", "steamerrorreporter.exe",
    "epicgameslauncher.exe", "epicwebhelper.exe", "epiconlineservicesuserhelper.exe",
    "riotclientservices.exe", "riotclientux.exe", "riotclientuxrender.exe", "riotclientcrashhandler.exe",
    "vgc.exe", "vgtray.exe", "eadesktop.exe", "eabackgroundservice.exe", "ealocalhostsvc.exe",
    "battle.net.exe", "agent.exe", "galaxyclient.exe", "galaxyclient helper.exe", "galaxycommunication.exe",
    "upc.exe", "ubisoftconnect.exe", "uplaywebcore.exe", "rockstarservice.exe", "launcher.exe",
    "wallpaper32.exe", "wallpaper64.exe", "webwallpaper32.exe",                     # Wallpaper Engine
    "vrmonitor.exe", "vrserver.exe", "vrcompositor.exe", "vrdashboard.exe", "vrwebhelper.exe",  # SteamVR
    "unitycrashhandler64.exe", "unitycrashhandler32.exe", "crashreportclient.exe", "crashpad_handler.exe",
    "easyanticheat.exe", "easyanticheat_eos.exe", "beservice.exe", "beservice_x64.exe",
}


@dataclass
class Game:
    name: str      # friendly name, e.g. "Deadlock"
    exe: str       # e.g. "project8.exe"
    pid: int

    def __str__(self) -> str:
        return f"{self.name} ({self.exe})"


def _split(value: str) -> set[str]:
    return {p.strip().lower() for p in re.split(r"[,;]", value or "") if p.strip()}


def friendly_name(path: str, exe: str) -> str:
    """'C:\\...\\steamapps\\common\\Deadlock\\game\\bin\\win64\\project8.exe' -> 'Deadlock'."""
    low = path.replace("/", "\\").lower()
    for folder in GAME_FOLDERS:
        i = low.find(folder + "\\")
        if i >= 0:
            rest = path.replace("/", "\\")[i + len(folder) + 1:]
            first = rest.split("\\", 1)[0]
            if first:
                return first
    return exe.rsplit(".", 1)[0]


class GameDetector:
    def __init__(self, extra_processes: str = "", ignore: str = "",
                 process_iter: Callable[..., Iterable] = psutil.process_iter):
        self.extra = {p if p.endswith(".exe") else p + ".exe" for p in _split(extra_processes)}
        self.ignore = DEFAULT_IGNORE | {p if p.endswith(".exe") else p + ".exe" for p in _split(ignore)}
        self.process_iter = process_iter
        self.current: Game | None = None

    def is_game(self, name: str, exe_path: str) -> bool:
        name = (name or "").lower()
        if not name or name in self.ignore:
            return False
        if name in self.extra:
            return True
        path = (exe_path or "").replace("/", "\\").lower()
        if any(folder + "\\" in path for folder in IGNORE_FOLDERS):
            return False
        return any(folder + "\\" in path for folder in GAME_FOLDERS)

    def scan(self) -> Game | None:
        """Return a running game (or None). Logs when a game starts or stops."""
        found: Game | None = None
        for p in self.process_iter(["pid", "name", "exe"]):
            try:
                info = p.info
                name, exe = info.get("name") or "", info.get("exe") or ""
                if self.is_game(name, exe):
                    found = Game(friendly_name(exe, name) if exe else name.rsplit(".", 1)[0], name, info["pid"])
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
                continue
        if found and (not self.current or found.exe != self.current.exe):
            log.info("Game detected: %s", found)
        elif not found and self.current:
            log.info("Game closed: %s", self.current)
        self.current = found
        return found
