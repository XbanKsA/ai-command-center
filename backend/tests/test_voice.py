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

    def fake_run(audio):
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
