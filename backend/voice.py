"""
Voice pipeline (runs entirely on the PC, works with the tablet off):

  mic --> openWakeWord ("Hey Jarvis") --> record until silence --> faster-whisper (STT)
      --> JARVIS agent --> edge-tts (speech) --> speakers

All heavy libraries are imported lazily so the server still starts (voice disabled)
if a voice dependency, the microphone, or the internet (edge-tts) is missing.
"""
from __future__ import annotations

import asyncio
import io
import logging
import re
import threading
import time
from typing import Awaitable, Callable

log = logging.getLogger("voice")

SAMPLE_RATE = 16_000
CHUNK = 1280                  # 80 ms @ 16 kHz (what openWakeWord expects)
TTS_RATE = 24_000
_ARABIC = re.compile(r"[؀-ۿ]")


def _add_nvidia_dll_dirs() -> None:
    """If `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12` was used, make their DLLs findable."""
    import os
    import site
    from pathlib import Path
    roots = [Path(p) for p in site.getsitepackages() + [site.getusersitepackages()]]
    for root in roots:
        for bin_dir in root.glob("nvidia/*/bin"):
            try:
                os.add_dll_directory(str(bin_dir))
            except (OSError, AttributeError):
                pass
            if str(bin_dir) not in os.environ.get("PATH", ""):
                os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


def cuda_usable() -> tuple[bool, str]:
    """Check GPU speech recognition can work BEFORE trying it: a missing CUDA DLL can make
    ctranslate2 abort the whole process instead of raising a Python error."""
    import sys
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() < 1:
            return False, "no CUDA device"
    except Exception as exc:
        return False, str(exc)
    if sys.platform == "win32":
        import ctypes
        _add_nvidia_dll_dirs()
        for dll in ("cublas64_12.dll", "cudnn_ops64_9.dll"):
            try:
                ctypes.WinDLL(dll)
            except OSError:
                return False, f"{dll} not found (optional: pip install nvidia-cublas-cu12 nvidia-cudnn-cu12==9.*)"
    return True, ""


# Typical VRAM of faster-whisper models in float16 on the GPU (GB) - used to sanity-check measurements
WHISPER_VRAM_GB = {"tiny": 0.3, "base": 0.4, "small": 0.8, "medium": 1.8, "turbo": 1.8, "large": 3.5,
                   "distil": 1.8}


def whisper_vram_estimate(model_name: str) -> float:
    name = model_name.lower()
    for key, gb in WHISPER_VRAM_GB.items():
        if key in name:
            return gb
    return 1.0


