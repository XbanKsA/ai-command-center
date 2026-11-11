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


class STT:
    """faster-whisper wrapper. Uses the NVIDIA GPU when the CUDA libraries are present, else CPU."""

    def __init__(self, model_name: str = "small", device: str = "auto", language: str = ""):
        self.model_name = model_name
        self.device_pref = device
        self.language = language or None
        self.model = None
        self.device = None
        self._lock = threading.Lock()

    def _load(self, device: str):
        from faster_whisper import WhisperModel
        compute = "float16" if device == "cuda" else "int8"
        log.info("Loading Whisper '%s' on %s (%s)...", self.model_name, device, compute)
        self.model = WhisperModel(self.model_name, device=device, compute_type=compute)
        self.device = device

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

    def transcribe(self, audio) -> tuple[str, str]:
        """audio = float32 numpy array @16 kHz, or a file-like / bytes (any format ffmpeg/PyAV can read)."""
        self.load()
        if isinstance(audio, (bytes, bytearray)):
            audio = io.BytesIO(audio)
        try:
            return self._run(audio)
        except Exception as exc:
            if self.device == "cuda":    # e.g. missing CUDA DLLs only show up at inference time
                log.warning("GPU transcription failed (%s) -> switching Whisper to CPU", exc)
                with self._lock:
                    self._load("cpu")
                if hasattr(audio, "seek"):
                    audio.seek(0)
                return self._run(audio)
            raise

    def _run(self, audio) -> tuple[str, str]:
        segments, info = self.model.transcribe(audio, language=self.language, beam_size=1,
                                               vad_filter=True, condition_on_previous_text=False)
        text = " ".join(s.text.strip() for s in segments).strip()
        return text, info.language


class TTS:
    def __init__(self, voice: str, voice_arabic: str):
        self.voice = voice
        self.voice_arabic = voice_arabic

    def pick_voice(self, text: str) -> str:
        return self.voice_arabic if _ARABIC.search(text or "") else self.voice

    async def synthesize(self, text: str) -> bytes:
        import edge_tts
        comm = edge_tts.Communicate(text, self.pick_voice(text))
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
    def __init__(self, settings, loop: asyncio.AbstractEventLoop, on_command: CommandHandler):
        self.s = settings
        self.loop = loop
        self.on_command = on_command
        self.stt = STT(settings.whisper_model, settings.whisper_device, settings.stt_language)
        self.tts = TTS(settings.tts_voice, settings.tts_voice_arabic)
        self.status = {"enabled": settings.voice_enabled, "wake_word": "not started", "stt": "not loaded",
                       "listening": False, "busy": False, "last_heard": None, "last_error": None}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
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
    def speak(self, text: str) -> None:
        """Blocking: synthesize with edge-tts and play on the PC speakers."""
        if not text:
            return
        try:
            mp3 = asyncio.run_coroutine_threadsafe(self.tts.synthesize(text), self.loop).result(timeout=30)
            with self._speak_lock:
                self.tts.play_mp3(mp3)
        except Exception as exc:
            self.status["last_error"] = f"TTS: {exc}"
            log.warning("TTS failed (%s). Text was: %s", exc, text)

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

    def _record_command(self, stream, noise_floor: float):
        import numpy as np
        threshold = max(500.0, noise_floor * 3)
        frames, speech_started, silent_chunks = [], False, 0
        start = time.time()
        while time.time() - start < 10:
            chunk, _ = stream.read(CHUNK)
            samples = chunk[:, 0].copy()
            frames.append(samples)
            loud = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2))) > threshold
            if loud:
                speech_started, silent_chunks = True, 0
            else:
                silent_chunks += 1
            if speech_started and silent_chunks >= 12:        # ~1 s of silence after speech
                break
            if not speech_started and time.time() - start > 4:   # nobody spoke
                return None
        return np.concatenate(frames).astype(np.float32) / 32768.0

    def _handle_wake(self, stream, noise_floor: float) -> None:
        self.status["busy"] = True
        try:
            # 1 command + up to 2 follow-ups (answering "are you sure?" / "which one?" needs no wake word)
            for _turn in range(3):
                while stream.read_available >= CHUNK:     # discard audio captured while we were talking
                    stream.read(CHUNK)
                _beep()
                audio = self._record_command(stream, noise_floor)
                if audio is None:
                    log.info("No command heard")
                    return
                text, lang = self.stt.transcribe(audio)
                self.status["last_heard"] = text
                log.info("Heard (%s): %s", lang, text)
                if not text:
                    return
                resp = asyncio.run_coroutine_threadsafe(self.on_command(text), self.loop).result(timeout=180)
                if self.s.speak_responses and resp.get("reply"):
                    self.speak(resp["reply"])
                if resp.get("status") not in ("needs_confirmation", "needs_choice", "needs_clarification"):
                    return
        except Exception as exc:
            self.status["last_error"] = str(exc)
            log.exception("Voice command failed")
        finally:
            self.status["busy"] = False
