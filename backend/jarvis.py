"""
JARVIS agent: natural language -> structured intent (via local Ollama) -> safe execution.

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

from executor import ActionResult, Executor, normalize
from llm import LLMError, OllamaClient
from telemetry import TelemetryCollector

log = logging.getLogger("jarvis")

INTENTS = [
    "chat", "open_app", "close_app", "open_url", "web_search", "media_control", "system_stats",
    "lock_pc", "sleep_pc", "shutdown_pc", "restart_pc", "cancel_shutdown", "unknown",
]
RISKY_INTENTS = {"close_app", "sleep_pc", "shutdown_pc", "restart_pc"}
ACTION_INTENTS = set(INTENTS) - {"chat", "unknown", "system_stats"}
MEDIA_TARGETS = ["play_pause", "next", "previous", "stop", "mute", "volume_up", "volume_down"]

INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": INTENTS},
        "target": {"type": "string"},
        "reply": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["intent", "target", "reply", "confidence"],
}

SYSTEM_PROMPT = f"""You are JARVIS, a concise, witty, helpful AI assistant that controls a Windows PC.
Convert every user message into ONE JSON object: {{"intent", "target", "reply", "confidence"}}.

Intents:
- chat: questions/conversation. "reply" = your full answer (max 3 short sentences, it will be spoken aloud). target = "".
- open_app: open/launch/start a program or game. target = the app name exactly as the user said it (never a path).
- close_app: close/quit/kill a program. target = app name.
- open_url: open a website. target = the domain or URL (e.g. "youtube.com").
- web_search: search the internet. target = the search query.
- media_control: target is one of {MEDIA_TARGETS}.
- system_stats: user asks about CPU / GPU / RAM / performance / temperature. target = "".
- lock_pc, sleep_pc, shutdown_pc, restart_pc, cancel_shutdown: target = "".
- unknown: the request is unclear or impossible. "reply" = a short clarifying question.

Rules:
- "reply" for actions = a very short spoken acknowledgement (e.g. "Opening Spotify.").
- Always write "reply" in the SAME language the user used (Arabic -> Arabic, English -> English).
- confidence = 0..1, how sure you are about the intent and target. Never invent targets.
- Only output the JSON object.

