
import pytest

from jarvis import Jarvis, detect_lang
from telemetry import TelemetryCollector
from tests.conftest import FakeLLM


def intent(i, target="", reply="", conf=0.95, browser=""):
    return {"intent": i, "target": target, "browser": browser, "reply": reply, "confidence": conf}


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
    assert (await j.handle_text("open youtube"))["data"]["url"] == "https://www.youtube.com"
    assert (await j.handle_text("search weather riyadh"))["status"] == "done"
    assert (await j.handle_text("louder"))["status"] == "done"
    assert (await j.handle_text("lock it"))["status"] == "done"


async def test_bad_url_and_bad_media(make):
    j, _ = make({"weird": intent("open_url", "javascript:alert(1)"), "media": intent("media_control", "explode")})
    assert (await j.handle_text("open the weird thing"))["status"] == "failed"
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
    r = await j.handle_text("tell me a joke")
    assert r["status"] == "error" and "Ollama" in r["reply"]
    # simple commands still work without the LLM
    assert (await j.handle_text("open chrome"))["status"] == "done"


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


# ---------------------------------------------------------------- fixes from first real-PC test

async def test_sites_in_specific_browser_fast_path(make):
    j, llm = make()
    r = await j.handle_text("open instagram, whatsapp and youtube on google chrome")
    assert llm.calls == []                                   # no LLM needed
    assert r["status"] == "done" and r["data"]["browser"] == "google chrome"
    assert r["data"]["urls"] == ["https://www.instagram.com", "https://web.whatsapp.com", "https://www.youtube.com"]
    assert r["reply"] == "Opening Instagram, WhatsApp and YouTube in Chrome."


async def test_sites_in_browser_arabic(make):
    j, llm = make()
    r = await j.handle_text("افتح يوتيوب وانستقرام وواتساب في كروم")
    assert llm.calls == []
    assert r["data"]["urls"] == ["https://www.youtube.com", "https://www.instagram.com", "https://web.whatsapp.com"]
    assert r["reply"] == "جاري فتح YouTube، Instagram وWhatsApp في Chrome."


async def test_llm_open_url_with_browser_field(make):
    j, _ = make({"stuff": intent("open_url", "youtube, instagram", browser="chrome")})
    r = await j.handle_text("could you bring up my stuff")
    assert r["data"]["urls"] == ["https://www.youtube.com", "https://www.instagram.com"]
    assert r["data"]["browser"] == "chrome" and "in Chrome" in r["reply"]


async def test_llm_puts_browser_in_target(make):
    j, _ = make({"stuff": intent("open_url", "youtube on chrome")})
    r = await j.handle_text("bring up my stuff")
    assert r["data"]["urls"] == ["https://www.youtube.com"] and r["data"]["browser"] == "chrome"


async def test_mix_apps_and_sites(make):
    j, _ = make()
    r = await j.handle_text("open spotify and youtube")
    assert r["data"]["app"]["name"] == "Spotify" and r["data"]["urls"] == ["https://www.youtube.com"]
    assert r["reply"] == "Opening Spotify and YouTube."


async def test_open_unknown_thing_goes_to_llm(make):
    j, llm = make({"door": intent("unknown", reply="I can't open doors.")})
    r = await j.handle_text("open the door")
    assert len(llm.calls) == 1 and r["status"] == "needs_clarification"


@pytest.mark.parametrize("answer", ["Yes.", "Yes, close it.", "Yeah, do it.", "yes please", "Sure!", "OK",
                                    "نعم", "اي سكره", "أكيد", "go ahead"])
async def test_close_confirmation_understands_yes(make, monkeypatch, answer):
    j, llm = make({"close": intent("close_app", "spotify")})
    monkeypatch.setattr(j.executor, "find_processes", lambda q: {"Spotify.exe": [111, 112]})
    r = await j.handle_text("close spotify")
    assert r["status"] == "needs_confirmation" and r["reply"] == "Are you sure you want to close Spotify?"
    calls = len(llm.calls)
    r2 = await j.handle_text(answer)
    assert len(llm.calls) == calls, answer       # answered without the LLM
    assert r2["status"] == "done", (answer, r2["reply"])
    assert "Spotify" in r2["reply"] or "سبوتيفاي" in r2["reply"] or "Spotify" in r2["reply"]


@pytest.mark.parametrize("answer", ["No.", "No, don't.", "cancel", "لا", "nope never mind"])
async def test_close_confirmation_understands_no(make, monkeypatch, answer):
    j, _ = make()
    monkeypatch.setattr(j.executor, "find_processes", lambda q: {"Spotify.exe": [111]})
    r = await j.handle_text("close spotify")
    assert r["status"] == "needs_confirmation"
    assert (await j.handle_text(answer))["status"] == "cancelled"


async def test_confirmation_via_llm_when_wording_is_unusual(make, monkeypatch):
    j, llm = make({"go on then": intent("confirm")})
    monkeypatch.setattr(j.executor, "find_processes", lambda q: {"Spotify.exe": [111]})
    await j.handle_text("close spotify")
    r = await j.handle_text("go on then, finish it")
    assert r["status"] == "done"
    # the LLM was told what question is pending
    assert any("You just asked the user" in m["content"] for m in llm.calls[-1] if m["role"] == "system")


