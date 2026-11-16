"""
Kageon's hands for files and folders: find, create, move, copy, rename, organize, undo.

Safety rules (all enforced here, not by the AI):
  * Only inside the allowed folders (ALLOWED_FOLDERS, default Desktop/Documents/Downloads/Pictures).
    Anything outside -- Windows, Program Files, other drives -- is refused.
  * Nothing is ever deleted permanently. The only removal is undoing a copy, which goes to the Recycle Bin.
  * Existing files are never overwritten: "photo.png" becomes "photo (2).png".
  * Every change is written to a journal (data/file_actions.json) so "undo that" can put it back,
    even after a restart.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

log = logging.getLogger("files")
IS_WINDOWS = sys.platform == "win32"

# Windows "known folder" IDs: the real locations, even when OneDrive moved Desktop/Documents.
KNOWN_FOLDERS = {
    "desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "downloads": "374DE290-123F-4565-9164-39C4925E467B",
    "pictures": "33E28130-4E1E-4676-835A-98395C3BC3BB",
    "videos": "18989B1D-99B5-455B-841C-AB7C74E4DDFC",
    "music": "4BD8D571-6D19-48D3-BE97-422220080E43",
}
FOLDER_ALIASES = {
    "desktop": "desktop", "my desktop": "desktop", "the desktop": "desktop", "سطح المكتب": "desktop",
    "documents": "documents", "my documents": "documents", "docs": "documents", "المستندات": "documents",
    "downloads": "downloads", "my downloads": "downloads", "download": "downloads", "التنزيلات": "downloads",
    "pictures": "pictures", "my pictures": "pictures", "photos": "pictures", "images": "pictures", "الصور": "pictures",
    "videos": "videos", "my videos": "videos", "music": "music", "my music": "music",
}

# What "organize" sorts into, and what "move my screenshots / images / pdfs ..." means.
CATEGORIES = {
    "Images": {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".heic", ".svg", ".ico", ".tif", ".tiff"},
    "Videos": {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".webm", ".m4v"},
    "Music": {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma"},
    "Documents": {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".xls", ".xlsx", ".csv", ".ppt", ".pptx", ".md"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "Installers": {".exe", ".msi"},
    "Code": {".py", ".js", ".jsx", ".ts", ".html", ".css", ".json", ".ipynb", ".java", ".c", ".cpp", ".cs"},
}
CATEGORY_WORDS = {
    "screenshots": "screenshots", "screenshot": "screenshots", "screen shots": "screenshots",
    "images": "Images", "image": "Images", "pictures": "Images", "photos": "Images", "pics": "Images",
    "videos": "Videos", "video": "Videos", "clips": "Videos", "movies": "Videos",
    "music": "Music", "songs": "Music", "audio": "Music",
    "documents": "Documents", "docs": "Documents", "pdfs": "pdf", "pdf files": "pdf", "pdf": "pdf",
    "zip files": "Archives", "zips": "Archives", "archives": "Archives",
    "installers": "Installers", "setups": "Installers", "setup files": "Installers",
}
# Desktop icons for apps/games: never moved by "organize".
SKIP_SUFFIXES = {".lnk", ".url", ".appref-ms", ".ini", ".tmp", ".crdownload", ".part"}
SKIP_DIRS = {"node_modules", ".git", ".venv", "venv", "__pycache__", "$recycle.bin", "appdata"}
SEARCH_DEPTH = 4
SEARCH_MAX_ENTRIES = 40_000
JOURNAL_KEEP = 20


class FileError(Exception):
    """A request Kageon refuses or can't do; the message is spoken to the user."""


@dataclass
class Plan:
    """What a move/copy/organize WOULD do. Shown to the user for a Yes/No, then executed."""
    op: str                                   # "move" | "copy"
    pairs: list[tuple[Path, Path]]            # (source, destination folder)
    summary: str = ""
    new_dirs: list[Path] = field(default_factory=list)