Examples:
User: open chrome -> {{"intent":"open_app","target":"chrome","reply":"Opening Chrome.","confidence":0.97}}
User: افتح سبوتيفاي -> {{"intent":"open_app","target":"سبوتيفاي","reply":"جاري فتح سبوتيفاي.","confidence":0.95}}
User: turn the volume up -> {{"intent":"media_control","target":"volume_up","reply":"Volume up.","confidence":0.95}}
User: how hot is my gpu -> {{"intent":"system_stats","target":"","reply":"Checking your system.","confidence":0.9}}
User: shut down the computer -> {{"intent":"shutdown_pc","target":"","reply":"Shutting down.","confidence":0.95}}
User: who wrote hamlet -> {{"intent":"chat","target":"","reply":"Hamlet was written by William Shakespeare.","confidence":0.99}}
User: do the thing -> {{"intent":"unknown","target":"","reply":"Which thing would you like me to do?","confidence":0.2}}
"""

# ------------------------------------------------------------------ language helpers

_ARABIC = re.compile(r"[؀-ۿ]")


def detect_lang(text: str) -> str:
    return "ar" if _ARABIC.search(text or "") else "en"


MESSAGES = {
    "opening": {"en": "Opening {name}.", "ar": "جاري فتح {name}."},
    "ambiguous": {"en": "I found several matches: {opts}. Which one do you mean?",
                  "ar": "وجدت أكثر من تطابق: {opts}. أيها تقصد؟"},
    "not_found": {"en": "I couldn't find an app called {q}.", "ar": "لم أجد برنامجاً باسم {q}."},
    "nothing_to_close": {"en": "{q} doesn't seem to be running.", "ar": "{q} غير مفتوح حالياً."},
    "confirm_close": {"en": "This will close {desc}. Should I go ahead?", "ar": "سيتم إغلاق {desc}. هل أتابع؟"},
    "confirm_power": {"en": "Are you sure you want me to {action}?", "ar": "هل أنت متأكد أنك تريد {action}؟"},
    "confirm_low": {"en": "Just to be sure: {action}?", "ar": "للتأكيد: {action}؟"},
    "cancelled": {"en": "Okay, cancelled.", "ar": "تم الإلغاء."},
    "no_pending": {"en": "There's nothing waiting for confirmation.", "ar": "لا يوجد شيء بانتظار التأكيد."},
    "expired": {"en": "That request expired. Please ask again.", "ar": "انتهت صلاحية الطلب، اطلبه مرة أخرى."},
    "llm_down": {"en": "My AI engine is unavailable: {err}", "ar": "محرك الذكاء الاصطناعي غير متاح: {err}"},
    "unclear": {"en": "Sorry, I didn't catch that. Could you rephrase?", "ar": "عذراً، لم أفهم. هل يمكنك إعادة الصياغة؟"},
    "bad_url": {"en": "That doesn't look like a valid website.", "ar": "هذا لا يبدو كموقع صحيح."},
}

POWER_ACTIONS = {
    "sleep_pc": {"en": "put the PC to sleep", "ar": "وضع الجهاز في وضع السكون"},
    "shutdown_pc": {"en": "shut down the PC", "ar": "إيقاف تشغيل الجهاز"},
    "restart_pc": {"en": "restart the PC", "ar": "إعادة تشغيل الجهاز"},
}

YES_WORDS = {"yes", "yeah", "yep", "yup", "sure", "confirm", "confirmed", "do it", "go ahead", "proceed",
             "ok", "okay", "yes please", "affirmative", "نعم", "اي", "ايه", "إي", "أكد", "اكد", "تمام",
             "موافق", "اوكي", "أوكي", "يب", "اكيد", "أكيد", "نعم اكد"}
NO_WORDS = {"no", "nope", "cancel", "stop", "never mind", "nevermind", "dont", "don t", "abort",
            "لا", "الغ", "إلغاء", "الغاء", "وقف", "لا تسوي", "خلاص"}
ORDINALS = {"1": 0, "one": 0, "first": 0, "the first one": 0, "الأول": 0, "الاول": 0, "واحد": 0,
            "2": 1, "two": 1, "second": 1, "the second one": 1, "الثاني": 1, "اثنين": 1,
            "3": 2, "three": 2, "third": 2, "the third one": 2, "الثالث": 2, "ثلاثة": 2}


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
    run: Callable[[], ActionResult] | None = None
    options: list = field(default_factory=list)      # for "choose": list[AppEntry]
    created: float = field(default_factory=time.time)


Listener = Callable[[dict], Awaitable[None]]


class Jarvis:
    def __init__(self, llm: OllamaClient, executor: Executor, telemetry: TelemetryCollector,
                 confirm_timeout: int = 60, history_turns: int = 6):
        self.llm = llm
        self.executor = executor
        self.telemetry = telemetry
        self.confirm_timeout = confirm_timeout
        self.history: list[dict] = []
        self.history_turns = history_turns
        self.pending: dict[str, Pending] = {}
        self._lock = asyncio.Lock()
        self._listeners: list[Listener] = []

    # ---------------- public API
    def add_listener(self, fn: Listener) -> None:
        self._listeners.append(fn)

    async def handle_text(self, text: str, source: str = "text") -> dict:
        text = (text or "").strip()
        async with self._lock:
            if not text:
                resp = self._response(text, source, "en", "unknown", "", msg("unclear", "en"), "failed")
            else:
                resp = await self._handle(text, source)
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
        norm = normalize(text).rstrip(" .!")

        # 1) answers to a pending confirmation / choice (no LLM round-trip needed)
        pend = self._latest_pending()
        if pend:
            if pend.kind == "confirm" and (norm in YES_WORDS or norm in NO_WORDS):
                return await asyncio.to_thread(self._resolve_pending, pend.id, norm in YES_WORDS, source, None, text)
            if pend.kind == "choose":
                if norm in NO_WORDS:
                    return await asyncio.to_thread(self._resolve_pending, pend.id, False, source, None, text)
                idx = self._pick_option(norm, pend)
                if idx is not None:
                    return await asyncio.to_thread(self._resolve_pending, pend.id, True, source, idx, text)

        # 2) ask the local LLM for a structured intent
        try:
            raw = await self.llm.chat(self._messages(text), schema=INTENT_SCHEMA)
        except LLMError as exc:
            return self._response(text, source, lang, "unknown", "", msg("llm_down", lang, err=str(exc)), "error")
        parsed = self._parse(raw)
        if parsed is None:
            log.warning("Unparseable LLM output: %r", raw[:300])
            return self._response(text, source, lang, "unknown", "", msg("unclear", lang), "failed")

        self._remember(text, parsed)
        intent, target, reply, conf = parsed["intent"], parsed["target"], parsed["reply"], parsed["confidence"]
        log.info("Intent: %s target=%r conf=%.2f (%s)", intent, target, conf, source)
        return await asyncio.to_thread(self._dispatch, text, source, lang, intent, target, reply, conf)

    def _messages(self, text: str) -> list[dict]:
        return [{"role": "system", "content": SYSTEM_PROMPT}, *self.history, {"role": "user", "content": text}]

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
                "reply": str(data.get("reply") or "").strip(), "confidence": max(0.0, min(conf, 1.0))}

    # ---------------- dispatch (runs in a worker thread: may touch Windows APIs)
    def _dispatch(self, text, source, lang, intent, target, reply, conf) -> dict:
        R = lambda reply_, status, **kw: self._response(text, source, lang, intent, target, reply_, status, **kw)
        ex = self.executor

        if intent == "chat":
            return R(reply or msg("unclear", lang), "chat")
        if intent == "unknown":
            return R(reply or msg("unclear", lang), "needs_clarification")
        if intent == "system_stats":
            snap = self.telemetry.snapshot()
            return R(self.telemetry.spoken_summary(), "done", data={"telemetry": snap})

        # ---------- open_app: resolve name dynamically, never guess
        if intent == "open_app":
            if not target:
                return R(msg("unclear", lang), "needs_clarification")
            ex.apps.refresh_if_stale()
            m = ex.apps.match(target)
            if m.status == "none":
                ex.apps.refresh()               # maybe it was just installed
                m = ex.apps.match(target)
            if m.status == "none":
                return R(msg("not_found", lang, q=target), "failed")
            if m.status == "ambiguous":
                return self._ask_choice(R, intent, target, lang, [e for e, _ in m.candidates[:3]])
            entry = m.best
            if conf < 0.5:
                return self._ask_confirm(R, intent, target, lang, lambda: ex.launch_entry(entry),
                                         msg("confirm_low", lang, action=msg("opening", lang, name=entry.name).rstrip(".")))
            res = ex.launch_entry(entry)
            return self._result(R, res, msg("opening", lang, name=entry.name))

        # ---------- close_app: always confirm, show exactly what will be closed
        if intent == "close_app":
            procs = ex.find_processes(target)
            if not procs:
                return R(msg("nothing_to_close", lang, q=target or "?"), "failed")
            pids = [pid for lst in procs.values() for pid in lst]
            desc = ", ".join(f"{name} ({len(p)})" if len(p) > 1 else name for name, p in procs.items())
            return self._ask_confirm(R, intent, target, lang, lambda: ex.close_processes(pids, desc),
                                     msg("confirm_close", lang, desc=desc), data={"processes": procs})

        # ---------- power: always confirm
        if intent in POWER_ACTIONS:
            fn = {"sleep_pc": ex.sleep_pc, "shutdown_pc": ex.shutdown_pc, "restart_pc": ex.restart_pc}[intent]
            action = POWER_ACTIONS[intent][lang]
            return self._ask_confirm(R, intent, target, lang, fn, msg("confirm_power", lang, action=action))

        # ---------- safe actions
        if intent == "open_url":
            if not ex.normalize_url(target):
                return R(msg("bad_url", lang), "failed")
            run = lambda: ex.open_url(target)
        elif intent == "web_search":
            run = lambda: ex.web_search(target or text)
        elif intent == "media_control":
            if target not in MEDIA_TARGETS:
                return R(msg("unclear", lang), "needs_clarification")
            run = lambda: ex.media(target)
        elif intent == "lock_pc":
            run = ex.lock_pc
        elif intent == "cancel_shutdown":
            run = ex.cancel_shutdown
        else:
            return R(msg("unclear", lang), "needs_clarification")

        if conf < 0.5:
            return self._ask_confirm(R, intent, target, lang, run,
                                     msg("confirm_low", lang, action=reply or f"{intent} {target}"))
        return self._result(R, run(), reply)

    def _result(self, R, res: ActionResult, ok_reply: str) -> dict:
        if res.ok:
            return R(ok_reply or res.message, "done", data=res.data)
        return R(res.message, "failed", data=res.data)

    def _ask_confirm(self, R, intent, target, lang, run, question, data=None) -> dict:
        self._expire_pending()
        p = Pending(uuid.uuid4().hex[:12], "confirm", intent, target, lang, run=run)
        self.pending[p.id] = p
        return R(question, "needs_confirmation", pending_id=p.id, data=data or {})

    def _ask_choice(self, R, intent, target, lang, entries) -> dict:
        self._expire_pending()
        p = Pending(uuid.uuid4().hex[:12], "choose", intent, target, lang, options=entries)
        self.pending[p.id] = p
        names = [e.name for e in entries]
        return R(msg("ambiguous", lang, opts=", ".join(names)), "needs_choice", pending_id=p.id, options=names)

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
                return R(msg("ambiguous", p.lang, opts=", ".join(e.name for e in p.options)),
                         "needs_choice", pending_id=p.id, options=[e.name for e in p.options])
            entry = p.options[choice]
            return self._result(R, self.executor.launch_entry(entry), msg("opening", p.lang, name=entry.name))
        res = p.run()
        return self._result(R, res, res.message)