async def test_yes_without_pending(make):
    j, _ = make({"yes": intent("confirm")})
    assert (await j.handle_text("yes"))["status"] == "failed"


async def test_fast_media_and_elapsed(make):
    j, llm = make()
    r = await j.handle_text("Turn the volume up")
    assert r["status"] == "done" and r["intent"] == "media_control" and llm.calls == []
    assert r["reply"] == "Volume up."
    assert (await j.handle_text("ارفع الصوت"))["reply"] == "رفعت الصوت."
    assert r["via"] == "rules" and r["elapsed_ms"] >= 0


async def test_fast_path_can_be_disabled(make):
    j, llm = make({"notepad": intent("open_app", "notepad")})
    j.fast_commands = False
    await j.handle_text("open notepad")
    assert len(llm.calls) == 1


async def test_speech_without_commas(make):
    j, llm = make()
    r = await j.handle_text("Open Instagram WhatsApp and YouTube in Chrome.")
    assert llm.calls == [] and len(r["data"]["urls"]) == 3


@pytest.mark.parametrize("text,expected", [
    ("Yes.", True), ("yes close it", True), ("Yeah do it", True), ("No, don't.", False), ("yes don't", None),
    ("open notepad", None), ("لا", False), ("نعم", True), ("", None)])
def test_yes_or_no(text, expected):
    from jarvis import yes_or_no
    assert yes_or_no(text) is expected


# ---------------------------------------------------------------- AI modes (qwen3.5 9b / 4b)

@pytest.fixture
def jm(make, tmp_path):
    from config import Settings
    from modes import ModeManager
    j, llm = make()
    s = Settings()
    s.data_dir = tmp_path
    s.announce_mode_changes = True
    said = []
    m = ModeManager(s, llm, lambda: (int(10.5 * 1024 ** 3), 12 * 1024 ** 3), tmp_path, announce=said.append)
    j.modes = m
    return j, llm, m, said


async def _settle(j):
    import asyncio
    for t in list(j._bg_tasks):
        await t
    await asyncio.sleep(0)


@pytest.mark.parametrize("text,mode,reply", [
    ("gaming mode", "gaming", "Gaming mode on. Switching to the lightweight model."),
    ("Switch to gaming mode please.", "gaming", "Gaming mode on. Switching to the lightweight model."),
    ("حول على وضع الالعاب", "gaming", "تم تفعيل وضع الألعاب. سأستخدم النموذج الخفيف."),
])
async def test_voice_gaming_mode(jm, text, mode, reply):
    j, llm, m, said = jm
    await m.poll_once(initial=True)
    r = await j.handle_text(text, source="voice")
    assert r["reply"] == reply and r["via"] == "rules" and llm.calls == []
    await _settle(j)
    assert m.requested == mode and m.active == "gaming" and llm.model == "qwen3.5:4b"
    assert said == []                     # the voice reply already announced it - no double speech


async def test_voice_normal_and_auto_mode(jm):
    j, llm, m, said = jm
    await m.poll_once(initial=True)
    await j.handle_text("gaming mode", source="voice")
    await _settle(j)
    r = await j.handle_text("normal mode", source="voice")
    assert r["reply"] == "Back to normal mode. Using the full model."
    await _settle(j)
    assert m.active == "normal" and m.requested == "normal"
    r = await j.handle_text("auto mode", source="voice")
    await _settle(j)
    assert r["reply"].startswith("Auto mode on") and m.requested == "auto"
    assert (await j.handle_text("auto mode"))["reply"] == "Already in auto mode."


async def test_which_model(jm):
    j, llm, m, said = jm
    await m.poll_once(initial=True)
    r = await j.handle_text("Which model are you using?")
    assert r["reply"] == "I'm using qwen3.5:9b, the full model, in normal mode, switching automatically."
    assert llm.calls == []
    r = await j.handle_text("وش الموديل اللي تستخدمه؟")
    assert "qwen3.5:9b" in r["reply"] and r["lang"] == "ar"


async def test_mode_via_llm_intent(jm):
    j, llm, m, said = jm
    llm.rules = {"lighter brain": {"intent": "set_mode", "target": "gaming", "browser": "", "reply": "",
                                   "confidence": 0.9}}
    await m.poll_once(initial=True)
    r = await j.handle_text("please use your lighter brain for a while")
    await _settle(j)
    assert r["intent"] == "set_mode" and m.active == "gaming"


async def test_thinking_only_when_asked(jm):
    j, llm, m, said = jm
    await j.handle_text("tell me a fun fact")
    await j.handle_text("Think about it: should I upgrade my GPU or CPU first?")
    await j.handle_text("فكر فيها بعمق: ايش افضل لغة برمجة؟")
    assert llm.thinks == [None, True, True]
    assert any("think carefully" in msg["content"] for msg in llm.calls[1] if msg["role"] == "system")
