
import pytest

from assistant import Assistant, detect_lang
from telemetry import TelemetryCollector
from tests.conftest import FakeLLM


def intent(i, target="", reply="", conf=0.95, browser=""):
    return {"intent": i, "target": target, "browser": browser, "reply": reply, "confidence": conf}


@pytest.fixture
def make(dry_executor):
    def _make(rules=None, fail=None):
        llm = FakeLLM(rules, fail)
        return Assistant(llm, dry_executor, TelemetryCollector(), confirm_timeout=60), llm
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
    from assistant import yes_or_no
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
    ("Swap to gamingmode.", "gaming", "Gaming mode on. Switching to the lightweight model."),
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



def test_compact_mode_words():
    from assistant import detect_mode_command
    assert detect_mode_command("swap to automode") == "auto"
    assert detect_mode_command("Normalmode please") == "normal"


# ---------------------------------------------------------------- search / play (YouTube, Spotify)

async def test_search_cat_video_goes_to_youtube(make):
    j, llm = make()
    r = await j.handle_text("search for a cat video")
    assert llm.calls == [] and r["status"] == "done"
    assert r["data"]["url"] == "https://www.youtube.com/results?search_query=cat"
    assert r["reply"] == "Searching YouTube for cat."


async def test_search_song_via_llm_uses_youtube(make):
    j, llm = make({"bad romance": {"intent": "web_search", "target": "bad romance lady gaga", "browser": "",
                                    "site": "youtube", "steps": [], "reply": "", "confidence": 0.9}})
    r = await j.handle_text("search for bad romance by lady gaga")
    assert len(llm.calls) == 1
    assert r["data"]["url"] == "https://www.youtube.com/results?search_query=bad+romance+lady+gaga"


async def test_play_opens_first_video(make):
    j, llm = make()
    r = await j.handle_text("play bad romance by lady gaga")
    assert llm.calls == [] and r["intent"] == "play_media"
    assert r["data"]["url"].startswith("https://www.youtube.com/watch?v=")
    assert r["reply"] == "Playing bad romance by lady gaga on YouTube."
    r = await j.handle_text("play lofi beats on youtube music")
    assert r["data"]["url"].startswith("https://music.youtube.com/watch?v=")


async def test_play_on_spotify_uses_app(make):
    j, _ = make()
    r = await j.handle_text("play shape of you on spotify")
    assert r["data"]["url"] == "spotify:search:shape%20of%20you" and r["data"]["site"] == "Spotify"


async def test_plain_play_is_still_media_key_and_google_default(make):
    j, _ = make()
    assert (await j.handle_text("play"))["intent"] == "media_control"
    r = await j.handle_text("search for the weather in riyadh")
    assert r["data"]["url"] == "https://www.google.com/search?q=the+weather+in+riyadh"
    r = await j.handle_text("look up rtx 5070 prices on amazon")
    assert r["data"]["url"].startswith("https://www.amazon.sa/s?k=rtx+5070+prices")


# ---------------------------------------------------------------- screen

async def test_screen_question_sends_screenshot(make, monkeypatch):
    import assistant as jmod
    monkeypatch.setattr(jmod, "capture_screen", lambda max_side: "BASE64IMAGE")
    j, llm = make({"on my screen": "You have **VS Code** open with a SyntaxError on line 12."})
    r = await j.handle_text("Can you see what's on my screen?")
    assert r["status"] == "chat" and r["via"] == "vision"
    assert r["reply"] == "You have VS Code open with a SyntaxError on line 12."     # markdown stripped
    user_msg = llm.calls[-1][-1]
    assert user_msg["images"] == ["BASE64IMAGE"] and llm.thinks[-1] is None


async def test_screen_without_vision_model_or_pillow(make, monkeypatch):
    import assistant as jmod
    from screen import ScreenError
    j, llm = make()
    llm.model = "qwen2.5-coder:3b"
    assert "can't see images" in (await j.handle_text("what's on my screen"))["reply"]
    llm.model = "qwen3.5:9b"

    def boom(max_side):
        raise ScreenError("Screen reading needs the Pillow package. Run setup.bat once to install it.")
    monkeypatch.setattr(jmod, "capture_screen", boom)
    assert "setup.bat" in (await j.handle_text("what does this error say"))["reply"]


def test_screen_phrase_detection():
    from screen import is_screen_question
    assert is_screen_question("can you see my screen")
    assert is_screen_question("What does this error say?")
    assert not is_screen_question("open the screen recorder")
    assert not is_screen_question("tell me a joke")


# ---------------------------------------------------------------- memory

@pytest.fixture
def jmem(dry_executor, tmp_path):
    from memory import MemoryStore
    mem = MemoryStore(tmp_path / "memory.db")

    def _make(rules=None):
        llm = FakeLLM(rules)
        return Assistant(llm, dry_executor, TelemetryCollector(), memory=mem), llm
    yield _make, mem
    mem.close()


async def test_remember_and_use_facts(jmem):
    make_j, mem = jmem
    j, llm = make_j()
    r = await j.handle_text("Remember that my games are on D:\\Games.")
    assert r["reply"] == "Got it, I'll remember that." and llm.calls == []
    assert mem.facts()[0]["text"] == "My games are on D:\\Games."
    await j.handle_text("where are my games installed?")
    system_msgs = [m["content"] for m in llm.calls[-1] if m["role"] == "system"]
    assert any("My games are on D:\\Games." in m for m in system_msgs)


