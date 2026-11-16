"""
Windows action executor -- no hardcoded app paths.

App discovery is dynamic:
  * `Get-StartApps` (PowerShell)  -> every app in the Start Menu, including Store/UWP apps,
                                     launched through `shell:AppsFolder\\<AppID>`
  * Start Menu + Desktop shortcuts (.lnk / .url / .appref-ms) -> launched with os.startfile

Names are fuzzy-matched. If the best match isn't clearly ahead of the others, the
executor reports the request as AMBIGUOUS and returns the candidates instead of guessing.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

import psutil

from files import FileManager

log = logging.getLogger("executor")
IS_WINDOWS = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000

# ----------------------------------------------------------------- data types


@dataclass
class AppEntry:
    name: str
    kind: str          # "startapp" | "shortcut" | "builtin"
    target: str        # AppID, shortcut path, or command
    norm: str = ""

    def __post_init__(self):
        self.norm = normalize(self.name)

    def to_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind, "target": self.target}


@dataclass
class ActionResult:
    ok: bool
    message: str
    data: dict = field(default_factory=dict)


@dataclass
class MatchResult:
    status: str                     # "match" | "ambiguous" | "none"
    best: AppEntry | None = None
    candidates: list[tuple[AppEntry, float]] = field(default_factory=list)


# ----------------------------------------------------------------- matching

_NOISE_WORDS = ("uninstall", "help", "readme", "read me", "manual", "documentation", "release notes",
                "website", "support", "license", "changelog", "what's new", "debug", "safe mode")

ALIASES = {
    "chrome": "google chrome", "google": "google chrome",
    "edge": "microsoft edge", "browser": "microsoft edge",
    "vscode": "visual studio code", "vs code": "visual studio code", "code": "visual studio code",
    "explorer": "file explorer", "files": "file explorer", "file manager": "file explorer",
    "my files": "file explorer",
    "cmd": "command prompt", "command line": "command prompt",
    "calc": "calculator", "task manager": "task manager", "taskmgr": "task manager",
    "word": "word", "excel": "excel", "powerpoint": "powerpoint", "outlook": "outlook",
    "control panel": "control panel", "settings": "settings",
    "كروم": "google chrome", "الحاسبة": "calculator", "حاسبة": "calculator", "المتصفح": "microsoft edge",
    "الاعدادات": "settings", "الإعدادات": "settings", "المفكرة": "notepad", "ستيم": "steam",
    "سبوتيفاي": "spotify", "ديسكورد": "discord", "يوتيوب": "youtube",
}


def normalize(text: str) -> str:
    text = (text or "").lower().replace("&", " and ")
    text = re.sub(r"[^\w\s+]", " ", text)     # \w keeps Arabic letters; keep + (Notepad++)
    return re.sub(r"\s+", " ", text).strip()


def _score(query: str, name: str) -> float:
    if not query or not name:
        return 0.0
    if query == name:
        s = 1.0
    elif len(query) >= 3 and (name.startswith(query + " ") or name.startswith(query)):
        s = 0.9
    elif set(query.split()) <= set(name.split()):
        s = 0.85
    elif len(query) >= 3 and query in name:
        s = 0.75
    else:
        s = SequenceMatcher(None, query, name).ratio() * 0.8
    if any(w in name for w in _NOISE_WORDS) and not any(w in query for w in _NOISE_WORDS):
        s -= 0.4
    return max(s, 0.0)


def match_app(query: str, entries: list[AppEntry], min_score: float = 0.5,
              accept_score: float = 0.85, margin: float = 0.08) -> MatchResult:
    q = normalize(query)
    if not q:
        return MatchResult("none")
    queries = {q}
    if q in ALIASES:
        queries.add(normalize(ALIASES[q]))
    scored: dict[str, tuple[AppEntry, float]] = {}
    for e in entries:
        s = max(_score(qq, e.norm) for qq in queries)
        if s >= min_score and (e.norm not in scored or s > scored[e.norm][1]):
            scored[e.norm] = (e, s)
    ranked = sorted(scored.values(), key=lambda t: (-t[1], len(t[0].name)))
    if not ranked:
        return MatchResult("none")
    best, best_s = ranked[0]
    second_s = ranked[1][1] if len(ranked) > 1 else 0.0
    if best_s >= accept_score and (best_s == 1.0 or best_s - second_s >= margin):
        return MatchResult("match", best, ranked[:5])
    return MatchResult("ambiguous", None, ranked[:5])


# ----------------------------------------------------------------- app index

BUILTIN_APPS = [
    AppEntry("Notepad", "builtin", "notepad.exe"),
    AppEntry("Calculator", "builtin", "calc.exe"),
    AppEntry("Command Prompt", "builtin", "cmd.exe"),
    AppEntry("File Explorer", "builtin", "explorer.exe"),
    AppEntry("Task Manager", "builtin", "taskmgr.exe"),
    AppEntry("Control Panel", "builtin", "control.exe"),
    AppEntry("Settings", "builtin", "ms-settings:"),
]


def _shortcut_dirs() -> list[Path]:
    env = os.environ
    dirs = [
        Path(env.get("PROGRAMDATA", r"C:\ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
        Path(env.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        Path(env.get("USERPROFILE", "")) / "Desktop",
        Path(env.get("PUBLIC", r"C:\Users\Public")) / "Desktop",
    ]
    onedrive = env.get("OneDrive")
    if onedrive:
        dirs.append(Path(onedrive) / "Desktop")
    return [d for d in dirs if str(d) and d.exists()]


def scan_shortcuts() -> list[AppEntry]:
    out = []
    for d in _shortcut_dirs():
        for ext in ("*.lnk", "*.url", "*.appref-ms"):
            for p in d.rglob(ext):
                out.append(AppEntry(p.stem, "shortcut", str(p)))
    return out


def scan_start_apps() -> list[AppEntry]:
    """All Start Menu apps (desktop + Store) via PowerShell Get-StartApps."""
    cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
           "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"]
    res = subprocess.run(cmd, capture_output=True, timeout=30, creationflags=CREATE_NO_WINDOW)
    raw = res.stdout.decode("utf-8", errors="replace").strip()
    if not raw:
        return []
    data = json.loads(raw)
    if isinstance(data, dict):
        data = [data]
    return [AppEntry(d["Name"], "startapp", d["AppID"]) for d in data if d.get("Name") and d.get("AppID")]


class AppIndex:
    def __init__(self):
        self.entries: list[AppEntry] = list(BUILTIN_APPS)
        self.last_refresh = 0.0
        self.errors: list[str] = []
        self._lock = threading.Lock()

    def refresh(self) -> int:
        if not IS_WINDOWS:
            return len(self.entries)
        entries: list[AppEntry] = []
        errors = []
        for scanner in (scan_start_apps, scan_shortcuts):
            try:
                entries.extend(scanner())
            except Exception as exc:
                errors.append(f"{scanner.__name__}: {exc}")
                log.warning("App scan %s failed: %s", scanner.__name__, exc)
        entries.extend(BUILTIN_APPS)
        with self._lock:
            self.entries = entries
            self.errors = errors
            self.last_refresh = time.time()
        log.info("App index refreshed: %d entries", len(entries))
        return len(entries)

    def refresh_if_stale(self, max_age: float = 600) -> None:
        if time.time() - self.last_refresh > max_age:
            self.refresh()

    def match(self, query: str) -> MatchResult:
        with self._lock:
            entries = list(self.entries)
        return match_app(query, entries)

    def search(self, query: str, limit: int = 20) -> list[dict]:
        with self._lock:
            entries = list(self.entries)
        if not query:
            seen, out = set(), []
            for e in sorted(entries, key=lambda e: e.norm):
                if e.norm not in seen:
                    seen.add(e.norm)
                    out.append(e.to_dict())
            return out[:limit]
        res = match_app(query, entries, min_score=0.3, accept_score=2.0)
        return [dict(e.to_dict(), score=round(s, 2)) for e, s in res.candidates][:limit]


# ----------------------------------------------------------------- websites & browsers

# Well-known sites: spoken name -> (display name, url). Anything else that looks like a domain also works.
SITES: dict[str, tuple[str, str]] = {}
for _names, _display, _url in [
    (["youtube", "you tube", "يوتيوب", "اليوتيوب"], "YouTube", "https://www.youtube.com"),
    (["instagram", "insta", "انستقرام", "انستغرام", "إنستغرام", "انستا"], "Instagram", "https://www.instagram.com"),
    (["whatsapp", "whatsapp web", "whats app", "واتساب", "واتس اب", "الواتس"], "WhatsApp", "https://web.whatsapp.com"),
    (["twitter", "x", "تويتر", "اكس"], "X", "https://x.com"),
    (["facebook", "فيسبوك", "فيس بوك"], "Facebook", "https://www.facebook.com"),
    (["tiktok", "tik tok", "تيك توك"], "TikTok", "https://www.tiktok.com"),
    (["snapchat", "snap", "سناب", "سناب شات"], "Snapchat", "https://web.snapchat.com"),
    (["netflix", "نتفلكس", "نتفليكس"], "Netflix", "https://www.netflix.com"),
    (["gmail", "جيميل", "قوقل ميل"], "Gmail", "https://mail.google.com"),
    (["google", "قوقل", "جوجل"], "Google", "https://www.google.com"),
    (["chatgpt", "chat gpt", "شات جي بي تي"], "ChatGPT", "https://chatgpt.com"),
    (["claude", "كلود"], "Claude", "https://claude.ai"),
    (["github", "جيت هب"], "GitHub", "https://github.com"),
    (["reddit", "ريديت"], "Reddit", "https://www.reddit.com"),
    (["twitch", "تويتش"], "Twitch", "https://www.twitch.tv"),
    (["linkedin", "لينكد ان"], "LinkedIn", "https://www.linkedin.com"),
    (["amazon", "امازون"], "Amazon", "https://www.amazon.sa"),
    (["google maps", "maps", "خرائط قوقل"], "Google Maps", "https://maps.google.com"),
    (["google drive", "drive", "قوقل درايف"], "Google Drive", "https://drive.google.com"),
    (["spotify web"], "Spotify", "https://open.spotify.com"),
]:
    for _n in _names:
        SITES[_n] = (_display, _url)

# Spoken browser name -> executable name (looked up dynamically in the Windows registry "App Paths")
BROWSERS = {
    "chrome": "chrome.exe", "google chrome": "chrome.exe", "كروم": "chrome.exe", "قوقل كروم": "chrome.exe",
    "edge": "msedge.exe", "microsoft edge": "msedge.exe", "ايدج": "msedge.exe",
    "firefox": "firefox.exe", "فايرفوكس": "firefox.exe",
    "brave": "brave.exe", "opera": "opera.exe", "opera gx": "opera.exe",
}


def resolve_site(name: str) -> tuple[str, str] | None:
    """'youtube' -> ('YouTube', 'https://www.youtube.com'); 'example.com' -> ('example.com', 'https://example.com')."""
    n = normalize(name)
    for prefix in ("the ", "موقع ", "website ", "site "):
        if n.startswith(prefix):
            n = n[len(prefix):]
    for suffix in (" website", " site", " web", " dot com"):
        if n.endswith(suffix) and n[: -len(suffix)] in SITES:
            n = n[: -len(suffix)]
    if n in SITES:
        return SITES[n]
    url = Executor.normalize_url((name or "").strip())
    if url and re.search(r"\.[a-z]{2,}(/|$)", url.split("://", 1)[1], re.I):
        return (urllib.parse.urlparse(url).netloc, url)
    return None


def resolve_browser(name: str) -> str | None:
    """Spoken browser name -> exe file name, or None."""
    return BROWSERS.get(normalize(name)) if name else None


def find_browser_path(exe: str) -> str | None:
    """Find a browser's real install path via the registry (works wherever it is installed)."""
    if not IS_WINDOWS or not exe:
        return None
    import winreg
    key_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, key_path) as k:
                path = winreg.QueryValue(k, None)
                if path and Path(path.strip('"')).exists():
                    return path.strip('"')
        except OSError:
            continue
    return None


