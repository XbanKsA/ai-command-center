"""Mode switching tests with a simulated 12 GB RTX card and a controllable clock."""
import pytest

from config import Settings
from modes import ModeManager
from tests.conftest import FakeLLM

GB = 1024 ** 3


class FakeGPU:
    """NVML-like reader. `other_gb` = VRAM used by games/desktop; the model's VRAM comes from FakeLLM."""

    def __init__(self, llm, total_gb=12.0, other_gb=1.5, available=True):
        self.llm, self.total_gb, self.other_gb, self.available = llm, total_gb, other_gb, available

    def __call__(self):
        if not self.available:
            return None
        used = self.other_gb + sum(self.llm.loaded.values())
        return int((self.total_gb - used) * GB), int(self.total_gb * GB)


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def env(tmp_path):
    s = Settings()
    s.data_dir = tmp_path
    s.mode_default = "auto"
    s.vram_gaming_below_gb, s.vram_normal_above_gb = 9.5, 10.5
    s.normal_after_seconds, s.announce_min_interval = 30, 60
    s.announce_mode_changes = True
    llm = FakeLLM()
    gpu = FakeGPU(llm)
    clock = Clock()
    said, changes = [], []

    async def on_change(state):
        changes.append(state)

    def make(**kw):
        return ModeManager(s, llm, kw.get("reader", gpu), tmp_path, announce=said.append,
                           on_change=on_change, clock=clock)
    return s, llm, gpu, clock, said, changes, make


async def test_startup_normal_and_no_self_trigger(env):
    s, llm, gpu, clock, said, changes, make = env
    llm.loaded["qwen2.5-coder:3b"] = 2.5          # left over from the old JARVIS version
    m = make()
    await m.start()
    await m.stop(unload=False)
    assert m.active == "normal" and m.model == "qwen3.5:9b" and llm.model == "qwen3.5:9b"
    assert llm.loaded == {"qwen3.5:9b": 8.5}      # old model was unloaded
    assert said == []                              # no announcement at startup
    # 9B now uses 8.5 GB -> raw free is only 2 GB, but JARVIS must NOT switch itself to gaming mode
    for _ in range(5):
        clock.t += 5
        await m.poll_once()
    assert m.active == "normal" and m.effective_free_gb == pytest.approx(10.5, abs=0.01)
    assert m.label() == "qwen3.5:9b, Normal mode (auto)"


async def test_game_starts_switch_immediately_unloading_9b_first(env):
    s, llm, gpu, clock, said, changes, make = env
    m = make()
    await m.poll_once(initial=True)
    llm.events.clear()
    gpu.other_gb = 7.0                            # a game grabs 7 GB
    await m.poll_once()
    assert m.active == "gaming" and m.model == "qwen3.5:4b"
    assert llm.events == ["unload qwen3.5:9b", "load qwen3.5:4b"]     # 9B freed before 4B loads
    assert said == ["Gaming mode on. Switching to the lightweight model."]
    assert changes[-1]["label"] == "qwen3.5:4b, Gaming mode (auto)"
    h = m.history[-1]
    assert h["from"]["model"] == "qwen3.5:9b" and h["to"]["model"] == "qwen3.5:4b" and h["source"] == "auto"
    assert "T" in h["time"] and h["free_for_others_gb"] == pytest.approx(5.0, abs=0.01)


async def test_hysteresis_back_to_normal_only_after_30s(env):
    s, llm, gpu, clock, said, changes, make = env
    m = make()
    await m.poll_once(initial=True)
    gpu.other_gb = 7.0
    await m.poll_once()
    assert m.active == "gaming"
    gpu.other_gb = 1.0                            # game closed: 11 GB free for others
    for dt in (0, 10, 20):
        clock.t += 5 if dt else 0
        await m.poll_once()
        assert m.active == "gaming"
    gpu.other_gb = 3.0                            # brief dip (9 GB) resets the timer
    clock.t += 5
    await m.poll_once()
    gpu.other_gb = 1.0
    clock.t += 5
    await m.poll_once()                           # timer starts again here
    start = clock.t
    for _ in range(5):                            # 5, 10 ... 25 s above the threshold: not yet
        clock.t += 5
        await m.poll_once()
        assert m.active == "gaming"
    clock.t = start + 31
    await m.poll_once()
    assert m.active == "normal" and m.model == "qwen3.5:9b"
    # and the normal model's own VRAM still doesn't flip it back
    clock.t += 5
    await m.poll_once()
    assert m.active == "normal"


