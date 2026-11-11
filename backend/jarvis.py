"""
JARVIS agent: natural language -> structured intent -> safe execution.

Speed:
  * Simple, unambiguous commands ("open notepad", "open youtube in chrome", "close spotify",
    "volume up", "yes"/"no") are understood instantly by local rules -- no LLM round-trip.
  * Everything else goes to the local Ollama model with a strict JSON schema.

Safety model (enforced in code, never left to the LLM):
  * The LLM may only choose from a fixed list of intents (JSON-schema constrained output).
  * Risky intents (close apps, sleep, shutdown, restart) ALWAYS require confirmation.
  * Ambiguous app names return the candidates and ask which one -- no guessing.
  * Low-confidence interpretations of actions are confirmed before running.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from executor import ActionResult, AppEntry, Executor, normalize, resolve_browser, resolve_site
from llm import LLMError, OllamaClient
from telemetry import TelemetryCollector

log = logging.getLogger("jarvis")

INTENTS = [
    "chat", "open_app", "close_app", "open_url", "web_search", "media_control", "system_stats",
    "lock_pc", "sleep_pc", "shutdown_pc", "restart_pc", "cancel_shutdown", "confirm", "deny", "unknown",
]
MEDIA_TARGETS = ["play_pause", "next", "previous", "stop", "mute", "volume_up", "volume_down"]

INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": INTENTS},
        "target": {"type": "string"},
        "browser": {"type": "string"},
        "reply": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["intent", "target", "browser", "reply", "confidence"],
}

SYSTEM_PROMPT = f"""You are JARVIS, a concise, witty, helpful AI assistant that controls a Windows PC.
Convert every user message into ONE JSON object: {{"intent", "target", "browser", "reply", "confidence"}}.

Intents:
- chat: questions/conversation. "reply" = your full answer (max 3 short sentences, it will be spoken aloud).
- open_app: open/launch/start programs or games. target = app name(s) exactly as said, comma-separated if several.
- open_url: open websites (youtube, instagram, whatsapp web, any domain). target = site name(s) or domain(s),
  comma-separated if several. If the user names a browser ("on chrome", "in edge"), put it in "browser".
- close_app: close/quit/kill a program. target = app name.
- web_search: search the internet. target = the search query. browser = browser if named.
- media_control: target is one of {MEDIA_TARGETS}.
- system_stats: user asks about CPU / GPU / RAM / performance / temperature.
- lock_pc, sleep_pc, shutdown_pc, restart_pc, cancel_shutdown: target = "".
- confirm / deny: the user answers yes / no to a question you just asked.
- unknown: the request is unclear or impossible. "reply" = a short clarifying question.

Rules:
- "browser" is "" unless the user explicitly names a browser. Never put the browser in "target".
- "reply" for actions = a very short spoken acknowledgement.
- Always write "reply" in the SAME language the user used (Arabic -> Arabic, English -> English).
- confidence = 0..1, how sure you are about the intent and target. Never invent targets.
- Only output the JSON object.