# ----------------------------------------------------------------- site search / play

SEARCH_SITES = {
    "google": ("Google", "https://www.google.com/search?q={q}"),
    "youtube": ("YouTube", "https://www.youtube.com/results?search_query={q}"),
    "youtube music": ("YouTube Music", "https://music.youtube.com/search?q={q}"),
    "spotify": ("Spotify", "https://open.spotify.com/search/{q}"),
    "amazon": ("Amazon", "https://www.amazon.sa/s?k={q}"),
    "github": ("GitHub", "https://github.com/search?q={q}"),
    "reddit": ("Reddit", "https://www.reddit.com/search/?q={q}"),
    "twitch": ("Twitch", "https://www.twitch.tv/search?term={q}"),
    "wikipedia": ("Wikipedia", "https://en.wikipedia.org/w/index.php?search={q}"),
    "steam": ("Steam store", "https://store.steampowered.com/search/?term={q}"),
    "maps": ("Google Maps", "https://www.google.com/maps/search/{q}"),
    "images": ("Google Images", "https://www.google.com/search?tbm=isch&q={q}"),
    "x": ("X", "https://x.com/search?q={q}"),
}
_SITE_ALIASES = {
    "yt": "youtube", "you tube": "youtube", "youtube music": "youtube music", "yt music": "youtube music",
    "music": "youtube music", "google maps": "maps", "twitter": "x", "steam store": "steam",
    "google images": "images", "the web": "google", "web": "google", "internet": "google", "": "google",
}