class STT:
    """faster-whisper wrapper. Uses the NVIDIA GPU when the CUDA libraries are present, else CPU."""

    def __init__(self, model_name: str = "small", device: str = "auto", language: str = "",
                 vram_reader=None):
        self.model_name = model_name
        self.vram_reader = vram_reader          # () -> (free, total) | None
        self.vram_bytes = 0                     # VRAM Whisper itself occupies (so mode switching ignores it)
        self.device_pref = device
        self.language = language or None
        self.model = None
        self.device = None
        self._lock = threading.Lock()

    def _load(self, device: str):
        from faster_whisper import WhisperModel
        compute = "float16" if device == "cuda" else "int8"
        log.info("Loading Whisper '%s' on %s (%s)...", self.model_name, device, compute)
        before = self.vram_reader() if (device == "cuda" and self.vram_reader) else None
        self.model = WhisperModel(self.model_name, device=device, compute_type=compute)
        self.device = device
        self.vram_bytes = 0
        if device == "cuda":
            # Measure, but don't trust a wild number: if the LLM was loading at the same moment,
            # the difference includes part of the LLM too. Fall back to the known typical size.
            est = whisper_vram_estimate(self.model_name)
            after = self.vram_reader() if (before and self.vram_reader) else None
            measured = (before[0] - after[0]) / 1024 ** 3 if (before and after) else None
            if measured is not None and 0.1 <= measured <= est * 1.5:
                gb = measured
            else:
                gb = est
                if measured is not None:
                    log.info("Whisper VRAM measurement (%.1f GB) looks off (other GPU activity) - using %.1f GB",
                             measured, est)
            self.vram_bytes = int(gb * 1024 ** 3)
            log.info("Whisper uses ~%.1f GB of VRAM", gb)

    def load(self) -> None:
        with self._lock:
            if self.model is not None:
                return
            if self.device_pref == "auto":
                usable, why = cuda_usable()
                if not usable:
                    log.info("Whisper will use the CPU (GPU not usable: %s)", why)
                order = ["cuda", "cpu"] if usable else ["cpu"]
            else:
                order = [self.device_pref]
            last = None
            for dev in order:
                try:
                    self._load(dev)
                    return
                except Exception as exc:
                    last = exc
                    log.warning("Whisper on %s failed: %s", dev, exc)
            raise RuntimeError(f"Could not load Whisper: {last}")

    def transcribe(self, audio, language: str | None = None) -> tuple[str, str]:
        """audio = float32 numpy array @16 kHz, or a file-like / bytes (any format ffmpeg/PyAV can read).
        language = optional hint ('en'/'ar'); defaults to STT_LANGUAGE or auto-detect."""
        self.load()
        if isinstance(audio, (bytes, bytearray)):
            audio = io.BytesIO(audio)
        try:
            return self._run(audio, language)
        except Exception as exc:
            if self.device == "cuda":    # e.g. missing CUDA DLLs only show up at inference time
                log.warning("GPU transcription failed (%s) -> switching Whisper to CPU", exc)
                with self._lock:
                    self._load("cpu")
                if hasattr(audio, "seek"):
                    audio.seek(0)
                return self._run(audio, language)
            raise

    def _run(self, audio, language: str | None = None) -> tuple[str, str]:
        segments, info = self.model.transcribe(audio, language=self.language or language, beam_size=1,
                                               vad_filter=True, condition_on_previous_text=False,
                                               without_timestamps=True)
        text = " ".join(s.text.strip() for s in segments).strip()
        return text, info.language


class TTS:
    def __init__(self, voice: str, voice_arabic: str, cache_size: int = 200):
        self.voice = voice
        self.voice_arabic = voice_arabic
        self._cache: dict[tuple[str, str], bytes] = {}     # repeated replies ("Opening Chrome.") play instantly
        self._cache_size = cache_size

    def pick_voice(self, text: str) -> str:
        return self.voice_arabic if _ARABIC.search(text or "") else self.voice

    async def synthesize(self, text: str) -> bytes:
        key = (self.pick_voice(text), text)
        if key in self._cache:
            return self._cache[key]
        mp3 = await self._synthesize(text, key[0])
        if len(self._cache) >= self._cache_size:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = mp3
        return mp3

    async def _synthesize(self, text: str, voice: str) -> bytes:
        import edge_tts
        comm = edge_tts.Communicate(text, voice)
        audio = bytearray()
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
        if not audio:
            raise RuntimeError("edge-tts returned no audio")
        return bytes(audio)

    @staticmethod
    def play_mp3(mp3: bytes) -> None:
        import miniaudio
        import numpy as np
        import sounddevice as sd
        decoded = miniaudio.decode(mp3, output_format=miniaudio.SampleFormat.SIGNED16,
                                   nchannels=1, sample_rate=TTS_RATE)
        samples = np.frombuffer(decoded.samples, dtype=np.int16)
        sd.play(samples, TTS_RATE)
        sd.wait()


def _beep():
    try:
        import numpy as np
        import sounddevice as sd
        t = np.linspace(0, 0.12, int(TTS_RATE * 0.12), False)
        tone = (np.sin(2 * np.pi * 880 * t) * 0.25 * np.hanning(t.size)).astype("float32")
        sd.play(tone, TTS_RATE)
        sd.wait()
    except Exception:
        pass


CommandHandler = Callable[[str], Awaitable[dict]]