async def test_announcements_rate_limited_and_can_be_disabled(env):
    s, llm, gpu, clock, said, changes, make = env
    s.normal_after_seconds = 0
    m = make()
    await m.poll_once(initial=True)
    gpu.other_gb = 7.0
    await m.poll_once()                           # -> gaming, announced
    gpu.other_gb = 1.0
    clock.t += 5
    await m.poll_once()
    clock.t += 5
    await m.poll_once()                           # -> normal within 60 s: NOT announced again
    assert m.active == "normal" and len(said) == 1
    clock.t += 61
    gpu.other_gb = 7.0
    await m.poll_once()                           # -> gaming after 60 s: announced
    assert len(said) == 2
    s.announce_mode_changes = False
    clock.t += 120
    await m.set_mode("normal")
    assert len(said) == 2


async def test_manual_override_sticks_and_persists(env):
    s, llm, gpu, clock, said, changes, make = env
    m = make()
    await m.poll_once(initial=True)
    state = await m.set_mode("gaming", source="tablet")
    assert state["requested"] == "gaming" and state["mode"] == "gaming" and state["auto"] is False
    assert state["label"] == "qwen3.5:4b, Gaming mode (manual)"
    for _ in range(20):                           # lots of free VRAM, but manual choice stays
        clock.t += 5
        await m.poll_once()
    assert m.active == "gaming"
    m2 = make()                                   # restart -> still gaming
    assert m2.requested == "gaming"
    await m2.poll_once(initial=True)
    assert m2.active == "gaming"
    await m2.set_mode("auto")
    assert m2.active == "normal" and m2.requested == "auto"
    assert make().requested == "auto"
    with pytest.raises(ValueError):
        await m2.set_mode("turbo")


async def test_no_gpu_means_manual_only(env, caplog):
    s, llm, gpu, clock, said, changes, make = env
    gpu.available = False
    m = make()
    assert "AUTO mode unavailable" in caplog.text
    await m.poll_once(initial=True)
    assert m.auto_available is False and m.active == "normal"
    assert m.label() == "qwen3.5:9b, Normal mode (manual, auto unavailable)"
    await m.set_mode("gaming")
    assert m.active == "gaming"


async def test_missing_model_uses_fallback_and_reports_pull_command(env, caplog):
    s, llm, gpu, clock, said, changes, make = env
    llm.installed = ["qwen3.5:4b", "qwen2.5-coder:3b"]
    m = make()
    await m.poll_once(initial=True)
    st = m.status()
    assert m.model == "qwen2.5-coder:3b" and st["fallback_in_use"]
    assert st["pull_commands"] == ["ollama pull qwen3.5:9b"]
    assert "ollama pull qwen3.5:9b" in caplog.text
    assert m.label().startswith("qwen2.5-coder:3b (fallback), Normal mode")
    await m.set_mode("gaming")
    assert m.model == "qwen3.5:4b" and not m.fallback_in_use


async def test_waits_for_ollama_then_loads(env):
    s, llm, gpu, clock, said, changes, make = env
    llm.reachable = False
    m = make()
    await m.poll_once(initial=True)
    assert m.loaded_ok is False and llm.loaded == {} and m.missing == []
    llm.reachable = True
    await m.poll_once()
    assert m.loaded_ok and llm.loaded == {"qwen3.5:9b": 8.5}


async def test_stop_unloads_model(env):
    s, llm, gpu, clock, said, changes, make = env
    m = make()
    await m.poll_once(initial=True)
    await m.stop(unload=True)
    assert llm.loaded == {}


def test_describe(env):
    s, llm, gpu, clock, said, changes, make = env
    m = make()
    m.active, m.model = "gaming", "qwen3.5:4b"
    assert m.describe("en") == "I'm using qwen3.5:4b, the lightweight model, in gaming mode, switching automatically."
    assert "qwen3.5:4b" in m.describe("ar") and "وضع الألعاب" in m.describe("ar")


async def test_whisper_vram_ignored_and_no_checks_while_busy(env):
    s, llm, gpu, clock, said, changes, make = env
    whisper = {"bytes": 0, "busy": False}
    m = ModeManager(s, llm, gpu, s.data_dir, announce=said.append, clock=clock,
                    own_extra_vram=lambda: whisper["bytes"], busy=lambda: whisper["busy"])
    await m.poll_once(initial=True)
    gpu.other_gb = 1.5 + 1.0                       # Whisper loads 1 GB on the GPU
    whisper["bytes"] = 1 * GB
    await m.poll_once()
    assert m.active == "normal" and m.effective_free_gb == pytest.approx(10.5, abs=0.01)
    whisper["busy"] = True                         # transcription spike: ignored
    gpu.other_gb = 6.0
    await m.poll_once()
    assert m.active == "normal"
    whisper["busy"] = False                        # a real game: switches
    await m.poll_once()
    assert m.active == "gaming"
