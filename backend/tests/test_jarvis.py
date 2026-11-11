
import pytest

from jarvis import Jarvis, detect_lang
from telemetry import TelemetryCollector
from tests.conftest import FakeLLM


def intent(i, target="", reply="", conf=0.95):
    return {"intent": i, "target": target, "reply": reply, "confidence": conf}


@pytest.fixture
def make(dry_executor):
    def _make(rules=None, fail=None):
        llm = FakeLLM(rules, fail)
        return Jarvis(llm, dry_executor, TelemetryCollector(), confirm_timeout=60), llm
    return _make


def test_detect_lang():
    assert detect_lang("open chrome") == "en"
    assert detect_lang("افتح كروم") == "ar"


async def test_chat(make):
    j, _ = make({"hamlet": intent("chat", reply="Shakespeare wrote it.")})
    r = await j.handle_text("who wrote hamlet")
    assert r["status"] == "chat" and "Shakespeare" in r["reply"]


async def test_open_app_executes(make):
    j, _ = make({"spotify": intent("open_app", "spotify", "Opening Spotify.")})
    r = await j.handle_text("open spotify")
    assert r["status"] == "done" and r["data"]["app"]["name"] == "Spotify" and r["data"]["dry_run"]


async def test_open_app_arabic_reply(make):
    j, _ = make({"سبوتيفاي": intent("open_app", "spotify")})
    r = await j.handle_text("افتح سبوتيفاي")
    assert r["status"] == "done" and r["lang"] == "ar" and "جاري فتح" in r["reply"]


async def test_unknown_app(make):
    j, _ = make({"photoshop": intent("open_app", "photoshop")})
    r = await j.handle_text("open photoshop")
    assert r["status"] == "failed" and "photoshop" in r["reply"]


async def test_ambiguous_app_asks_then_choice_by_number(make):
    j, llm = make({"visual studio": intent("open_app", "visual studio")})
    r = await j.handle_text("open visual studio")
    assert r["status"] == "needs_choice" and len(r["options"]) >= 2 and r["pending_id"]
    calls = len(llm.calls)
    r2 = await j.handle_text("the second one")
    assert len(llm.calls) == calls          # answered locally, no LLM call
    assert r2["status"] == "done" and r2["data"]["app"]["name"] == r["options"][1]


async def test_ambiguous_choice_by_name_via_confirm_api(make):
    j, _ = make({"visual studio": intent("open_app", "visual studio")})
    r = await j.handle_text("open visual studio")
    idx = r["options"].index("Visual Studio Code")
    r2 = await j.confirm(r["pending_id"], True, choice=idx)
    assert r2["status"] == "done" and r2["data"]["app"]["name"] == "Visual Studio Code"


async def test_shutdown_requires_confirmation_yes(make):
    j, _ = make({"shut down": intent("shutdown_pc", reply="Shutting down.")})
    r = await j.handle_text("shut down the computer")
    assert r["status"] == "needs_confirmation" and r["pending_id"]
    r2 = await j.handle_text("yes")
    assert r2["status"] == "done" and r2["data"]["dry_run"]


async def test_shutdown_cancel_arabic(make):
    j, _ = make({"اطفي": intent("shutdown_pc")})
    r = await j.handle_text("اطفي الجهاز")
    assert r["status"] == "needs_confirmation" and "متأكد" in r["reply"]
    r2 = await j.handle_text("لا")
    assert r2["status"] == "cancelled"
    assert j.pending == {}


async def test_confirm_via_id_and_expired_id(make):
    j, _ = make({"restart": intent("restart_pc")})
    r = await j.handle_text("restart")
    assert (await j.confirm(r["pending_id"], True))["status"] == "done"
    assert (await j.confirm(r["pending_id"], True))["status"] == "failed"   # already used


async def test_pending_expires(make):
    j, _ = make({"sleep": intent("sleep_pc")})
    j.confirm_timeout = 0
    r = await j.handle_text("sleep")
    import time; time.sleep(0.01)
    assert (await j.confirm(r["pending_id"], True))["status"] == "failed"


async def test_close_app_not_running(make):
    j, _ = make({"close": intent("close_app", "someappthatdoesnotexist")})
    r = await j.handle_text("close someappthatdoesnotexist")
    assert r["status"] == "failed"


async def test_low_confidence_action_needs_confirmation(make):
    j, _ = make({"music": intent("media_control", "play_pause", "Playing.", conf=0.3)})
    r = await j.handle_text("music maybe")
    assert r["status"] == "needs_confirmation"
    assert (await j.handle_text("ok"))["status"] == "done"


async def test_safe_actions(make):
    j, _ = make({
        "youtube": intent("open_url", "youtube.com", "Opening YouTube."),
        "search": intent("web_search", "weather riyadh", "Searching."),
        "louder": intent("media_control", "volume_up", "Volume up."),
        "lock": intent("lock_pc", "", "Locking."),
    })
    assert (await j.handle_text("open youtube"))["data"]["url"] == "https://youtube.com"
    assert (await j.handle_text("search weather riyadh"))["status"] == "done"
    assert (await j.handle_text("louder"))["status"] == "done"
    assert (await j.handle_text("lock it"))["status"] == "done"


async def test_bad_url_and_bad_media(make):
    j, _ = make({"site": intent("open_url", "javascript:alert(1)"), "media": intent("media_control", "explode")})
    assert (await j.handle_text("open site"))["status"] == "failed"
    assert (await j.handle_text("media thing"))["status"] == "needs_clarification"


async def test_system_stats(make):
    j, _ = make({"cpu": intent("system_stats")})
    r = await j.handle_text("how is my cpu")
    assert r["status"] == "done" and "CPU is at" in r["reply"] and "telemetry" in r["data"]


async def test_invented_intent_is_rejected(make):
    j, _ = make({"format": {"intent": "format_disk", "target": "C:", "reply": "ok", "confidence": 1}})
    r = await j.handle_text("format my drive")
    assert r["status"] == "needs_clarification"


async def test_garbage_llm_output(make):
    j, _ = make({"hi": "this is not json at all"})
    assert (await j.handle_text("hi"))["status"] == "failed"
    j2, _ = make({"hi": 'Sure! {"intent":"chat","target":"","reply":"Hey","confidence":1} hope it helps'})
    assert (await j2.handle_text("hi"))["reply"] == "Hey"


async def test_ollama_down(make):
    j, _ = make(fail="Ollama is not running (start the Ollama app).")
    r = await j.handle_text("open chrome")
    assert r["status"] == "error" and "Ollama" in r["reply"]


async def test_history_is_bounded(make):
    j, _ = make()
    for i in range(20):
        await j.handle_text(f"message {i}")
    assert len(j.history) == 12


async def test_listener_receives_events(make):
    j, _ = make()
    got = []

    async def listener(resp):
        got.append(resp)
    j.add_listener(listener)
    await j.handle_text("hello", source="voice")
    assert got and got[0]["source"] == "voice"