async def test_recall_and_forget(jmem):
    make_j, mem = jmem
    j, llm = make_j()
    await j.handle_text("remember my favorite game is Deadlock")
    await j.handle_text("remember that my birthday is March 3")
    r = await j.handle_text("What do you remember?")
    assert "Deadlock" in r["reply"] and "March 3" in r["reply"] and llm.calls == []
    r = await j.handle_text("what do you remember about my birthday")
    assert r["data"]["facts"][0]["text"] == "My birthday is March 3."
    r = await j.handle_text("forget my birthday")
    assert r["reply"] == "Okay, I forgot: My birthday is March 3." and len(mem.facts()) == 1
    r = await j.handle_text("forget about my cat")
    assert r["status"] == "failed"
    # "what do you know about X" is a normal question for the AI, not a memory lookup
    await j.handle_text("what do you know about black holes")
    assert len(llm.calls) == 1


async def test_forget_everything_needs_confirmation(jmem):
    make_j, mem = jmem
    j, _ = make_j()
    await j.handle_text("remember that I like pizza")
    mem.add_routine("gaming time", ["open steam"])
    r = await j.handle_text("forget everything")
    assert r["status"] == "needs_confirmation" and len(mem.facts()) == 1
    r = await j.handle_text("yes")
    assert r["status"] == "done" and mem.facts() == [] and mem.count_conversations() <= 1
    assert len(mem.routines()) == 1                       # routines are kept


async def test_forget_it_cancels_a_question(jmem, monkeypatch):
    make_j, mem = jmem
    j, _ = make_j()
    await j.handle_text("remember that I like pizza")
    monkeypatch.setattr(j.executor, "find_processes", lambda q: {"Spotify.exe": [1]})
    await j.handle_text("close spotify")
    assert (await j.handle_text("forget it"))["status"] == "cancelled"
    assert len(mem.facts()) == 1


async def test_history_survives_restart_and_past_conversations(jmem):
    make_j, mem = jmem
    j, _ = make_j()
    await j.handle_text("who wrote hamlet")
    j2, llm2 = make_j()
    assert any(m["content"] == "who wrote hamlet" for m in j2.history)
    # an old conversation from yesterday
    import time as _t
    with mem._db:
        mem._db.execute("INSERT INTO conversations(ts, source, user_text, reply, intent) VALUES (?,?,?,?,?)",
                        (_t.time() - 86400 - 60, "voice", "how do I overclock my gpu", "Use MSI Afterburner.", "chat"))
    await j2.handle_text("what did we talk about yesterday")
    sys_msgs = [m["content"] for m in llm2.calls[-1] if m["role"] == "system"]
    assert any("MSI Afterburner" in m for m in sys_msgs)


# ---------------------------------------------------------------- routines

async def test_create_and_run_routine(jmem):
    make_j, mem = jmem
    j, llm = make_j({"when i say": {"intent": "create_routine", "target": "gaming time", "browser": "", "site": "",
                                    "steps": ["open steam", "open discord", "volume up"], "reply": "",
                                    "confidence": 0.95}})
    r = await j.handle_text("When I say gaming time, open Steam and Discord and turn the volume up")
    assert r["reply"] == "Got it. When you say gaming time, I'll open steam, open discord and volume up."
    calls = len(llm.calls)
    r = await j.handle_text("Gaming time!")
    assert len(llm.calls) == calls and r["via"] == "routine" and r["status"] == "done"
    assert [s["status"] for s in r["data"]["steps"]] == ["done", "done", "done"]
    assert r["reply"] == "Running gaming time. Opening Steam. Opening Discord. Volume up."
    r = await j.handle_text("what routines do I have")
    assert "gaming time" in r["reply"]
    r = await j.handle_text("delete the gaming time routine")
    assert r["status"] == "done" and mem.routines() == []


async def test_routine_with_confirmation_step_and_no_recursion(jmem, monkeypatch):
    make_j, mem = jmem
    j, _ = make_j()
    monkeypatch.setattr(j.executor, "find_processes", lambda q: {"Discord.exe": [5]})
    mem.add_routine("bed time", ["bed time", "volume down", "close discord"])   # first step = itself
    r = await j.handle_text("bed time")
    assert r["status"] == "needs_confirmation" and r["pending_id"]
    assert r["data"]["steps"][0]["status"] != "done" or "Running" not in r["data"]["steps"][0]["reply"]
    assert (await j.handle_text("yes"))["status"] == "done"


async def test_routine_needs_steps(jmem):
    make_j, mem = jmem
    j, _ = make_j({"when i say": {"intent": "create_routine", "target": "movie night", "browser": "", "site": "",
                                  "steps": [], "reply": "", "confidence": 0.9}})
    r = await j.handle_text("when I say movie night")
    assert r["status"] == "needs_clarification" and mem.routines() == []


def test_wake_name_is_stripped_from_commands():
    from assistant import OPEN_RE, REMEMBER_RE
    for said in ("hey kageon open notepad", "kageon open notepad", "hey kage on open notepad", "open notepad"):
        m = OPEN_RE.match(said)
        assert m and m.group("t") == "notepad", said
    assert REMEMBER_RE.match("hey kageon remember that my desk is white").group("t") == "my desk is white"