def known_folder(name: str) -> Path | None:
    key = FOLDER_ALIASES.get(name.strip().lower(), name.strip().lower())
    guid = KNOWN_FOLDERS.get(key)
    if not guid:
        return None
    if IS_WINDOWS:
        try:
            import ctypes
            import uuid
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                            ("Data4", ctypes.c_ubyte * 8)]
            u = uuid.UUID(guid)
            g = GUID(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8)(*u.bytes[8:]))
            ptr = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(ptr)) == 0:
                path = ptr.value
                ctypes.windll.ole32.CoTaskMemFree(ptr)
                return Path(path)
        except Exception as exc:
            log.debug("SHGetKnownFolderPath(%s) failed: %s", key, exc)
    for base in (Path.home(), Path.home() / "OneDrive"):
        p = base / key.title()
        if p.exists():
            return p
    return Path.home() / key.title()


def category_of(path: Path) -> str | None:
    ext = path.suffix.lower()
    return next((cat for cat, exts in CATEGORIES.items() if ext in exts), None)


def _words(text: str) -> list[str]:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)          # "MyCV" -> "My CV"
    return [w for w in re.split(r"[^0-9a-zA-Z؀-ۿ]+", text.lower()) if w]


def name_score(query: str, name: str) -> float:
    q, stem = " ".join(_words(query)), Path(name).stem
    n = " ".join(_words(stem))
    if not q or not n:
        return 0.0
    if q == n or q == name.lower():
        return 1.0
    if q.replace(" ", "") == n.replace(" ", ""):              # "gfxpack" == "GFX Pack"
        return 0.95
    qw, nw = q.split(), n.split()
    if all(w in nw for w in qw):
        return 0.9
    if all(any(x.startswith(w) for x in nw) for w in qw):
        return 0.8
    return SequenceMatcher(None, q, n).ratio() * 0.75


def free_name(folder: Path, name: str, taken: set[str] | None = None) -> Path:
    """folder/name, or folder/'name (2).ext' if that already exists -- never overwrite."""
    taken = taken or set()
    cand = folder / name
    stem, suffix = Path(name).stem, Path(name).suffix
    i = 2
    while cand.exists() or str(cand).lower() in taken:
        cand = folder / f"{stem} ({i}){suffix}"
        i += 1
    return cand


