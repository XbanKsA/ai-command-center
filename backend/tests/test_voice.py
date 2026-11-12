import asyncio

from config import Settings
from voice import STT, TTS, VoiceEngine, cuda_usable


def test_voice_picked_by_language():
    t = TTS("en-GB-RyanNeural", "ar-SA-HamedNeural")
    assert t.pick_voice("Opening Spotify.") == "en-GB-RyanNeural"
    assert t.pick_voice("جاري فتح سبوتيفاي.") == "ar-SA-HamedNeural"


def test_cuda_check_never_raises():
    ok, why = cuda_usable()
    assert isinstance(ok, bool) and isinstance(why, str)


def test_stt_falls_back_to_cpu_when_gpu_inference_fails(monkeypatch):
    stt = STT("tiny", device="cuda")
    loaded = []

    def fake_load(device):
        loaded.append(device)
        stt.device = device
        stt.model = object()

    calls = {"n": 0}

    def fake_run(audio, language=None):
        calls["n"] += 1
        if stt.device == "cuda":
            raise RuntimeError("cudnn_ops64_9.dll missing")
        return "open notepad", "en"

    monkeypatch.setattr(stt, "_load", fake_load)
    monkeypatch.setattr(stt, "_run", fake_run)
    assert stt.transcribe(b"fake-audio") == ("open notepad", "en")
    assert loaded == ["cuda", "cpu"] and calls["n"] == 2


def test_auto_device_uses_cpu_without_cuda(monkeypatch):
    import voice
    monkeypatch.setattr(voice, "cuda_usable", lambda: (False, "no CUDA device"))
    stt = STT("tiny", device="auto")
    seen = []
    monkeypatch.setattr(stt, "_load", lambda d: (seen.append(d), setattr(stt, "model", object())))
    stt.load()
    assert seen == ["cpu"]


def test_voice_disabled_does_not_start():
    s = Settings()
    s.voice_enabled = False
    eng = VoiceEngine(s, asyncio.new_event_loop(), on_command=None)
    eng.start()
    assert "disabled" in eng.status["wake_word"] and eng._thread is None


async def test_tts_cache_reuses_audio(monkeypatch):
    tts = TTS("en-GB-RyanNeural", "ar-SA-HamedNeural")
    calls = []

    async def fake(text, voice):
        calls.append((text, voice))
        return b"mp3:" + text.encode()
    monkeypatch.setattr(tts, "_synthesize", fake)
    assert await tts.synthesize("Opening Chrome.") == b"mp3:Opening Chrome."
    assert await tts.synthesize("Opening Chrome.") == b"mp3:Opening Chrome."
    assert len(calls) == 1


def test_end_of_speech_detection_with_vad():
    """Feed the recorder: silence, 'speech', silence -> it must stop shortly after speech ends."""
    import numpy as np
    s = Settings()
    s.end_silence_ms = 700
    eng = VoiceEngine(s, asyncio.new_event_loop(), on_command=None)

    pattern = [0] * 3 + [1] * 10 + [0] * 30          # 80 ms chunks
    class FakeStream:
        i = 0
        def read(self, n):
            v = pattern[min(self.i, len(pattern) - 1)]
            self.i += 1
            return (np.full((n, 1), 8000 if v else 0, dtype=np.int16), False)
    eng._vad = None                                    # volume-based fallback path
    st = FakeStream()
    audio = eng._record_command(st, noise_floor=100)
    assert audio is not None
    assert st.i <= 3 + 10 + 9 + 1                      # stopped ~0.7 s after speech ended, not after 12 s
    class Quiet(FakeStream):
        def read(self, n):
            return (np.zeros((n, 1), dtype=np.int16), False)
    assert eng._record_command(Quiet(), noise_floor=100, max_wait=0.05) is None


def test_whisper_vram_measurement_sanity(monkeypatch):
    """Startup race: the LLM loads while Whisper loads -> the measured difference is way too big."""
    import sys, types
    GB = 1024 ** 3
    readings = iter([(10 * GB, 12 * GB), (5 * GB, 12 * GB)])      # 5 GB "used by Whisper" = impossible
    stt = STT("small", device="cuda", vram_reader=lambda: next(readings))
    fake = types.ModuleType("faster_whisper")
    fake.WhisperModel = lambda *a, **k: object()
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    stt._load("cuda")
    assert stt.vram_bytes == int(0.8 * GB)                        # typical size used instead
    readings2 = iter([(10 * GB, 12 * GB), (int(9.4 * GB), 12 * GB)])  # 0.6 GB = plausible -> measured
    stt2 = STT("small", device="cuda", vram_reader=lambda: next(readings2))
    stt2._load("cuda")
    assert abs(stt2.vram_bytes - 0.6 * GB) < 0.01 * GB


def test_speech_language_setting():
    s = Settings()
    s.stt_language, s.english_only = "", True
    assert s.speech_language == "en"
    s.english_only = False
    assert s.speech_language == ""            # auto-detect
    s.stt_language = "ar"
    assert s.speech_language == "ar"          # explicit setting wins
    eng = VoiceEngine(Settings(), asyncio.new_event_loop(), on_command=None)
    assert eng.stt.language == "en"            # default: English only
