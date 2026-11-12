"""
Auto mode switching between two Ollama models (only one in VRAM at a time).

  Normal mode : MODEL_NORMAL  (qwen3.5:9b  - smarter, ~8-9 GB VRAM)
  Gaming mode : MODEL_GAMING  (qwen3.5:4b  - lightweight, ~4.5 GB VRAM)
  Fallback    : MODEL_FALLBACK (qwen2.5-coder:3b) if a mode's model isn't downloaded

Requested mode: "auto" | "gaming" | "normal". A manual choice is remembered (even across restarts)
until "auto" is set again.

AUTO detection uses "free VRAM for others" = GPU free VRAM + VRAM held by JARVIS's own model
(from Ollama /api/ps). Without that correction the 9B model would push JARVIS into gaming mode
just by being loaded. Rules:
  * normal -> gaming  immediately when it drops below VRAM_GAMING_BELOW_GB (a game started)
  * gaming -> normal  only after it stays above VRAM_NORMAL_ABOVE_GB for NORMAL_AFTER_SECONDS
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from llm import LLMError, OllamaClient

log = logging.getLogger("modes")
GB = 1024 ** 3
REQUESTS = ("auto", "gaming", "normal")

ANNOUNCEMENTS = {
    "gaming": {"en": "Gaming mode on. Switching to the lightweight model.",
               "ar": "تم تفعيل وضع الألعاب. سأستخدم النموذج الخفيف."},
    "normal": {"en": "Back to normal mode. Using the full model.",
               "ar": "عدنا إلى الوضع العادي. سأستخدم النموذج الكامل."},
}


class ModeManager:
    def __init__(self, settings, llm: OllamaClient, vram_reader: Callable[[], tuple[int, int] | None],
                 data_dir: Path | None = None,
                 announce: Callable[[str], None] | None = None,
                 on_change: Callable[[dict], Awaitable[None]] | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 own_extra_vram: Callable[[], int] | None = None,
                 busy: Callable[[], bool] | None = None):
        self.s = settings
        self.llm = llm
        self.read_vram = vram_reader
        self.announce_fn = announce
        self.on_change = on_change
        self.clock = clock
        self.own_extra_vram = own_extra_vram or (lambda: 0)   # e.g. Whisper on the GPU
        self.busy = busy or (lambda: False)                    # e.g. speech being transcribed right now
        self._file = Path(data_dir or settings.data_dir) / "mode.json"

        self.requested = self._load_requested()
        self.active = "normal"                      # profile in use: "normal" | "gaming"
        self.model = settings.model_normal          # model actually selected
        self.fallback_in_use = False
        self.missing: list[str] = []
        self.loaded_ok = False                      # target model successfully loaded at least once
        self.switching = False
        self.auto_available = vram_reader() is not None
        self.effective_free_gb: float | None = None
        self.total_gb: float | None = None
        self._high_since: float | None = None
        self._warned_offline = False
        self._last_announce = -1e9
        self.history: deque[dict] = deque(maxlen=20)
        self._switch_lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self.llm.model = self.model
        if not self.auto_available:
            log.warning("AUTO mode unavailable: no NVIDIA GPU / pynvml -> manual mode only "
                        "(say 'gaming mode' or 'normal mode', or use the tablet toggle)")

    # ------------------------------------------------------------------ persistence
    def _load_requested(self) -> str:
        try:
            v = json.loads(self._file.read_text(encoding="utf-8")).get("requested")
            if v in REQUESTS:
                return v
        except Exception:
            pass
        v = (self.s.mode_default or "auto").strip().lower()
        return v if v in REQUESTS else "auto"

    def _save_requested(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(json.dumps({"requested": self.requested}), encoding="utf-8")
        except Exception as exc:
            log.debug("could not save mode: %s", exc)

    # ------------------------------------------------------------------ status
    @property
    def is_auto(self) -> bool:
        return self.requested == "auto"

    def label(self) -> str:
        how = "auto" if self.is_auto and self.auto_available else "manual"
        if self.is_auto and not self.auto_available:
            how = "manual, auto unavailable"
        model = f"{self.model} (fallback)" if self.fallback_in_use else self.model
        return f"{model}, {self.active.capitalize()} mode ({how})"

    def describe(self, lang: str = "en") -> str:
        """Spoken answer to 'which model are you using?'."""
        how_en = "switching automatically" if self.is_auto and self.auto_available else "set manually"
        how_ar = "التبديل تلقائي" if self.is_auto and self.auto_available else "تم ضبطه يدوياً"
        size = "lightweight" if self.active == "gaming" else "full"
        if lang == "ar":
            mode_ar = "وضع الألعاب" if self.active == "gaming" else "الوضع العادي"
            fb = " (نموذج احتياطي)" if self.fallback_in_use else ""
            return f"أستخدم {self.model}{fb}، في {mode_ar}، و{how_ar}."
        fb = ", the fallback model" if self.fallback_in_use else f", the {size} model"
        return f"I'm using {self.model}{fb}, in {self.active} mode, {how_en}."

    def status(self) -> dict:
        return {
            "label": self.label(),
            "model": self.model,
            "mode": self.active,                       # what is in effect: normal | gaming
            "requested": self.requested,               # auto | gaming | normal
            "auto": self.is_auto,
            "auto_available": self.auto_available,
            "switching": self.switching,
            "fallback_in_use": self.fallback_in_use,
            "missing_models": list(self.missing),
            "pull_commands": [f"ollama pull {m}" for m in self.missing],
            "models": {"normal": self.s.model_normal, "gaming": self.s.model_gaming,
                       "fallback": self.s.model_fallback},
            "vram": {"free_for_others_gb": self.effective_free_gb, "total_gb": self.total_gb,
                     "gaming_below_gb": self.s.vram_gaming_below_gb,
                     "normal_above_gb": self.s.vram_normal_above_gb,
                     "normal_after_seconds": self.s.normal_after_seconds},
            "last_switch": self.history[-1] if self.history else None,
        }

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        """Pick the right model now, then watch VRAM in the background."""
        await self.poll_once(initial=True)
        self._task = asyncio.create_task(self._loop())

    async def stop(self, unload: bool = True) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        if unload and self.loaded_ok:
            if await self.llm.unload(self.model):
                log.info("Unloaded %s from VRAM (JARVIS exiting)", self.model)

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.s.vram_poll_seconds)
            try:
                await self.poll_once()
            except Exception:
                log.exception("mode check failed")

    # ------------------------------------------------------------------ measuring
    async def measure(self) -> float | None:
        """Free VRAM in GB as if JARVIS's own model were unloaded. None if no NVIDIA GPU."""
        info = self.read_vram()
        if info is None:
            return None
        free, total = info
        ours = {self.s.model_normal, self.s.model_gaming, self.s.model_fallback}
        ours |= {m if ":" in m else f"{m}:latest" for m in ours}
        own = sum(m["size_vram"] for m in await self.llm.loaded_models() if m["name"] in ours)
        own += int(self.own_extra_vram() or 0)
        self.total_gb = round(total / GB, 1)
        self.effective_free_gb = round((free + own) / GB, 2)
        return self.effective_free_gb

    async def poll_once(self, initial: bool = False) -> None:
        if self.switching or (not initial and self.loaded_ok and self.busy()):
            return          # don't measure while JARVIS itself is busy using the GPU (short spikes)
        free = await self.measure()
        if free is None and self.auto_available:
            self.auto_available = False
            log.warning("Lost NVIDIA GPU readings -> AUTO mode unavailable, manual mode only")
        elif free is not None and not self.auto_available:
            self.auto_available = True
            log.info("NVIDIA GPU readings available -> AUTO mode enabled")

        if initial or not self.loaded_ok:
            # first start (or Ollama wasn't ready yet): choose a profile and load it
            target = self._initial_profile(free)
            await self._switch(target, self._reason_for(target, free, initial=True), source="startup",
                               announce=False, force=True)
            return

        if not self.is_auto or free is None:
            return

        now = self.clock()
        if self.active == "normal":
            self._high_since = None
            if free < self.s.vram_gaming_below_gb:
                await self._switch("gaming", f"free VRAM {free:.1f} GB < {self.s.vram_gaming_below_gb} GB",
                                   source="auto")
        else:  # gaming: hysteresis - must stay high for a while before going back
            if free > self.s.vram_normal_above_gb:
                if self._high_since is None:
                    self._high_since = now
                    log.info("Free VRAM %.1f GB > %.1f GB - back to normal in %.0fs if it stays high",
                             free, self.s.vram_normal_above_gb, self.s.normal_after_seconds)
                elif now - self._high_since >= self.s.normal_after_seconds:
                    await self._switch("normal", f"free VRAM {free:.1f} GB > {self.s.vram_normal_above_gb} GB "
                                                 f"for {self.s.normal_after_seconds:.0f}s", source="auto")
            else:
                self._high_since = None

    def _initial_profile(self, free: float | None) -> str:
        if self.requested in ("gaming", "normal"):
            return self.requested
        if free is not None and free < self.s.vram_gaming_below_gb:
            return "gaming"
        return "normal"

    def _reason_for(self, target: str, free: float | None, initial: bool = False) -> str:
        if self.requested in ("gaming", "normal"):
            return f"manual {self.requested} mode"
        if free is None:
            return "no GPU readings (auto unavailable)"
        return f"free VRAM {free:.1f} GB" + (" at startup" if initial else "")

    # ------------------------------------------------------------------ manual override
    async def set_mode(self, requested: str, source: str = "manual") -> dict:
        requested = (requested or "").strip().lower()
        if requested not in REQUESTS:
            raise ValueError(f"mode must be one of {REQUESTS}")
        self.requested = requested
        self._save_requested()
        self._high_since = None
        log.info("Mode set to %s by %s", requested.upper(), source)
        if requested in ("gaming", "normal"):
            if requested != self.active or not self.loaded_ok:
                await self._switch(requested, f"manual {requested} mode", source=source)
            elif self.on_change:
                await self.on_change(self.status())
        else:
            free = await self.measure()
            target = self._initial_profile(free)
            if target != self.active or not self.loaded_ok:
                await self._switch(target, self._reason_for(target, free), source=source)
            elif self.on_change:
                await self.on_change(self.status())
        return self.status()

    # ------------------------------------------------------------------ the swap
    async def _switch(self, profile: str, reason: str, source: str, announce: bool = True,
                      force: bool = False) -> None:
        async with self._switch_lock:
            if profile == self.active and self.loaded_ok and not force:
                return
            try:
                installed = set(await self.llm.installed_models())
            except Exception:
                if not self._warned_offline:
                    log.warning("Ollama is not reachable yet - JARVIS will load the %s model when it starts",
                                profile)
                    self._warned_offline = True
                self.active, self.loaded_ok = profile, False
                return
            self._warned_offline = False
            full = lambda m: m if ":" in m else f"{m}:latest"
            self.switching = True
            old_profile, old_model = self.active, self.model
            t0 = time.perf_counter()
            unload_s = load_s = 0.0
            try:
                target = self.s.model_gaming if profile == "gaming" else self.s.model_normal
                fallback = False
                missing = [m for m in (self.s.model_normal, self.s.model_gaming) if full(m) not in installed]
                self.missing = missing
                if target in missing:
                    log.warning("Model %s is not downloaded. Run:  ollama pull %s", target, target)
                    if full(self.s.model_fallback) in installed:
                        target, fallback = self.s.model_fallback, True
                        log.warning("Using fallback model %s for now", target)

                # wait for any reply that is still being generated, then swap
                async with self.llm.lock:
                    t_unload = time.perf_counter()
                    ours = {self.s.model_normal, self.s.model_gaming, self.s.model_fallback}
                    loaded = await self.llm.loaded_models()
                    for m in loaded:
                        base = m["name"].removesuffix(":latest")
                        if (m["name"] in ours or base in ours) and m["name"] != target and base != target:
                            await self.llm.unload(m["name"])
                            log.info("Unloaded %s", m["name"])
                    unload_s = time.perf_counter() - t_unload
                    self.active, self.model, self.fallback_in_use = profile, target, fallback
                    self.llm.model = target
                    t_load = time.perf_counter()
                    try:
                        await self.llm.warm(target)
                        self.loaded_ok = True
                    except LLMError as exc:
                        self.loaded_ok = False
                        log.warning("Could not load %s: %s", target, exc)
                    load_s = time.perf_counter() - t_load
            finally:
                self.switching = False

            entry = {
                "time": datetime.now().isoformat(timespec="seconds"),
                "from": {"mode": old_profile, "model": old_model},
                "to": {"mode": profile, "model": self.model},
                "requested": self.requested, "source": source, "reason": reason,
                "free_for_others_gb": self.effective_free_gb, "loaded": self.loaded_ok,
                "seconds": round(time.perf_counter() - t0, 2),
            }
            self.history.append(entry)
            if source == "startup":
                log.info("[%s] STARTUP: %s mode (%s) - %s | loaded %s in %.1fs%s", entry["time"], profile.upper(),
                         self.requested, reason, self.model, load_s, "" if self.loaded_ok else " | LOAD FAILED")
            else:
                log.info("[%s] MODE SWITCH %s -> %s (%s, by %s): %s | %s -> %s | unload %.1fs, load %.1fs%s",
                         entry["time"], old_profile.upper(), profile.upper(), self.requested, source, reason,
                         old_model, self.model, unload_s, load_s, "" if self.loaded_ok else " | LOAD FAILED")

        if announce and source != "voice" and old_profile != profile:
            self.announce(ANNOUNCEMENTS[profile]["en"])
        if source == "voice":
            self._last_announce = self.clock()      # the voice reply already said it
        if self.on_change:
            await self.on_change(self.status())

    # ------------------------------------------------------------------ voice announcements
    def announce(self, text: str) -> bool:
        if not self.s.announce_mode_changes or not self.announce_fn:
            return False
        now = self.clock()
        if now - self._last_announce < self.s.announce_min_interval:
            log.info("Mode announcement skipped (spoke one %.0fs ago): %s", now - self._last_announce, text)
            return False
        self._last_announce = now
        try:
            self.announce_fn(text)
        except Exception as exc:
            log.debug("announce failed: %s", exc)
        return True