class FileManager:
    def __init__(self, allowed: list[str] | None = None, journal_path: Path | None = None,
                 dry_run: bool = False, roots: dict[str, Path] | None = None):
        self.dry_run = dry_run
        self.journal_path = journal_path
        self.roots: dict[str, Path] = {}
        if roots is not None:                    # tests pass their own folders
            self.roots = {k: Path(v) for k, v in roots.items()}
        else:
            for item in allowed or ["desktop", "documents", "downloads", "pictures"]:
                item = item.strip()
                if not item:
                    continue
                p = known_folder(item) if item.lower() in KNOWN_FOLDERS or item.lower() in FOLDER_ALIASES else None
                if p is None:
                    p = Path(os.path.expandvars(item)).expanduser()
                    if not p.is_absolute():
                        log.warning("ALLOWED_FOLDERS: %r is not a known folder or a full path -- skipped", item)
                        continue
                self.roots[item.lower() if p != Path(item) else p.name.lower()] = p
        self.roots = {k: v.resolve() for k, v in self.roots.items()}
        self.journal: list[dict] = self._load_journal()

    # ------------------------------------------------------------------ safety
    def is_allowed(self, path: Path) -> bool:
        try:
            p = path.resolve()
        except OSError:
            return False
        return any(p == r or r in p.parents for r in self.roots.values())

    def _check(self, *paths: Path) -> None:
        for p in paths:
            if not self.is_allowed(p):
                raise FileError(f"I'm not allowed to touch {p}. I only work in {self.allowed_names()}.")
            if p.resolve() in self.roots.values():
                raise FileError(f"I won't move or rename {p.name} itself.")

    def allowed_names(self) -> str:
        names = [p.name for p in self.roots.values()]
        return ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else "".join(names)

    # ------------------------------------------------------------------ finding things
    def resolve_folder(self, name: str, create_parent: Path | None = None) -> Path | None:
        """'desktop', 'my downloads', 'Projects' (a folder inside an allowed one), or a full path."""
        raw = (name or "").strip().strip('"')
        key = re.sub(r"^(?:my|the)\s+", "", raw.lower()).removesuffix(" folder").strip()
        if not key:
            return None
        alias = FOLDER_ALIASES.get(key) or FOLDER_ALIASES.get(raw.lower())
        if alias:
            for rk, rp in self.roots.items():
                if rk == alias or rp.name.lower() == alias:
                    return rp
            kp = known_folder(alias)
            if kp is not None and self.is_allowed(kp):
                return kp
            return None
        p = Path(os.path.expandvars(raw)).expanduser()
        if p.is_absolute():
            return p if p.is_dir() and self.is_allowed(p) else None
        hits = [h for h in self.find(key, limit=5, dirs_only=True) if name_score(key, h.name) >= 0.9]
        return hits[0] if hits else None

    def _walk(self, dirs_only: bool = False):
        seen = 0
        for root in self.roots.values():
            stack = [(root, 0)]
            while stack:
                folder, depth = stack.pop()
                try:
                    entries = list(os.scandir(folder))
                except OSError:
                    continue
                for e in entries:
                    seen += 1
                    if seen > SEARCH_MAX_ENTRIES:
                        return
                    if e.name.startswith((".", "$", "~$")) or e.name.lower() == "desktop.ini":
                        continue
                    try:
                        is_dir = e.is_dir(follow_symlinks=False)
                    except OSError:
                        continue
                    if is_dir:
                        if e.name.lower() in SKIP_DIRS:
                            continue
                        yield Path(e.path)
                        if depth + 1 < SEARCH_DEPTH:
                            stack.append((Path(e.path), depth + 1))
                    elif not dirs_only:
                        yield Path(e.path)

    def find(self, query: str, limit: int = 5, dirs_only: bool = False) -> list[Path]:
        query = re.sub(r"^(?:my|the|a|an)\s+", "", (query or "").strip(), flags=re.I)
        query = re.sub(r"\s+(?:file|folder|document)$", "", query, flags=re.I)
        if not query:
            return []
        scored = []
        for p in self._walk(dirs_only):
            s = name_score(query, p.name)
            if s >= 0.6:
                try:
                    mtime = p.stat().st_mtime
                except OSError:
                    mtime = 0
                scored.append((s, mtime, p))
        scored.sort(key=lambda x: (-x[0], -x[1]))           # best match first, then newest
        return [p for _, _, p in scored[:limit]]

    def best_match(self, query: str) -> Path | None:
        """One clear winner for 'open my CV' -- or None if nothing / too close to call."""
        hits = self.find(query, limit=3)
        if not hits:
            return None
        top = name_score(query, hits[0].name)
        second = name_score(query, hits[1].name) if len(hits) > 1 else 0
        return hits[0] if top >= 0.9 and (top > second or len(hits) == 1) else None

    def select(self, what: str, source: Path | None = None) -> list[Path]:
        """'my screenshots', 'pdfs', 'all images', or a file/folder name -> the matching paths."""
        w = re.sub(r"^(?:all\s+(?:of\s+)?(?:the\s+|my\s+)?|my\s+|the\s+)", "", (what or "").strip().lower())
        w = re.sub(r"^(?:all\s+)?(?:my\s+|the\s+)?", "", w).strip()
        cat = CATEGORY_WORDS.get(w)
        if cat:
            folders = [source] if source else [r for k, r in self.roots.items() if k in ("desktop", "downloads")] \
                or list(self.roots.values())[:2]
            out = []
            for folder in folders:
                for p in sorted(folder.iterdir()) if folder.is_dir() else []:
                    if not p.is_file() or p.name.startswith((".", "~$")):
                        continue
                    if cat == "screenshots":
                        ok = p.name.lower().startswith(("screenshot", "screen shot", "capture")) and category_of(p) == "Images"
                    elif cat == "pdf":
                        ok = p.suffix.lower() == ".pdf"
                    else:
                        ok = category_of(p) == cat
                    if ok:
                        out.append(p)
            return out
        if source:
            hits = [p for p in source.iterdir() if name_score(what, p.name) >= 0.9]
            return sorted(hits, key=lambda p: -name_score(what, p.name))[:1]
        best = self.best_match(what)
        return [best] if best else []

    def list_folder(self, folder: Path) -> dict:
        """What's inside a folder (top level): folder names, file names and how many of each kind."""
        if not self.is_allowed(folder) or not folder.is_dir():
            raise FileError(f"I'm not allowed to look in {folder}. I only work in {self.allowed_names()}.")
        dirs, files, kinds = [], [], {}
        for p in sorted(folder.iterdir(), key=lambda x: x.name.lower()):
            if p.name.startswith((".", "~$", "$")) or p.name.lower() == "desktop.ini":
                continue
            if p.is_dir():
                dirs.append(p.name)
                continue
            files.append(p.name)
            kind = "shortcuts" if p.suffix.lower() in (".lnk", ".url", ".appref-ms") else (category_of(p) or "other files")
            kinds[kind.lower()] = kinds.get(kind.lower(), 0) + 1
        return {"folder": folder.name, "dirs": dirs, "files": files, "kinds": kinds}

    # ------------------------------------------------------------------ plans (shown before doing)
    def plan_transfer(self, op: str, items: list[Path], dest: Path) -> Plan:
        if not items:
            raise FileError("I couldn't find anything matching that.")
        self._check(*items)
        if not self.is_allowed(dest):
            raise FileError(f"I'm not allowed to put files in {dest}. I only work in {self.allowed_names()}.")
        pairs = [(p, dest) for p in items if p.parent.resolve() != dest.resolve() or op == "copy"]
        if not pairs:
            raise FileError(f"{'It is' if len(items) == 1 else 'They are'} already in {dest.name}.")
        what = pairs[0][0].name if len(pairs) == 1 else f"{len(pairs)} items"
        return Plan(op, pairs, f"{op} {what} to {dest.name}", new_dirs=[] if dest.exists() else [dest])

    def plan_organize(self, folder: Path) -> Plan:
        if not self.is_allowed(folder) or not folder.is_dir():
            raise FileError(f"I can't organize {folder}.")
        pairs, counts = [], {}
        for p in sorted(folder.iterdir()):
            if not p.is_file() or p.suffix.lower() in SKIP_SUFFIXES or p.name.startswith((".", "~$")):
                continue
            cat = category_of(p)
            if cat is None:
                continue
            pairs.append((p, folder / cat))
            counts[cat] = counts.get(cat, 0) + 1
        if not pairs:
            raise FileError(f"{folder.name} is already tidy -- nothing to sort.")
        parts = [f"{n} {c.lower() if n != 1 else c.lower().rstrip('s')}" for c, n in counts.items()]
        summary = f"move {len(pairs)} files into {len(counts)} folders ({', '.join(parts)})"
        new_dirs = [folder / c for c in counts if not (folder / c).exists()]
        return Plan("move", pairs, summary, new_dirs)

    # ------------------------------------------------------------------ doing (journaled)
    def execute(self, plan: Plan) -> tuple[int, list[str]]:
        """-> (number done, errors). Files that are open in another program fail individually."""
        if self.dry_run:
            log.info("[DRY RUN] %s", plan.summary)
            return len(plan.pairs), []
        ops, errors, done = [], [], 0
        for d in plan.new_dirs:
            if not d.exists():
                d.mkdir(parents=True)
                ops.append({"op": "mkdir", "path": str(d)})
        taken: set[str] = set()
        for src, dest_dir in plan.pairs:
            try:
                self._check(src)
                dest_dir.mkdir(parents=True, exist_ok=True)
                dst = free_name(dest_dir, src.name, taken)
                taken.add(str(dst).lower())
                if plan.op == "copy":
                    (shutil.copytree if src.is_dir() else shutil.copy2)(src, dst)
                    ops.append({"op": "copy", "dst": str(dst)})
                else:
                    shutil.move(str(src), str(dst))
                    ops.append({"op": "move", "src": str(src), "dst": str(dst)})
                done += 1
            except (OSError, FileError) as exc:
                errors.append(f"{src.name}: {getattr(exc, 'strerror', None) or exc}")
        self._record(plan.summary, ops)
        log.info("%s: %d done, %d failed", plan.summary, done, len(errors))
        return done, errors

    def create_folder(self, name: str, parent: Path) -> Path:
        name = re.sub(r'[<>:"/\\|?*]', "", (name or "").strip()).strip(". ")
        if not name:
            raise FileError("What should the folder be called?")
        if not self.is_allowed(parent):
            raise FileError(f"I'm not allowed to create folders in {parent}.")
        path = parent / name
        if path.exists():
            raise FileError(f"There's already a {name} in {parent.name}.")
        if not self.dry_run:
            path.mkdir(parents=True)
            self._record(f"create folder {name}", [{"op": "mkdir", "path": str(path)}])
        return path

    def rename(self, item: Path, new_name: str) -> Path:
        self._check(item)
        new_name = re.sub(r'[<>:"/\\|?*]', "", (new_name or "").strip()).strip(". ")
        if not new_name:
            raise FileError("What should the new name be?")
        if item.is_file() and not Path(new_name).suffix:
            new_name += item.suffix                     # "rename notes to ideas" keeps .txt
        dst = item.with_name(new_name)
        if dst.exists():
            raise FileError(f"There's already a {new_name} there.")
        if not self.dry_run:
            item.rename(dst)
            self._record(f"rename {item.name} to {new_name}", [{"op": "move", "src": str(item), "dst": str(dst)}])
        return dst

    def undo(self) -> tuple[str, int, list[str]]:
        """Reverse the most recent change. -> (what it was, items restored, problems)."""
        if not self.journal:
            raise FileError("There's nothing to undo.")
        batch = self.journal.pop()
        restored, problems = 0, []
        for op in reversed(batch["ops"]):
            try:
                if op["op"] == "move":
                    src, dst = Path(op["src"]), Path(op["dst"])
                    if not dst.exists():
                        problems.append(f"{dst.name} is gone")
                        continue
                    target = src if not src.exists() else free_name(src.parent, src.name)
                    shutil.move(str(dst), str(target))
                    restored += 1
                elif op["op"] == "copy":
                    dst = Path(op["dst"])
                    if dst.exists():
                        from send2trash import send2trash
                        send2trash(str(dst))                # Recycle Bin, never a hard delete
                        restored += 1
                elif op["op"] == "mkdir":
                    d = Path(op["path"])
                    if d.exists():
                        if any(d.iterdir()):
                            problems.append(f"kept {d.name} (it's not empty)")
                        else:
                            d.rmdir()
            except (OSError, ImportError) as exc:
                problems.append(f"{Path(op.get('dst') or op.get('path') or '').name}: {exc}")
        self._save_journal()
        return batch["summary"], restored, problems

    # ------------------------------------------------------------------ journal
    def _record(self, summary: str, ops: list[dict]) -> None:
        if not ops:
            return
        self.journal.append({"summary": summary, "ops": ops, "time": time.time()})
        self.journal = self.journal[-JOURNAL_KEEP:]
        self._save_journal()

    def _load_journal(self) -> list[dict]:
        if self.journal_path and self.journal_path.exists():
            try:
                data = json.loads(self.journal_path.read_text(encoding="utf-8"))
                return data if isinstance(data, list) else []
            except (OSError, ValueError):
                return []
        return []

    def _save_journal(self) -> None:
        if not self.journal_path:
            return
        try:
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            self.journal_path.write_text(json.dumps(self.journal, indent=1), encoding="utf-8")
        except OSError as exc:
            log.warning("Could not save the undo journal: %s", exc)