def resolve_search_site(site: str) -> str:
    n = normalize(site or "")
    n = _SITE_ALIASES.get(n, n)
    return n if n in SEARCH_SITES else "google"


def find_youtube_video(query: str, timeout: float = 6.0) -> str | None:
    """ID of the first YouTube search result (no API key needed). None if it can't be found."""
    import httpx
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                             "Chrome/124.0 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}
    try:
        r = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
        m = re.search(r'"videoRenderer":\{"videoId":"([A-Za-z0-9_-]{11})"', r.text) or \
            re.search(r'"videoId":"([A-Za-z0-9_-]{11})"', r.text)
        return m.group(1) if m else None
    except Exception as exc:
        log.debug("YouTube lookup failed: %s", exc)
        return None


# ----------------------------------------------------------------- executor

PROTECTED_PROCESSES = {
    "system", "idle", "registry", "smss", "csrss", "wininit", "winlogon", "services", "lsass",
    "svchost", "dwm", "explorer", "fontdrvhost", "sihost", "ctfmon", "conhost", "runtimebroker",
    "searchhost", "startmenuexperiencehost", "shellexperiencehost", "audiodg", "ollama",
    "ollama app", "python", "pythonw", "py", "memcompression", "securityhealthservice", "msmpeng",
}

MEDIA_KEYS = {
    "play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2,
    "mute": 0xAD, "volume_down": 0xAE, "volume_up": 0xAF,
}