Examples:
User: open chrome -> {{"intent":"open_app","target":"chrome","browser":"","reply":"Opening Chrome.","confidence":0.97}}
User: open youtube, instagram and whatsapp on google chrome -> {{"intent":"open_url","target":"youtube, instagram, whatsapp","browser":"chrome","reply":"Opening them in Chrome.","confidence":0.95}}
User: افتح يوتيوب في كروم -> {{"intent":"open_url","target":"youtube","browser":"chrome","reply":"جاري فتح يوتيوب.","confidence":0.95}}
User: افتح سبوتيفاي -> {{"intent":"open_app","target":"سبوتيفاي","browser":"","reply":"جاري فتح سبوتيفاي.","confidence":0.95}}
User: search for the weather in riyadh -> {{"intent":"web_search","target":"weather in riyadh","browser":"","reply":"Searching.","confidence":0.95}}
User: turn the volume up -> {{"intent":"media_control","target":"volume_up","browser":"","reply":"Volume up.","confidence":0.95}}
User: how hot is my gpu -> {{"intent":"system_stats","target":"","browser":"","reply":"Checking.","confidence":0.9}}
User: shut down the computer -> {{"intent":"shutdown_pc","target":"","browser":"","reply":"Shutting down.","confidence":0.95}}
User: who wrote hamlet -> {{"intent":"chat","target":"","browser":"","reply":"William Shakespeare wrote Hamlet.","confidence":0.99}}
User: do the thing -> {{"intent":"unknown","target":"","browser":"","reply":"Which thing would you like me to do?","confidence":0.2}}
"""

# ------------------------------------------------------------------ language helpers

_ARABIC = re.compile(r"[؀-ۿ]")


def detect_lang(text: str) -> str:
    return "ar" if _ARABIC.search(text or "") else "en"


MESSAGES = {
    "opening": {"en": "Opening {name}.", "ar": "جاري فتح {name}."},
    "opening_in": {"en": "Opening {name} in {browser}.", "ar": "جاري فتح {name} في {browser}."},
    "ambiguous": {"en": "I found several matches for {q}: {opts}. Which one do you mean?",
                  "ar": "وجدت أكثر من تطابق لـ {q}: {opts}. أيها تقصد؟"},
    "not_found": {"en": "I couldn't find {q}.", "ar": "لم أجد {q}."},
    "nothing_to_close": {"en": "{q} doesn't seem to be running.", "ar": "{q} غير مفتوح حالياً."},
    "confirm_close": {"en": "Are you sure you want to close {desc}?", "ar": "هل أنت متأكد أنك تريد إغلاق {desc}؟"},
    "closed": {"en": "Done, {desc} is closed.", "ar": "تم إغلاق {desc}."},
    "confirm_power": {"en": "Are you sure you want me to {action}?", "ar": "هل أنت متأكد أنك تريد {action}؟"},
    "confirm_low": {"en": "Just to be sure: {action}?", "ar": "للتأكيد: {action}؟"},
    "cancelled": {"en": "Okay, cancelled.", "ar": "تم الإلغاء."},
    "no_pending": {"en": "There's nothing waiting for confirmation.", "ar": "لا يوجد شيء بانتظار التأكيد."},
    "expired": {"en": "That request expired. Please ask again.", "ar": "انتهت صلاحية الطلب، اطلبه مرة أخرى."},
    "llm_down": {"en": "My AI engine is unavailable: {err}", "ar": "محرك الذكاء الاصطناعي غير متاح: {err}"},
    "unclear": {"en": "Sorry, I didn't catch that. Could you rephrase?", "ar": "عذراً، لم أفهم. هل يمكنك إعادة الصياغة؟"},
    "bad_url": {"en": "That doesn't look like a valid website.", "ar": "هذا لا يبدو كموقع صحيح."},
    "yes_or_no": {"en": "Please answer yes or no.", "ar": "من فضلك أجب بنعم أو لا."},
}

POWER_ACTIONS = {
    "sleep_pc": {"en": "put the PC to sleep", "ar": "وضع الجهاز في وضع السكون"},
    "shutdown_pc": {"en": "shut down the PC", "ar": "إيقاف تشغيل الجهاز"},
    "restart_pc": {"en": "restart the PC", "ar": "إعادة تشغيل الجهاز"},
}

MEDIA_REPLIES = {
    "volume_up": {"en": "Volume up.", "ar": "رفعت الصوت."},
    "volume_down": {"en": "Volume down.", "ar": "خفضت الصوت."},
    "mute": {"en": "Muted.", "ar": "تم كتم الصوت."},
    "play_pause": {"en": "Done.", "ar": "تم."},
    "stop": {"en": "Stopped.", "ar": "تم الإيقاف."},
    "next": {"en": "Next track.", "ar": "المقطع التالي."},
    "previous": {"en": "Previous track.", "ar": "المقطع السابق."},
}

BROWSER_NAMES = {"chrome.exe": "Chrome", "msedge.exe": "Edge", "firefox.exe": "Firefox",
                 "brave.exe": "Brave", "opera.exe": "Opera"}

# ------------------------------------------------------------------ yes / no understanding

YES_PHRASES = {"yes", "yeah", "yep", "yup", "ya", "yes please", "sure", "confirm", "confirmed", "do it",
               "go ahead", "proceed", "ok", "okay", "affirmative", "of course", "absolutely", "please do",
               "yes sir", "correct", "right", "close it", "نعم", "اي", "ايه", "إي", "أكد", "اكد", "تمام",
               "موافق", "اوكي", "أوكي", "يب", "اكيد", "أكيد", "طيب", "سوها", "كمل", "أكمل", "اكمل", "صح"}
YES_FIRST = {"yes", "yeah", "yep", "yup", "ya", "sure", "ok", "okay", "confirm", "absolutely", "definitely",
             "نعم", "اي", "ايه", "إي", "أكيد", "اكيد", "تمام", "اوكي", "أوكي", "يب", "موافق", "طيب"}
NO_PHRASES = {"no", "nope", "nah", "cancel", "stop", "never mind", "nevermind", "dont", "don t", "abort",
              "no thanks", "لا", "الغ", "إلغاء", "الغاء", "وقف", "لا تسوي", "خلاص", "لا شكرا", "لاء"}
NO_FIRST = {"no", "nope", "nah", "cancel", "dont", "don", "stop", "abort", "لا", "الغ", "إلغاء", "الغاء", "لاء"}
NEGATIONS = {"not", "dont", "don", "no", "never", "لا", "ما", "مو"}

ORDINALS = {"1": 0, "one": 0, "first": 0, "the first one": 0, "first one": 0, "الأول": 0, "الاول": 0, "واحد": 0,
            "2": 1, "two": 1, "second": 1, "the second one": 1, "second one": 1, "الثاني": 1, "اثنين": 1,
            "3": 2, "three": 2, "third": 2, "the third one": 2, "third one": 2, "الثالث": 2, "ثلاثة": 2}


def yes_or_no(text: str) -> bool | None:
    """True = yes, False = no, None = not a yes/no answer. Tolerant of 'Yes, close it.' etc."""
    norm = normalize(text)
    if not norm:
        return None
    if norm in YES_PHRASES:
        return True
    if norm in NO_PHRASES:
        return False
    words = norm.split()
    if words[0] in NO_FIRST:
        return False
    if words[0] in YES_FIRST and not (set(words[1:]) & NEGATIONS):
        return True
    return None


# ------------------------------------------------------------------ fast local command rules

_WAKE_PREFIX = r"^(?:(?:hey|hi|ok|okay|yo)\s+)?(?:jarvis\s+)?(?:(?:هاي|يا)\s+)?(?:جارفس\s+)?"
_POLITE = r"(?:please\s+|can you\s+|could you\s+|would you\s+|لو سمحت\s+|ممكن\s+)?"
OPEN_RE = re.compile(_WAKE_PREFIX + _POLITE + r"(?:open|launch|start|run|go to|افتح|افتحي|افتحلي|شغل|شغلي|شغّل|ودني)"
                     r"\s+(?:لي\s+|up\s+)?(?P<t>.+?)(?:\s+please|\s+لو سمحت)?$")
CLOSE_RE = re.compile(_WAKE_PREFIX + _POLITE + r"(?:close|quit|exit|kill|سكر|سكّر|اقفل|أقفل|اغلق|أغلق|طفي)"
                      r"\s+(?P<t>.+?)(?:\s+please|\s+لو سمحت)?$")
BROWSER_SUFFIX_RE = re.compile(
    r"\s+(?:on|in|using|with|via|في|على|عن طريق)\s+(?:the\s+)?(?:browser\s+)?(?P<b>google chrome|chrome|microsoft edge|edge|"
    r"firefox|brave|opera gx|opera|قوقل كروم|كروم|ايدج|فايرفوكس)(?:\s+browser)?$|\s+ب(?P<b2>كروم|ايدج|فايرفوكس)$")
MEDIA_PHRASES = {
    "volume_up": {"volume up", "turn up the volume", "turn the volume up", "louder", "increase the volume",
                  "raise the volume", "ارفع الصوت", "علي الصوت", "على الصوت", "زيد الصوت"},
    "volume_down": {"volume down", "turn down the volume", "turn the volume down", "quieter", "lower the volume",
                    "decrease the volume", "نزل الصوت", "وطي الصوت", "اخفض الصوت", "قلل الصوت"},
    "mute": {"mute", "unmute", "mute the sound", "mute the volume", "اكتم الصوت", "كتم الصوت", "اسكت"},
    "play_pause": {"pause", "play", "resume", "pause the music", "play the music", "pause music", "play music",
                   "شغل الموسيقى", "وقف الموسيقى", "كمل الاغنية"},
    "next": {"next", "next song", "next track", "skip", "skip this song", "skip song", "الاغنية الجاية", "الأغنية التالية",
             "الاغنية التالية", "التالي"},
    "previous": {"previous", "previous song", "previous track", "go back a song", "الاغنية السابقة", "الأغنية السابقة", "السابق"},
}
_MEDIA_LOOKUP = {normalize(p): k for k, ps in MEDIA_PHRASES.items() for p in ps}


def soft_normalize(text: str) -> str:
    """Like normalize() but keeps commas, so lists like 'youtube, instagram' survive."""
    text = (text or "").lower().replace("،", ",").replace("&", " and ")
    text = re.sub(r"[^\w\s+,]", " ", text)
    text = re.sub(r"\s*,\s*", ", ", text)
    return re.sub(r"\s+", " ", text).strip(" ,")


def split_browser(target: str) -> tuple[str, str]:
    """'youtube on google chrome' -> ('youtube', 'google chrome')."""
    t = soft_normalize(target)
    m = BROWSER_SUFFIX_RE.search(t)
    if m:
        return t[: m.start()].strip(), (m.group("b") or m.group("b2"))
    return t, ""


def split_targets(target: str, known: Callable[[str], bool]) -> list[str]:
    """'youtube, instagram and whatsapp' / 'يوتيوب وانستقرام وواتساب' -> ['youtube', 'instagram', 'whatsapp']."""
    parts = re.split(r"\s*(?:,|\band\b|\bplus\b)\s*|\s+و\s+", soft_normalize(target))
    out: list[str] = []
    for part in (normalize(p) for p in parts):
        if not part:
            continue
        # "instagram whatsapp" (speech often has no commas): split into words if each word is known
        words = part.split()
        if len(words) > 1 and not known(part) and all(known(w) for w in words):
            out.extend(words)
            continue
        # Arabic "و" glued to the next word: "يوتيوب وانستقرام" -> split only if that makes both known
        words, cur = part.split(), []
        for w in words:
            if cur and w.startswith("و") and len(w) > 2 and known(w[1:]) and not known(w):
                out.append(" ".join(cur))
                cur = [w[1:]]
            else:
                cur.append(w)
        if cur:
            out.append(" ".join(cur))
    return out


def join_names(names: list[str], lang: str) -> str:
    if len(names) <= 1:
        return "".join(names)
    if lang == "ar":
        return "، ".join(names[:-1]) + " و" + names[-1]
    return ", ".join(names[:-1]) + " and " + names[-1]


def msg(key: str, lang: str, **kw) -> str:
    return MESSAGES[key].get(lang, MESSAGES[key]["en"]).format(**kw)


# ------------------------------------------------------------------ pending actions


@dataclass
class Pending:
    id: str
    kind: str                                  # "confirm" | "choose"
    intent: str
    target: str
    lang: str
    question: str = ""
    run: Callable[[], ActionResult] | None = None
    done_reply: str = ""
    options: list = field(default_factory=list)      # for "choose": list[AppEntry]
    created: float = field(default_factory=time.time)


Listener = Callable[[dict], Awaitable[None]]


class Jarvis:
    def __init__(self, llm: OllamaClient, executor: Executor, telemetry: TelemetryCollector,
                 confirm_timeout: int = 60, history_turns: int = 6, fast_commands: bool = True):
        self.llm = llm
        self.executor = executor
        self.telemetry = telemetry
        self.confirm_timeout = confirm_timeout
        self.fast_commands = fast_commands
        self.history: list[dict] = []
        self.history_turns = history_turns
        self.pending: dict[str, Pending] = {}
        self._lock = asyncio.Lock()
        self._listeners: list[Listener] = []

    # ---------------- public API
    def add_listener(self, fn: Listener) -> None:
        self._listeners.append(fn)

    def has_pending(self) -> bool:
        return self._latest_pending() is not None

    async def handle_text(self, text: str, source: str = "text") -> dict:
        text = (text or "").strip()
        t0 = time.perf_counter()
        async with self._lock:
            if not text:
                resp = self._response(text, source, "en", "unknown", "", msg("unclear", "en"), "failed")
            else:
                resp = await self._handle(text, source)
        resp["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
        log.info("Handled in %.2fs via %s -> %s", resp["elapsed_ms"] / 1000, resp.get("via", "?"), resp["status"])
        await self._emit(resp)
        return resp

    async def confirm(self, pending_id: str, approve: bool, source: str = "tablet",
                      choice: int | None = None) -> dict:
        async with self._lock:
            resp = await asyncio.to_thread(self._resolve_pending, pending_id, approve, source, choice, "")
        await self._emit(resp)
        return resp

    # ---------------- internals
    async def _emit(self, resp: dict) -> None:
        for fn in list(self._listeners):
            try:
                await fn(resp)
            except Exception as exc:
                log.debug("listener failed: %s", exc)

    def _response(self, user_text, source, lang, intent, target, reply, status, **extra) -> dict:
        r = {
            "id": uuid.uuid4().hex[:12], "source": source, "user_text": user_text, "lang": lang,
            "intent": intent, "target": target, "reply": reply, "status": status,
            "pending_id": None, "options": [], "data": {}, "timestamp": time.time(),
        }
        r.update(extra)
        return r

    def _expire_pending(self) -> None:
        now = time.time()
        for pid in [k for k, p in self.pending.items() if now - p.created > self.confirm_timeout]:
            self.pending.pop(pid, None)

    def _latest_pending(self) -> Pending | None:
        self._expire_pending()
        return max(self.pending.values(), key=lambda p: p.created) if self.pending else None

    async def _handle(self, text: str, source: str) -> dict:
        lang = detect_lang(text)

        # 1) answers to a pending confirmation / choice (no LLM round-trip needed)
        pend = self._latest_pending()
        if pend:
            yn = yes_or_no(text)
            if pend.kind == "choose":
                idx = self._pick_option(normalize(text), pend)
                if idx is not None:
                    return self._via(await asyncio.to_thread(self._resolve_pending, pend.id, True, source, idx, text), "rules")
                if yn is False:
                    return self._via(await asyncio.to_thread(self._resolve_pending, pend.id, False, source, None, text), "rules")
            elif yn is not None:
                return self._via(await asyncio.to_thread(self._resolve_pending, pend.id, yn, source, None, text), "rules")

        # 2) instant local rules for simple commands
        if self.fast_commands:
            fast = await asyncio.to_thread(self._fast_intent, text)
            if fast:
                log.info("Fast intent: %s target=%r browser=%r", fast["intent"], fast["target"], fast["browser"])
                return self._via(await asyncio.to_thread(self._dispatch, text, source, lang, fast), "rules")

        # 3) ask the local LLM for a structured intent
        t0 = time.perf_counter()
        try:
            raw = await self.llm.chat(self._messages(text, pend), schema=INTENT_SCHEMA)
        except LLMError as exc:
            return self._via(self._response(text, source, lang, "unknown", "", msg("llm_down", lang, err=str(exc)), "error"), "llm")
        log.info("LLM answered in %.2fs", time.perf_counter() - t0)
        parsed = self._parse(raw)
        if parsed is None:
            log.warning("Unparseable LLM output: %r", raw[:300])
            return self._via(self._response(text, source, lang, "unknown", "", msg("unclear", lang), "failed"), "llm")

        self._remember(text, parsed)
        log.info("Intent: %s target=%r browser=%r conf=%.2f (%s)", parsed["intent"], parsed["target"],
                 parsed["browser"], parsed["confidence"], source)
        return self._via(await asyncio.to_thread(self._dispatch, text, source, lang, parsed), "llm")

    @staticmethod
    def _via(resp: dict, via: str) -> dict:
        resp["via"] = via
        return resp

    def _messages(self, text: str, pend: Pending | None) -> list[dict]:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}, *self.history]
        if pend:
            msgs.append({"role": "system", "content":
                         f'You just asked the user: "{pend.question}". If the reply agrees, use intent "confirm"; '
                         f'if it refuses, use intent "deny"; if it is a different request, handle it normally.'})
        msgs.append({"role": "user", "content": text})
        return msgs

    def _remember(self, text: str, parsed: dict) -> None:
        self.history += [{"role": "user", "content": text},
                         {"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)}]
        self.history = self.history[-self.history_turns * 2:]

    @staticmethod
    def _parse(raw: str) -> dict | None:
        data = None
        try:
            data = json.loads(raw)
        except Exception:
            m = re.search(r"\{.*\}", raw or "", re.S)
            if m:
                try:
                    data = json.loads(m.group(0))
                except Exception:
                    data = None
        if not isinstance(data, dict):
            return None
        intent = str(data.get("intent", "unknown")).strip().lower()
        if intent not in INTENTS:
            intent = "unknown"
        try:
            conf = float(data.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        return {"intent": intent, "target": str(data.get("target") or "").strip(),
                "browser": str(data.get("browser") or "").strip(),
                "reply": str(data.get("reply") or "").strip(), "confidence": max(0.0, min(conf, 1.0))}

    # ---------------- fast rules
    def _is_known_target(self, name: str) -> bool:
        return resolve_site(name) is not None or self.executor.apps.match(name).status != "none"

    def _fast_intent(self, text: str) -> dict | None:
        norm = normalize(text)
        base = {"browser": "", "reply": "", "confidence": 1.0}

        media = _MEDIA_LOOKUP.get(norm)
        if media:
            return {**base, "intent": "media_control", "target": media}

        m = OPEN_RE.match(soft_normalize(text))
        if m:
            target, browser = split_browser(m.group("t"))
            if browser and not resolve_browser(browser):
                return None
            self.executor.apps.refresh_if_stale()
            targets = split_targets(target, self._is_known_target)
            if not targets:
                return None
            for t in targets:
                if resolve_site(t):
                    continue
                if browser or self.executor.apps.match(t).status == "none":
                    return None          # unknown thing -> let the LLM interpret it
            return {**base, "intent": "open_app", "target": ", ".join(targets), "browser": browser}

        m = CLOSE_RE.match(soft_normalize(text))
        if m:
            target = m.group("t")
            if self.executor.find_processes(target):
                return {**base, "intent": "close_app", "target": target}
        return None

    # ---------------- dispatch (runs in a worker thread: may touch Windows APIs)
    def _dispatch(self, text: str, source: str, lang: str, p: dict) -> dict:
        intent, target, browser, reply, conf = p["intent"], p["target"], p["browser"], p["reply"], p["confidence"]
        R = lambda reply_, status, **kw: self._response(text, source, lang, intent, target, reply_, status, **kw)
        ex = self.executor

        if intent == "chat":
            return R(reply or msg("unclear", lang), "chat")
        if intent == "unknown":
            return R(reply or msg("unclear", lang), "needs_clarification")
        if intent in ("confirm", "deny"):
            pend = self._latest_pending()
            if not pend:
                return R(msg("no_pending", lang), "failed")
            if pend.kind == "choose" and intent == "confirm":
                idx = self._pick_option(normalize(target), pend) if target else None
                if idx is None:
                    return R(pend.question, "needs_choice", pending_id=pend.id, options=[e.name for e in pend.options])
                return self._resolve_pending(pend.id, True, source, idx, text)
            return self._resolve_pending(pend.id, intent == "confirm", source, None, text)
        if intent == "system_stats":
            snap = self.telemetry.snapshot()
            return R(self.telemetry.spoken_summary(), "done", data={"telemetry": snap})

        # ---------- open apps and/or websites (several at once is fine)
        if intent in ("open_app", "open_url"):
            if not target:
                return R(msg("unclear", lang), "needs_clarification")
            return self._open_targets(R, lang, target, browser, prefer_sites=(intent == "open_url"), conf=conf)

        # ---------- close_app: always confirm, show exactly what will be closed
        if intent == "close_app":
            procs = ex.find_processes(target)
            if not procs:
                return R(msg("nothing_to_close", lang, q=target or "?"), "failed")
            pids = [pid for lst in procs.values() for pid in lst]
            desc = join_names([name.removesuffix(".exe").removesuffix(".EXE") for name in procs], lang)
            return self._ask_confirm(R, intent, target, lang, lambda: ex.close_processes(pids, desc),
                                     msg("confirm_close", lang, desc=desc), done_reply=msg("closed", lang, desc=desc),
                                     data={"processes": procs})

        # ---------- power: always confirm
        if intent in POWER_ACTIONS:
            fn = {"sleep_pc": ex.sleep_pc, "shutdown_pc": ex.shutdown_pc, "restart_pc": ex.restart_pc}[intent]
            action = POWER_ACTIONS[intent][lang]
            return self._ask_confirm(R, intent, target, lang, fn, msg("confirm_power", lang, action=action))

        # ---------- other safe actions
        if intent == "web_search":
            run = lambda: ex.web_search(target or text, browser or None)
        elif intent == "media_control":
            if target not in MEDIA_TARGETS:
                return R(msg("unclear", lang), "needs_clarification")
            run = lambda: ex.media(target)
            reply = MEDIA_REPLIES[target][lang] if not reply or p.get("confidence", 0) >= 1.0 else reply
        elif intent == "lock_pc":
            run = ex.lock_pc
            reply = reply or {"en": "Locking the PC.", "ar": "جاري قفل الجهاز."}[lang]
        elif intent == "cancel_shutdown":
            run = ex.cancel_shutdown
        else:
            return R(msg("unclear", lang), "needs_clarification")

        if conf < 0.5:
            return self._ask_confirm(R, intent, target, lang, run,
                                     msg("confirm_low", lang, action=reply or f"{intent} {target}"))
        return self._result(R, run(), reply)

    def _open_targets(self, R, lang: str, target: str, browser: str, prefer_sites: bool, conf: float) -> dict:
        ex = self.executor
        target, inline_browser = split_browser(target)
        browser = browser or inline_browser
        if browser and not resolve_browser(browser):
            browser = ""
        ex.apps.refresh_if_stale()
        targets = split_targets(target, self._is_known_target)

        apps: list[AppEntry] = []
        sites: list[tuple[str, str]] = []
        missing: list[str] = []
        ambiguous = None
        for t in targets:
            site = resolve_site(t)
            if browser or (prefer_sites and site):
                if site:
                    sites.append(site)
                else:
                    missing.append(t)
                continue
            m = ex.apps.match(t)
            if m.status == "none" and not site:
                ex.apps.refresh()               # maybe it was just installed
                m = ex.apps.match(t)
            if m.status == "match":
                apps.append(m.best)
            elif site:
                sites.append(site)
            elif m.status == "ambiguous" and ambiguous is None:
                ambiguous = (t, [e for e, _ in m.candidates[:3]])
            else:
                missing.append(t)

        if not apps and not sites:
            if ambiguous:
                return self._ask_choice(R, "open_app", ambiguous[0], lang, ambiguous[1])
            return R(msg("not_found", lang, q=join_names(missing or targets, lang)), "failed")

        names = [a.name for a in apps] + [s[0] for s in sites]
        browser_name = BROWSER_NAMES.get(resolve_browser(browser) or "", browser.title() if browser else "")
        reply = (msg("opening_in", lang, name=join_names(names, lang), browser=browser_name) if browser and sites
                 else msg("opening", lang, name=join_names(names, lang)))

        def run_all() -> ActionResult:
            results = [ex.launch_entry(a) for a in apps]
            if sites:
                results.append(ex.open_urls([u for _, u in sites], browser or None))
            ok = all(r.ok for r in results)
            data = {"apps": [a.to_dict() for a in apps], "urls": [u for _, u in sites], "browser": browser or None,
                    "dry_run": any(r.data.get("dry_run") for r in results)}
            if apps:
                data["app"] = apps[0].to_dict()
            if sites:
                data["url"] = sites[0][1]
            return ActionResult(ok, reply if ok else "; ".join(r.message for r in results if not r.ok), data)

        if conf < 0.5:
            return self._ask_confirm(R, "open_app", target, lang, run_all,
                                     msg("confirm_low", lang, action=reply.rstrip(".")), done_reply=reply)
        res = run_all()
        if missing:
            res.message += " " + msg("not_found", lang, q=join_names(missing, lang))
        if ambiguous:
            follow = self._ask_choice(R, "open_app", ambiguous[0], lang, ambiguous[1])
            follow["reply"] = res.message + " " + follow["reply"]
            follow["data"].update(res.data)
            return follow
        return R(res.message, "done" if res.ok else "failed", data=res.data)

    def _result(self, R, res: ActionResult, ok_reply: str) -> dict:
        if res.ok:
            return R(ok_reply or res.message, "done", data=res.data)
        return R(res.message, "failed", data=res.data)

    def _ask_confirm(self, R, intent, target, lang, run, question, data=None, done_reply: str = "") -> dict:
        self._expire_pending()
        self.pending.clear()                      # only one open question at a time
        p = Pending(uuid.uuid4().hex[:12], "confirm", intent, target, lang, question=question, run=run,
                    done_reply=done_reply)
        self.pending[p.id] = p
        return R(question, "needs_confirmation", pending_id=p.id, data=data or {})

    def _ask_choice(self, R, intent, target, lang, entries) -> dict:
        self._expire_pending()
        self.pending.clear()
        names = [e.name for e in entries]
        question = msg("ambiguous", lang, q=target, opts=join_names(names, lang))
        p = Pending(uuid.uuid4().hex[:12], "choose", intent, target, lang, question=question, options=entries)
        self.pending[p.id] = p
        return R(question, "needs_choice", pending_id=p.id, options=names)

    def _pick_option(self, norm: str, pend: Pending) -> int | None:
        if norm in ORDINALS and ORDINALS[norm] < len(pend.options):
            return ORDINALS[norm]
        for i, e in enumerate(pend.options):
            if norm == e.norm or (len(norm) >= 3 and norm in e.norm):
                return i
        return None

    def _resolve_pending(self, pending_id: str, approve: bool, source: str, choice: int | None, user_text: str) -> dict:
        self._expire_pending()
        p = self.pending.pop(pending_id, None)
        if not p:
            lang = detect_lang(user_text)
            return self._response(user_text, source, lang, "confirm", "", msg("expired", lang), "failed")
        R = lambda reply, status, **kw: self._response(user_text, source, p.lang, p.intent, p.target, reply, status, **kw)
        if not approve:
            return R(msg("cancelled", p.lang), "cancelled")
        if p.kind == "choose":
            if choice is None or not (0 <= choice < len(p.options)):
                self.pending[p.id] = p      # keep waiting for a valid choice
                return R(p.question, "needs_choice", pending_id=p.id, options=[e.name for e in p.options])
            entry = p.options[choice]
            return self._result(R, self.executor.launch_entry(entry), msg("opening", p.lang, name=entry.name))
        res = p.run()
        return self._result(R, res, p.done_reply or res.message)