class VoiceEngine:
    def __init__(self, settings, loop: asyncio.AbstractEventLoop, on_command: CommandHandler, vram_reader=None):
        self.s = settings
        self.loop = loop
        self.on_command = on_command
        self.stt = STT(settings.whisper_model, settings.whisper_device, settings.stt_language, vram_reader)
        self.tts = TTS(settings.tts_voice, settings.tts_voice_arabic)
        self.status = {"enabled": settings.voice_enabled, "wake_word": "not started", "stt": "not loaded",
                       "listening": False, "busy": False, "last_heard": None, "last_error": None}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._vad = None
        self._speak_lock = threading.Lock()

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if not self.s.voice_enabled:
            self.status["wake_word"] = "disabled (VOICE_ENABLED=false)"
            return
        self._thread = threading.Thread(target=self._run, name="voice", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # ---------------------------------------------------------------- speaking
    def speak(self, text: str) -> float:
        """Blocking: synthesize with edge-tts and play on the PC speakers. Returns synthesis time (s)."""
        if not text:
            return 0.0
        t0 = time.perf_counter()
        try:
            mp3 = asyncio.run_coroutine_threadsafe(self.tts.synthesize(text), self.loop).result(timeout=30)
            synth = time.perf_counter() - t0
            with self._speak_lock:
                self.tts.play_mp3(mp3)
            return synth
        except Exception as exc:
            self.status["last_error"] = f"TTS: {exc}"
            log.warning("TTS failed (%s). Text was: %s", exc, text)
            return time.perf_counter() - t0

    def announce(self, text: str) -> None:
        """Non-blocking: speak a notification (e.g. a mode change) in the background."""
        if not self.s.speak_responses or not text:
            return
        threading.Thread(target=self.speak, args=(text,), name="announce", daemon=True).start()

    # ---------------------------------------------------------------- main loop
    def _mic_device(self):
        d = (self.s.mic_device or "").strip()
        return int(d) if d.isdigit() else (d or None)

    def _run(self) -> None:
        try:
            import numpy as np
            import sounddevice as sd
            from openwakeword.model import Model
            from openwakeword.utils import download_models
        except Exception as exc:
            self.status["wake_word"] = f"error: voice packages missing ({exc})"
            log.error("Voice disabled -- missing packages: %s", exc)
            return

        try:
            download_models([self.s.wake_word_model])   # no-op when already downloaded
        except Exception as exc:
            log.warning("Could not download wake-word model (%s); trying local copy", exc)
        try:
            oww = Model(wakeword_models=[self.s.wake_word_model], inference_framework="onnx")
        except Exception as exc:
            self.status["wake_word"] = f"error: {exc}"
            log.error("Wake word model failed to load: %s", exc)
            return
        try:
            from openwakeword.vad import VAD
            self._vad = VAD()          # Silero voice-activity detector: knows when you stopped talking
        except Exception as exc:
            self._vad = None
            log.warning("VAD unavailable (%s) -- using volume-based end-of-speech detection", exc)

        # Load Whisper in the background so first command isn't slow
        threading.Thread(target=self._preload_stt, daemon=True).start()

        noise_floor = 300.0
        while not self._stop.is_set():
            try:
                with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                    blocksize=CHUNK, device=self._mic_device()) as stream:
                    self.status.update(wake_word="listening", listening=True)
                    log.info("Voice ready -- say 'Hey Jarvis' (mic: %s)", sd.query_devices(stream.device)["name"])
                    while not self._stop.is_set():
                        chunk, _ = stream.read(CHUNK)
                        samples = chunk[:, 0]
                        rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
                        noise_floor = 0.98 * noise_floor + 0.02 * rms
                        scores = oww.predict(samples)
                        if max(scores.values(), default=0) >= self.s.wake_threshold:
                            log.info("Wake word detected (score %.2f)", max(scores.values()))
                            self._handle_wake(stream, noise_floor)
                            oww.reset()
                            # drop audio that piled up while we were busy
                            while stream.read_available >= CHUNK:
                                stream.read(CHUNK)
            except Exception as exc:
                self.status.update(wake_word=f"error: {exc}", listening=False, last_error=str(exc))
                log.error("Microphone error: %s -- retrying in 5s", exc)
                self._stop.wait(5)
        self.status.update(listening=False, wake_word="stopped")

    def _preload_stt(self) -> None:
        try:
            self.stt.load()
            self.status["stt"] = f"ready ({self.stt.model_name} on {self.stt.device})"
        except Exception as exc:
            self.status["stt"] = f"error: {exc}"

    def _is_speech(self, samples, threshold: float) -> bool:
        import numpy as np
        if self._vad is not None:
            return float(self._vad.predict(samples, frame_size=640)) > 0.5
        return float(np.sqrt(np.mean(samples.astype(np.float32) ** 2))) > threshold

    def _record_command(self, stream, noise_floor: float, max_wait: float = 4.0):
        """Record until the user stops talking. Returns float32 audio, or None if nobody spoke."""
        import numpy as np
        threshold = max(500.0, noise_floor * 3)
        end_chunks = max(3, round(self.s.end_silence_ms / 80))        # 80 ms per chunk
        if self._vad is not None:
            self._vad.reset_states()
        frames, speech_chunks, silent_chunks = [], 0, 0
        start = time.time()
        while time.time() - start < 12:
            chunk, _ = stream.read(CHUNK)
            samples = chunk[:, 0].copy()
            frames.append(samples)
            if self._is_speech(samples, threshold):
                speech_chunks, silent_chunks = speech_chunks + 1, 0
            else:
                silent_chunks += 1
            if speech_chunks >= 2 and silent_chunks >= end_chunks:      # spoke, then went quiet
                break
            if speech_chunks == 0 and time.time() - start > max_wait:   # nobody spoke
                return None
        # keep ~0.3 s before speech onset; drop the trailing silence
        audio = np.concatenate(frames[: len(frames) - max(0, silent_chunks - 2)])
        return audio.astype(np.float32) / 32768.0

    def _handle_wake(self, stream, noise_floor: float) -> None:
        self.status["busy"] = True
        try:
            # 1 command + up to 2 follow-ups (answering "are you sure?" / "which one?" needs no wake word)
            lang_hint = None
            for turn in range(3):
                while stream.read_available >= CHUNK:     # discard audio captured while we were talking
                    stream.read(CHUNK)
                _beep()
                t0 = time.perf_counter()
                audio = self._record_command(stream, noise_floor, max_wait=4.0 if turn == 0 else 6.0)
                if audio is None:
                    log.info("No command heard")
                    return
                t1 = time.perf_counter()
                # follow-up answers ("yes") are short: reuse the language of the first command
                text, lang = self.stt.transcribe(audio, language=lang_hint)
                lang_hint = lang_hint or (lang if lang in ("en", "ar") else None)
                t2 = time.perf_counter()
                self.status["last_heard"] = text
                log.info("Heard (%s): %s", lang, text)
                if not text:
                    return
                resp = asyncio.run_coroutine_threadsafe(self.on_command(text), self.loop).result(timeout=180)
                t3 = time.perf_counter()
                synth = 0.0
                if self.s.speak_responses and resp.get("reply"):
                    synth = self.speak(resp["reply"])
                log.info("Timing: you spoke %.1fs | speech-to-text %.2fs (%s) | JARVIS %.2fs (%s) | voice %.2fs | "
                         "reply started %.1fs after you stopped talking",
                         t1 - t0, t2 - t1, self.stt.device, t3 - t2, resp.get("via", "?"), synth,
                         (t2 - t1) + (t3 - t2) + synth + self.s.end_silence_ms / 1000)
                if resp.get("status") not in ("needs_confirmation", "needs_choice", "needs_clarification"):
                    return
        except Exception as exc:
            self.status["last_error"] = str(exc)
            log.exception("Voice command failed")
        finally:
            self.status["busy"] = False