class Executor:
    def __init__(self, dry_run: bool = False, app_index: AppIndex | None = None, play_site: str = "youtube",
                 files: FileManager | None = None):
        self.dry_run = dry_run
        self.files = files or FileManager(dry_run=dry_run)
        self.play_site = play_site
        self.apps = app_index or AppIndex()

    # ---- helpers
    def _run(self, description: str, fn) -> ActionResult:
        if self.dry_run:
            log.info("[DRY RUN] %s", description)
            return ActionResult(True, f"[dry run] {description}", {"dry_run": True})
        if not IS_WINDOWS:
            return ActionResult(False, "This action only works on Windows.")
        try:
            fn()
            log.info("Executed: %s", description)
            return ActionResult(True, description)
        except Exception as exc:
            log.exception("Action failed: %s", description)
            return ActionResult(False, f"Failed to {description[0].lower()}{description[1:]}: {exc}")

    # ---- apps
    @staticmethod
    def _launch(entry: AppEntry) -> None:
        if entry.kind == "startapp":
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{entry.target}"])
        elif entry.kind == "builtin" and entry.target.endswith(":"):
            os.startfile(entry.target)
        elif entry.kind == "builtin":
            subprocess.Popen([entry.target])
        else:
            os.startfile(entry.target)

    def launch_entry(self, entry: AppEntry) -> ActionResult:
        res = self._run(f"Opening {entry.name}", lambda: self._launch(entry))
        res.data.update({"app": entry.to_dict()})
        return res

    # ---- files and typing
    def open_path(self, path: Path) -> ActionResult:
        res = self._run(f"Opening {path.name}", lambda: os.startfile(str(path)))
        res.data.update({"path": str(path)})
        return res

    def show_in_folder(self, path: Path) -> ActionResult:
        return self._run(f"Showing {path.name} in its folder",
                         lambda: subprocess.Popen(["explorer.exe", "/select,", str(path)]))

    def type_text(self, text: str, app: AppEntry | None = None) -> ActionResult:
        """Type into the window in front, or first open `app` (e.g. Notepad) and type there."""
        def go():
            from keyboard_text import press_ctrl, send_keys, wait_for_window
            if app:
                self._launch(app)
                words = [w for w in app.norm.split() if len(w) > 2] or [app.norm]
                if not wait_for_window(words):
                    raise RuntimeError(f"{app.name} didn't come to the front, so I didn't type anything")
                time.sleep(0.5)
                if "notepad" in app.norm:
                    press_ctrl("n")                    # fresh tab, never into an old document
                    time.sleep(0.4)
            send_keys(text)
        return self._run(f"Type the text{f' in {app.name}' if app else ''}", go)

    def launch_target(self, target: str) -> ActionResult:
        """Launch something explicitly chosen by the user (tablet launcher slot):
        an .exe/.lnk/file path, a URL, a shell: / ms-settings: URI, or an app name."""
        t = (target or "").strip().strip('"')
        if not t:
            return ActionResult(False, "Nothing to launch.")
        if re.match(r"^https?://", t, re.I):
            return self.open_url(t)
        site = resolve_site(t) if not re.search(r"[\\/]", t) else None
        if site and self.apps.match(t).status != "match":
            return self.open_urls([site[1]])
        if re.match(r"^(shell:|ms-settings:|steam://|spotify:|discord://)", t, re.I):
            return self._run(f"Opening {t}", lambda: os.startfile(t))
        p = Path(os.path.expandvars(t))
        if p.is_absolute() or "\\" in t or "/" in t:
            if not p.exists():
                return ActionResult(False, f"File not found: {p}")
            return self._run(f"Opening {p.name}", lambda: os.startfile(str(p)))
        m = self.apps.match(t)
        if m.status == "match":
            return self.launch_entry(m.best)
        if m.status == "ambiguous":
            return ActionResult(False, f"'{t}' matches several apps.",
                                {"ambiguous": True, "options": [e.name for e, _ in m.candidates]})
        return ActionResult(False, f"No app called '{t}' was found.")

    # ---- processes
    def find_processes(self, query: str) -> dict[str, list[int]]:
        q = normalize(ALIASES.get(normalize(query), query))
        tokens = [t for t in q.split() if len(t) >= 3]
        joined = q.replace(" ", "")
        me = os.getpid()
        try:
            parent = psutil.Process(me).ppid()
        except Exception:
            parent = -1
        found: dict[str, list[int]] = {}
        for p in psutil.process_iter(["pid", "name"]):
            try:
                name = (p.info["name"] or "")
                base = name.lower().removesuffix(".exe")
                if (not base or base in PROTECTED_PROCESSES or base.startswith("python")
                        or p.info["pid"] in (me, parent, 0, 4)):
                    continue
                if base == joined or base in tokens or (len(joined) >= 4 and joined in base):
                    found.setdefault(name, []).append(p.info["pid"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return found

    def close_processes(self, pids: list[int], label: str) -> ActionResult:
        def go():
            procs = []
            for pid in pids:
                try:
                    pr = psutil.Process(pid)
                    pr.terminate()
                    procs.append(pr)
                except psutil.NoSuchProcess:
                    pass
            _, alive = psutil.wait_procs(procs, timeout=5)
            for pr in alive:
                try:
                    pr.kill()
                except psutil.NoSuchProcess:
                    pass
        return self._run(f"Closing {label}", go)

    # ---- web
    @staticmethod
    def normalize_url(url: str) -> str | None:
        u = (url or "").strip()
        if not u or " " in u:
            return None
        if not re.match(r"^[a-z][a-z0-9+.-]*://", u, re.I):
            u = "https://" + u
        parsed = urllib.parse.urlparse(u)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or "." not in parsed.netloc:
            return None
        return u

    def open_url(self, url: str) -> ActionResult:
        u = self.normalize_url(url)
        if not u:
            return ActionResult(False, f"'{url}' doesn't look like a valid web address.")
        return self.open_urls([u])

    def open_urls(self, urls: list[str], browser: str | None = None) -> ActionResult:
        """Open one or more URLs, in a specific browser if asked (e.g. 'chrome'), else the default browser."""
        exe_name = resolve_browser(browser) if browser else None
        exe_path = find_browser_path(exe_name) if exe_name else None
        where = f" in {browser}" if browser else ""

        def go():
            if exe_path:
                subprocess.Popen([exe_path, *urls])          # Chrome/Edge/Firefox open each URL in a new tab
            elif exe_name and IS_WINDOWS:
                subprocess.Popen(["cmd", "/c", "start", "", exe_name, *urls], creationflags=CREATE_NO_WINDOW)
            else:
                for u in urls:
                    webbrowser.open_new_tab(u)
        res = self._run(f"Opening {', '.join(urls)}{where}", go)
        res.data.update({"urls": urls, "url": urls[0] if urls else None, "browser": browser, "browser_path": exe_path})
        return res

    def web_search(self, query: str, browser: str | None = None, site: str = "") -> ActionResult:
        """Search Google (default) or a specific site: youtube, youtube music, spotify, amazon, github..."""
        q = (query or "").strip()
        if not q:
            return ActionResult(False, "What should I search for?")
        key = resolve_search_site(site)
        if key == "spotify" and not browser:
            app = self.apps.match("spotify")
            if app.status == "match":            # Spotify app installed -> search inside the app
                uri = "spotify:search:" + urllib.parse.quote(q)
                res = self._run(f"Searching Spotify for {q}", lambda: os.startfile(uri))
                res.data.update({"url": uri, "site": "Spotify"})
                return res
        name, template = SEARCH_SITES[key]
        res = self.open_urls([template.format(q=urllib.parse.quote_plus(q))], browser)
        res.data["site"] = name
        return res

    def play_media(self, query: str, site: str = "", browser: str | None = None) -> ActionResult:
        """Play a song/video: opens the FIRST YouTube result directly (or searches Spotify).
        Falls back to the search results page if the first result can't be found."""
        q = (query or "").strip()
        if not q:
            return ActionResult(False, "What should I play?")
        key = resolve_search_site(site or self.play_site)
        if key not in ("youtube", "youtube music"):
            return self.web_search(q, browser, key)
        video = find_youtube_video(q) if not self.dry_run else "dQw4w9WgXcQ"
        if not video:
            log.info("No YouTube result found for %r -> opening the search page", q)
            return self.web_search(q, browser, key)
        host = "music.youtube.com" if key == "youtube music" else "www.youtube.com"
        res = self.open_urls([f"https://{host}/watch?v={video}"], browser)
        res.data.update({"site": SEARCH_SITES[key][0], "video_id": video})
        return res

    # ---- media / system
    def media(self, key: str) -> ActionResult:
        vk = MEDIA_KEYS.get((key or "").strip().lower())
        if vk is None:
            return ActionResult(False, f"Unknown media command '{key}'.")

        def go():
            import ctypes
            user32 = ctypes.windll.user32
            presses = 5 if key in ("volume_up", "volume_down") else 1   # each press = 2%
            for _ in range(presses):
                user32.keybd_event(vk, 0, 0, 0)
                user32.keybd_event(vk, 0, 2, 0)
        return self._run(f"Media: {key.replace('_', ' ')}", go)

    def lock_pc(self) -> ActionResult:
        def go():
            import ctypes
            ctypes.windll.user32.LockWorkStation()
        return self._run("Locking the PC", go)

    def sleep_pc(self) -> ActionResult:
        return self._run("Putting the PC to sleep", lambda: subprocess.Popen(
            ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"]))

    def shutdown_pc(self) -> ActionResult:
        return self._run("Shutting down the PC in 10 seconds", lambda: subprocess.Popen(
            ["shutdown", "/s", "/t", "10"], creationflags=CREATE_NO_WINDOW))

    def restart_pc(self) -> ActionResult:
        return self._run("Restarting the PC in 10 seconds", lambda: subprocess.Popen(
            ["shutdown", "/r", "/t", "10"], creationflags=CREATE_NO_WINDOW))

    def cancel_shutdown(self) -> ActionResult:
        return self._run("Cancelling the scheduled shutdown", lambda: subprocess.Popen(
            ["shutdown", "/a"], creationflags=CREATE_NO_WINDOW))
