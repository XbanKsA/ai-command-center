"""
Kageon assistant: natural language -> structured intent -> safe execution.

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
from datetime import datetime
from typing import Awaitable, Callable

from executor import (SEARCH_SITES, ActionResult, AppEntry, Executor, normalize, resolve_browser,
                      resolve_search_site, resolve_site)
from llm import LLMError, OllamaClient
from memory import MemoryStore, time_window
from screen import ScreenError, capture_screen, clean_for_speech, is_screen_question
from telemetry import TelemetryCollector

log = logging.getLogger("assistant")

INTENTS = [
    "chat", "open_app", "close_app", "open_url", "web_search", "media_control", "system_stats",
    "lock_pc", "sleep_pc", "shutdown_pc", "restart_pc", "cancel_shutdown", "confirm", "deny",
    "set_mode", "model_info", "play_media", "screen",
    "remember", "recall", "forget", "create_routine", "list_routines", "delete_routine", "unknown",
]
MEDIA_TARGETS = ["play_pause", "next", "previous", "stop", "mute", "volume_up", "volume_down"]

INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": INTENTS},
        "target": {"type": "string"},
        "browser": {"type": "string"},
        "site": {"type": "string"},
        "steps": {"type": "array", "items": {"type": "string"}},
        "reply": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["intent", "target", "browser", "site", "steps", "reply", "confidence"],
}

SYSTEM_PROMPT = f"""You are Kageon, a concise, witty, helpful AI assistant that controls a Windows PC.
Convert every user message into ONE JSON object: {{"intent", "target", "browser", "site", "steps", "reply", "confidence"}}.

Intents:
- chat: questions/conversation. "reply" = your full answer (max 3 short sentences, it will be spoken aloud).
- open_app: open/launch/start programs or games. target = app name(s) exactly as said, comma-separated if several.
- open_url: open websites (youtube, instagram, whatsapp web, any domain). target = site name(s) or domain(s),
  comma-separated if several. If the user names a browser ("on chrome", "in edge"), put it in "browser".
- close_app: close/quit/kill a program. target = app name.
- web_search: search for something. target = the search query (WITHOUT words like "search for", "a video of").
  site = where to search: "youtube" for videos, songs, music, trailers, tutorials, clips; "youtube music",
  "spotify", "amazon", "github", "reddit", "maps", "images" when asked; otherwise "google".
- play_media: play a song / video / music. target = what to play (e.g. "bad romance lady gaga").
  site = "youtube" (default), "youtube music" or "spotify" if the user says so.
- screen: the user asks about what is on their screen ("what's on my screen", "read this error", "what am I looking at").
  target = their question.
- remember: the user asks you to remember something. target = the fact, rewritten clearly (e.g. "My games are on D:\\Games").
- recall: the user asks what you remember / know about them. target = topic or "".
- forget: the user asks you to forget something. target = what to forget ("everything" to forget all).
- create_routine: "when I say X, do A, B, C". target = the trigger phrase X; steps = each action as a short command,
  e.g. ["open steam", "open discord", "gaming mode", "volume up"].
- list_routines: the user asks which routines / shortcuts exist.
- delete_routine: target = the routine's trigger phrase.
- media_control: target is one of {MEDIA_TARGETS}.
- system_stats: user asks about CPU / GPU / RAM / performance / temperature.
- lock_pc, sleep_pc, shutdown_pc, restart_pc, cancel_shutdown: target = "".
- confirm / deny: the user answers yes / no to a question you just asked.
- set_mode: switch your AI mode. target = "gaming", "normal" or "auto".
- model_info: the user asks which AI model / mode you are using.
- unknown: the request is unclear or impossible. "reply" = a short clarifying question.

Rules:
- "browser" is "" unless the user explicitly names a browser. Never put the browser in "target".
- "site" is "" and "steps" is [] unless the intent uses them.
- Facts listed under "What you remember about the user" are true; use them when relevant.
- "reply" for actions = a very short spoken acknowledgement.
- Always write "reply" in the SAME language the user used (Arabic -> Arabic, English -> English).
- confidence = 0..1, how sure you are about the intent and target. Never invent targets.
- Only output the JSON object.

Examples:
User: open chrome -> {{"intent":"open_app","target":"chrome","browser":"","site":"","steps":[],"reply":"Opening Chrome.","confidence":0.97}}
User: open youtube, instagram and whatsapp on google chrome -> {{"intent":"open_url","target":"youtube, instagram, whatsapp","browser":"chrome","site":"","steps":[],"reply":"Opening them in Chrome.","confidence":0.95}}
User: افتح يوتيوب في كروم -> {{"intent":"open_url","target":"youtube","browser":"chrome","site":"","steps":[],"reply":"جاري فتح يوتيوب.","confidence":0.95}}
User: افتح سبوتيفاي -> {{"intent":"open_app","target":"سبوتيفاي","browser":"","site":"","steps":[],"reply":"جاري فتح سبوتيفاي.","confidence":0.95}}
User: search for the weather in riyadh -> {{"intent":"web_search","target":"weather in riyadh","browser":"","site":"google","steps":[],"reply":"Searching.","confidence":0.95}}
User: search for bad romance by lady gaga -> {{"intent":"web_search","target":"bad romance lady gaga","browser":"","site":"youtube","steps":[],"reply":"Searching YouTube.","confidence":0.9}}
User: search for a cat video -> {{"intent":"web_search","target":"cat","browser":"","site":"youtube","steps":[],"reply":"Searching YouTube for cat videos.","confidence":0.9}}
User: play shape of you on spotify -> {{"intent":"play_media","target":"shape of you","browser":"","site":"spotify","steps":[],"reply":"Playing it on Spotify.","confidence":0.95}}
User: can you see what's on my screen -> {{"intent":"screen","target":"what's on my screen","browser":"","site":"","steps":[],"reply":"Let me look.","confidence":0.95}}
User: remember that my games are on the D drive -> {{"intent":"remember","target":"My games are on the D drive","browser":"","site":"","steps":[],"reply":"Got it.","confidence":0.95}}
User: when I say gaming time open steam and discord and switch to gaming mode -> {{"intent":"create_routine","target":"gaming time","browser":"","site":"","steps":["open steam","open discord","gaming mode"],"reply":"Routine saved.","confidence":0.95}}
User: turn the volume up -> {{"intent":"media_control","target":"volume_up","browser":"","site":"","steps":[],"reply":"Volume up.","confidence":0.95}}
User: how hot is my gpu -> {{"intent":"system_stats","target":"","browser":"","site":"","steps":[],"reply":"Checking.","confidence":0.9}}
User: shut down the computer -> {{"intent":"shutdown_pc","target":"","browser":"","site":"","steps":[],"reply":"Shutting down.","confidence":0.95}}
User: who wrote hamlet -> {{"intent":"chat","target":"","browser":"","site":"","steps":[],"reply":"William Shakespeare wrote Hamlet.","confidence":0.99}}
User: do the thing -> {{"intent":"unknown","target":"","browser":"","site":"","steps":[],"reply":"Which thing would you like me to do?","confidence":0.2}}
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
    "searching": {"en": "Searching {site} for {q}.", "ar": "جاري البحث في {site} عن {q}."},
    "playing": {"en": "Playing {q} on {site}.", "ar": "جاري تشغيل {q} على {site}."},
    "remembered": {"en": "Got it, I'll remember that.", "ar": "تم، سأتذكر ذلك."},
    "remember_updated": {"en": "Got it, I've updated that memory.", "ar": "تم تحديث الذاكرة."},
    "nothing_remembered": {"en": "I don't have anything saved yet. Say 'remember that' followed by something.",
                           "ar": "لا يوجد شيء محفوظ بعد."},
    "no_memory_about": {"en": "I don't have anything saved about {q}.", "ar": "لا يوجد شيء محفوظ عن {q}."},
    "forgot": {"en": "Okay, I forgot: {fact}", "ar": "تم نسيان: {fact}"},
    "confirm_forget_all": {"en": "Should I forget all {n} things you told me to remember, and our conversation history?",
                           "ar": "هل أنسى كل ما طلبت مني تذكره وسجل محادثاتنا؟"},
    "forgot_all": {"en": "Done. I've forgotten everything. Your routines are still saved.",
                   "ar": "تم نسيان كل شيء. الروتينات ما زالت محفوظة."},
    "routine_saved": {"en": "Got it. When you say {trigger}, I'll {steps}.", "ar": "تم. عندما تقول {trigger} سأقوم بـ: {steps}."},
    "routine_updated": {"en": "Updated. When you say {trigger}, I'll {steps}.", "ar": "تم التحديث. عندما تقول {trigger} سأقوم بـ: {steps}."},
    "routine_need_steps": {"en": "What should the {trigger} routine do?", "ar": "ماذا يجب أن يفعل روتين {trigger}؟"},
    "routine_running": {"en": "Running {trigger}.", "ar": "جاري تنفيذ {trigger}."},
    "no_routines": {"en": "You don't have any routines yet. Try: when I say gaming time, open Steam and Discord.",
                    "ar": "لا توجد روتينات بعد."},
    "routines_list": {"en": "Your routines: {list}.", "ar": "الروتينات: {list}."},
    "routine_deleted": {"en": "Deleted the {trigger} routine.", "ar": "تم حذف روتين {trigger}."},
    "routine_not_found": {"en": "I couldn't find a routine called {trigger}.", "ar": "لم أجد روتيناً باسم {trigger}."},
    "no_memory": {"en": "Memory is turned off.", "ar": "الذاكرة متوقفة."},
    "no_vision": {"en": "The current model, {model}, can't see images.", "ar": "النموذج الحالي {model} لا يستطيع رؤية الصور."},
    "mode_gaming": {"en": "Gaming mode on. Switching to the lightweight model.",
                    "ar": "تم تفعيل وضع الألعاب. سأستخدم النموذج الخفيف."},
    "mode_normal": {"en": "Back to normal mode. Using the full model.",
                    "ar": "عدنا إلى الوضع العادي. سأستخدم النموذج الكامل."},
    "mode_auto": {"en": "Auto mode on. I'll pick the model based on your free GPU memory.",
                  "ar": "تم تفعيل الوضع التلقائي. سأختار النموذج حسب ذاكرة كرت الشاشة."},
    "mode_auto_unavailable": {"en": "Auto mode needs NVIDIA GPU readings, which aren't available, so I'm staying in {mode} mode.",
                              "ar": "الوضع التلقائي يحتاج قراءات كرت NVIDIA وهي غير متاحة، لذلك سأبقى في الوضع الحالي."},
    "mode_already": {"en": "Already in {mode} mode.", "ar": "أنا بالفعل في هذا الوضع."},
    "no_modes": {"en": "Mode switching isn't available.", "ar": "تبديل الأوضاع غير متاح."},
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
              "no thanks", "forget it", "skip it", "لا", "الغ", "إلغاء", "الغاء", "وقف", "لا تسوي", "خلاص",
              "لا شكرا", "لاء"}
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

# "Kageon" plus the ways speech-to-text tends to spell it
WAKE_NAMES = r"(?:kageon|kagion|kagyon|kage\s+on|cage\s+on|kegon|kaigon)"
_WAKE_PREFIX = r"^(?:(?:hey|hi|ok|okay|yo)\s+)?(?:" + WAKE_NAMES + r"\s+)?(?:(?:هاي|يا)\s+)?(?:كاجيون\s+)?"
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


# ------------------------------------------------------------------ AI mode commands

MODE_WORDS = {
    "gaming": ["gaming mode", "game mode", "gamer mode", "gamemode", "وضع الالعاب", "وضع الألعاب", "وضع اللعب", "وضع القيمنق",
               "وضع القيمنج", "مود الالعاب"],
    "normal": ["normal mode", "full mode", "regular mode", "الوضع العادي", "وضع عادي", "الوضع الطبيعي", "الوضع الكامل"],
    "auto": ["auto mode", "automatic mode", "auto switching", "الوضع التلقائي", "وضع تلقائي", "الوضع الاوتوماتيكي",
             "التبديل التلقائي"],
}
MODEL_QUESTIONS = ["which model", "what model", "current model", "what ai model", "which ai", "what mode are you",
                   "which mode are you", "what mode is", "which mode is",
                   "اي موديل", "أي موديل", "ايش الموديل", "وش الموديل", "اي نموذج", "أي نموذج", "ما هو النموذج",
                   "اي وضع", "أي وضع", "وش الوضع", "ايش الوضع"]
THINK_TRIGGERS = ["think about it", "think about this", "think carefully", "think hard", "think deeply", "think it through",
                  "deep analysis", "analyze deeply", "analyse deeply", "in depth", "in-depth", "take your time",
                  "step by step", "فكر فيها", "فكر في", "فكر بعمق", "فكر جيدا", "فكّر", "حلل بعمق", "تحليل عميق",
                  "خذ وقتك", "بالتفصيل"]


def detect_mode_command(text: str) -> str | None:
    """'switch to gaming mode' -> 'gaming'. Only short commands (so a question *about* modes isn't a switch)."""
    n = normalize(text)
    if len(n.split()) > 7 or any(q in n for q in MODEL_QUESTIONS):
        return None
    compact = n.replace(" ", "")              # speech-to-text sometimes writes "automode", "gamingmode"
    for mode, words in MODE_WORDS.items():
        if any(normalize(w) in n or normalize(w).replace(" ", "") in compact for w in words):
            return mode
    return None


def is_model_question(text: str) -> bool:
    n = normalize(text)
    return any(normalize(q) in n for q in MODEL_QUESTIONS)


def wants_thinking(text: str) -> bool:
    n = normalize(text)
    return any(normalize(t) in n for t in THINK_TRIGGERS)


# ------------------------------------------------------------------ date / time
# The language model has no clock (it once said "October 24, 2023"), so these are answered from the PC clock.
_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December")
_WHEN = r"(?:\s+(?:now|right now|today|of today|is it|is it today|is it now))?"
TIME_RE = re.compile(_WAKE_PREFIX + _POLITE + r"(?:tell me\s+)?(?:what\s+(?:s\s+|is\s+)?(?:the\s+)?(?:current\s+)?time"
                     r"|the\s+time|current\s+time|time)" + _WHEN + r"(?:\s+please)?$")
DATE_RE = re.compile(_WAKE_PREFIX + _POLITE + r"(?:tell me\s+)?(?:what\s+(?:s\s+|is\s+)?(?:the\s+)?(?:date|day)"
                     r"|what\s+(?:s\s+|is\s+)?today(?:\s+s\s+date)?|today\s+s\s+date|the\s+date|which\s+day)"
                     + _WHEN + r"(?:\s+please)?$")


def _now() -> datetime:
    return datetime.now()


def clock_text(dt: datetime | None = None) -> tuple[str, str]:
    """-> ("Monday, November 16, 2026", "10:32 PM"); no locale or Windows strftime quirks."""
    dt = dt or _now()
    date = f"{_DAYS[dt.weekday()]}, {_MONTHS[dt.month - 1]} {dt.day}, {dt.year}"
    return date, f"{dt.hour % 12 or 12}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


PLAY_RE = re.compile(_WAKE_PREFIX + _POLITE + r"(?:play|put on)\s+(?P<t>.+?)(?:\s+(?:on|in|using)\s+"
                     r"(?P<site>youtube music|yt music|youtube|you tube|spotify))?(?:\s+please)?$")
SEARCH_RE = re.compile(_WAKE_PREFIX + _POLITE + r"(?:search|look up|find|google)\s+(?:for\s+)?(?P<t>.+?)"
                       r"(?:\s+(?:on|in)\s+(?P<site>youtube music|yt music|youtube|you tube|spotify|google|amazon|github|"
                       r"reddit|twitch|wikipedia|steam|maps|google maps|images|google images|twitter|x))?(?:\s+please)?$")
_VIDEO_WORDS = re.compile(r"\b(videos?|songs?|music|trailers?|clips?|music video|tutorials?|lyrics)\b")


# ------------------------------------------------------------------ memory commands

REMEMBER_RE = re.compile(r"^(?:(?:hey\s+)?" + WAKE_NAMES + r"\s+)?(?:please\s+)?(?:remember|don'?t forget|keep in mind|note)"
                         r"\s+(?:that\s+)?(?P<t>.{3,})$", re.I)
FORGET_RE = re.compile(r"^(?:(?:hey\s+)?" + WAKE_NAMES + r"\s+)?(?:please\s+)?forget\s+(?:about\s+)?(?P<t>.+)$", re.I)
RECALL_RE = re.compile(r"^(?:what do you remember|what do you know about me|what have you (?:remembered|saved)|"
                       r"(?:list|show|tell me)(?: me)? (?:your|my|all) memories|what are my memories|"
                       r"what do you remember about (?P<t>.+)|what did i tell you about (?P<t2>.+))$", re.I)
LIST_ROUTINES = {"list my routines", "what routines do i have", "what are my routines", "show my routines",
                 "my routines", "list routines", "what routines do you know", "which routines do i have"}
DELETE_ROUTINE_RE = re.compile(r"^(?:please\s+)?(?:delete|remove)\s+(?:the\s+|my\s+)?(?:routine\s+(?P<a>.+)|"
                               r"(?P<b>.+?)\s+routine)$", re.I)
FORGET_ALL = {"everything", "all", "all memories", "all of it", "everything you know", "everything about me",
              "all my memories", "everything i told you"}
FORGET_LAST = {"that", "the last thing", "what i just said", "the last one", "the last memory"}
PAST_TALK_RE = re.compile(r"\b(we talk(?:ed)?|we (?:were )?discuss(?:ed|ing)?|did i (?:say|ask|tell)|last time|yesterday|"
                          r"earlier today|i asked you|you told me|our (?:last )?conversation|we spoke)\b", re.I)


def _clean_sentence(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().strip(".!?")).strip()


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


class Assistant:
    def __init__(self, llm: OllamaClient, executor: Executor, telemetry: TelemetryCollector,
                 confirm_timeout: int = 60, history_turns: int = 6, fast_commands: bool = True, modes=None,
                 memory: MemoryStore | None = None, screen_max_side: int = 1280, max_memory_facts: int = 20):
        self.llm = llm
        self.modes = modes                          # ModeManager (optional)
        self.memory = memory                        # MemoryStore (optional)
        self.screen_max_side = screen_max_side
        self.max_memory_facts = max_memory_facts
        self._in_routine = False
        self.executor = executor
        self.telemetry = telemetry
        self.confirm_timeout = confirm_timeout
        self.fast_commands = fast_commands
        self.history: list[dict] = []
        self.history_turns = history_turns
        self.pending: dict[str, Pending] = {}
        self._bg_tasks: set[asyncio.Task] = set()
        self._lock = asyncio.Lock()
        self._listeners: list[Listener] = []
        if self.memory:                             # pick up the conversation where it left off
            for ex in self.memory.recent_exchanges(history_turns):
                self.history += [{"role": "user", "content": ex["user_text"]},
                                 {"role": "assistant", "content": json.dumps(
                                     {"intent": ex["intent"] or "chat", "target": "", "browser": "", "site": "",
                                      "steps": [], "reply": ex["reply"], "confidence": 1.0}, ensure_ascii=False)}]

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
        if self.memory and text:
            try:
                self.memory.log_exchange(text, resp.get("reply", ""), resp.get("intent", ""), source)
            except Exception as exc:
                log.debug("could not log exchange: %s", exc)
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

        # 2) your routines ("gaming time" -> open Steam, open Discord, gaming mode ...)
        if self.memory and not self._in_routine:
            routine = self.memory.match_routine(text)
            if routine:
                return self._via(await self._run_routine(routine, text, source, lang), "routine")

        # 3) memory commands: remember / forget / what do you remember / routines (instant, no LLM)
        if self.memory:
            mem = await self._memory_rules(text, source, lang)
            if mem:
                return self._via(mem, "rules")

        # 4) "what's on my screen?" -> screenshot + vision model
        if is_screen_question(text):
            return self._via(await self._look_at_screen(text, source, lang, text, wants_thinking(text)), "vision")

        # 5) AI mode commands / "which model are you using?" (instant, no LLM)
        mode_cmd = detect_mode_command(text)
        if mode_cmd:
            return self._via(await self._set_mode(text, source, lang, mode_cmd), "rules")
        if is_model_question(text):
            return self._via(self._model_info(text, source, lang), "rules")

        # 6) instant local rules for simple commands
        if self.fast_commands:
            fast = await asyncio.to_thread(self._fast_intent, text)
            if fast:
                log.info("Fast intent: %s target=%r browser=%r", fast["intent"], fast["target"], fast["browser"])
                return self._via(await asyncio.to_thread(self._dispatch, text, source, lang, fast), "rules")

        # 7) ask the local LLM for a structured intent ("think about it" turns thinking on for this request)
        think = wants_thinking(text)
        t0 = time.perf_counter()
        try:
            raw = await self.llm.chat(self._messages(text, pend, think), schema=INTENT_SCHEMA, think=think or None)
        except LLMError as exc:
            return self._via(self._response(text, source, lang, "unknown", "", msg("llm_down", lang, err=str(exc)), "error"), "llm")
        log.info("LLM (%s%s) answered in %.2fs", self.llm.model, ", thinking" if think else "", time.perf_counter() - t0)
        parsed = self._parse(raw)
        if parsed is None:
            log.warning("Unparseable LLM output: %r", raw[:300])
            return self._via(self._response(text, source, lang, "unknown", "", msg("unclear", lang), "failed"), "llm")

        self._remember(text, parsed)
        log.info("Intent: %s target=%r browser=%r conf=%.2f (%s)", parsed["intent"], parsed["target"],
                 parsed["browser"], parsed["confidence"], source)
        if parsed["intent"] == "set_mode":
            mode = normalize(parsed["target"])
            mode = next((m for m in MODE_WORDS if m in mode), None)
            if mode:
                return self._via(await self._set_mode(text, source, lang, mode), "llm")
            parsed["intent"] = "unknown"
        if parsed["intent"] == "model_info":
            return self._via(self._model_info(text, source, lang), "llm")
        if parsed["intent"] == "screen":
            return self._via(await self._look_at_screen(text, source, lang, parsed["target"] or text, think), "vision")
        if parsed["intent"] in ("remember", "recall", "forget", "create_routine", "list_routines", "delete_routine"):
            return self._via(await self._memory_intent(text, source, lang, parsed), "llm")
        resp = await asyncio.to_thread(self._dispatch, text, source, lang, parsed)
        if think:
            resp["data"]["thinking"] = True
        return self._via(resp, "llm")

    # ================================================================ screen
    async def _look_at_screen(self, text: str, source: str, lang: str, question: str, think: bool) -> dict:
        R = lambda reply, status, **kw: self._response(text, source, lang, "screen", "", reply, status, **kw)
        caps = await self.llm.capabilities(self.llm.model)
        if caps and "vision" not in caps:
            return R(msg("no_vision", lang, model=self.llm.model), "failed")
        try:
            image = await asyncio.to_thread(capture_screen, self.screen_max_side)
        except ScreenError as exc:
            return R(str(exc), "failed")
        messages = [
            {"role": "system", "content": "You are Kageon, a helpful assistant. You are looking at a screenshot of the "
             "user's Windows PC screen. Answer their question about it directly and concisely (2-4 short sentences, "
             "it will be spoken aloud). Read exact text (errors, titles, numbers) when relevant. No markdown."},
            *self._memory_context(question),
            {"role": "user", "content": question or "What's on my screen?", "images": [image]},
        ]
        t0 = time.perf_counter()
        try:
            answer = await self.llm.chat(messages, schema=None, temperature=0.3, think=think or None)
        except LLMError as exc:
            return R(msg("llm_down", lang, err=str(exc)), "error")
        log.info("Vision (%s) answered in %.2fs", self.llm.model, time.perf_counter() - t0)
        return R(clean_for_speech(answer) or msg("unclear", lang), "chat", data={"screen": True})

    # ================================================================ memory
    async def _memory_rules(self, text: str, source: str, lang: str) -> dict | None:
        t = _clean_sentence(text)
        n = normalize(t)
        if n in LIST_ROUTINES or (("routine" in n or "shortcut" in n) and n.startswith(("what", "list", "show", "which"))):
            return await self._memory_intent(text, source, lang, {"intent": "list_routines", "target": ""})
        m = DELETE_ROUTINE_RE.match(t)
        if m:
            return await self._memory_intent(text, source, lang,
                                             {"intent": "delete_routine", "target": m.group("a") or m.group("b")})
        m = RECALL_RE.match(t)
        if m:
            return await self._memory_intent(text, source, lang,
                                             {"intent": "recall", "target": m.group("t") or m.group("t2") or ""})
        m = FORGET_RE.match(t)
        if m:
            return await self._memory_intent(text, source, lang, {"intent": "forget", "target": m.group("t")})
        m = REMEMBER_RE.match(t)
        if m and not n.startswith(("remember when", "remember what", "remember how")):
            return await self._memory_intent(text, source, lang, {"intent": "remember", "target": m.group("t")})
        return None

    async def _memory_intent(self, text: str, source: str, lang: str, p: dict) -> dict:
        intent, target = p["intent"], _clean_sentence(p.get("target", ""))
        R = lambda reply, status, **kw: self._response(text, source, lang, intent, target, reply, status, **kw)
        mem = self.memory
        if not mem:
            return R(msg("no_memory", lang), "failed")

        if intent == "remember":
            if not target:
                return R(msg("unclear", lang), "needs_clarification")
            fact_id, updated = mem.add_fact(target[0].upper() + target[1:])
            return R(msg("remember_updated" if updated else "remembered", lang), "done",
                     data={"fact": {"id": fact_id, "text": target}})

        if intent == "recall":
            facts = mem.search_facts(target, limit=5) if target else mem.facts()
            if not facts:
                return R(msg("no_memory_about", lang, q=target) if target else msg("nothing_remembered", lang), "done")
            spoken = " ".join(f["text"] for f in facts[:5])
            more = f" And {len(facts) - 5} more." if len(facts) > 5 else ""
            intro = "Here's what I remember: " if lang == "en" else "هذا ما أتذكره: "
            return R(intro + spoken + more, "done", data={"facts": facts})

        if intent == "forget":
            tn = normalize(target)
            if tn in FORGET_ALL:
                n = len(mem.facts())

                def wipe() -> ActionResult:
                    f, c = mem.clear_facts(), mem.clear_conversations()
                    self.history.clear()
                    return ActionResult(True, msg("forgot_all", lang), {"facts_deleted": f, "conversations_deleted": c})
                return self._ask_confirm(R, "forget", "everything", lang, wipe, msg("confirm_forget_all", lang, n=n),
                                         done_reply=msg("forgot_all", lang))
            if tn in FORGET_LAST:
                facts = mem.facts()
                target_fact = facts[0] if facts else None
            else:
                found = mem.search_facts(target, limit=1)
                target_fact = found[0] if found else None
            if not target_fact:
                return R(msg("no_memory_about", lang, q=target), "failed")
            mem.delete_fact(target_fact["id"])
            return R(msg("forgot", lang, fact=target_fact["text"]), "done", data={"deleted": target_fact})

        if intent == "list_routines":
            routines = mem.routines()
            if not routines:
                return R(msg("no_routines", lang), "done")
            names = join_names([r["display"] for r in routines], lang)
            return R(msg("routines_list", lang, list=names), "done", data={"routines": routines})

        if intent == "delete_routine":
            r = mem.delete_routine(target)
            if not r:
                return R(msg("routine_not_found", lang, trigger=target), "failed")
            return R(msg("routine_deleted", lang, trigger=r["display"]), "done", data={"deleted": r})

        if intent == "create_routine":
            trigger = target.strip("\"' ")
            steps = [st for st in p.get("steps", []) if normalize(st) != normalize(trigger)]
            if not trigger or yes_or_no(trigger) is not None:
                return R(msg("unclear", lang), "needs_clarification")
            if not steps:
                return R(msg("routine_need_steps", lang, trigger=trigger), "needs_clarification")
            _, updated = mem.add_routine(trigger, steps)
            key = "routine_updated" if updated else "routine_saved"
            return R(msg(key, lang, trigger=trigger, steps=join_names(steps, lang)), "done",
                     data={"routine": {"trigger": trigger, "steps": steps}})

        return R(msg("unclear", lang), "needs_clarification")

    async def _run_routine(self, routine: dict, text: str, source: str, lang: str) -> dict:
        log.info("Running routine '%s': %s", routine["display"], routine["steps"])
        results, pending = [], None
        self._in_routine = True
        try:
            for step in routine["steps"]:
                r = await self._handle(step, source)
                results.append({"step": step, "status": r["status"], "reply": r["reply"]})
                if r.get("pending_id"):
                    pending = r          # e.g. a step that needs "are you sure?"
        finally:
            self._in_routine = False
        replies = " ".join(x["reply"] for x in results if x["reply"])
        reply = msg("routine_running", lang, trigger=routine["display"]) + " " + replies
        status = pending["status"] if pending else ("done" if all(x["status"] in ("done", "chat") for x in results)
                                                      else "failed")
        return self._response(text, source, lang, "run_routine", routine["display"], reply.strip(), status,
                              pending_id=pending["pending_id"] if pending else None,
                              options=pending.get("options", []) if pending else [],
                              data={"routine": routine["display"], "steps": results})

    async def _set_mode(self, text: str, source: str, lang: str, mode: str) -> dict:
        R = lambda reply, status, **kw: self._response(text, source, lang, "set_mode", mode, reply, status, **kw)
        if not self.modes:
            return R(msg("no_modes", lang), "failed")
        m = self.modes
        if mode == "auto" and not m.auto_available:
            await m.set_mode("auto", source=source)
            return R(msg("mode_auto_unavailable", lang, mode=m.active), "done", data={"mode": m.status()})
        if mode == m.requested and (mode == "auto" or mode == m.active):
            return R(msg("mode_already", lang, mode=mode), "done", data={"mode": m.status()})
        # swap in the background: loading a model takes a few seconds, the reply shouldn't wait for it
        task = asyncio.create_task(m.set_mode(mode, source=source))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return R(msg(f"mode_{mode}", lang), "done", data={"mode": {**m.status(), "requested": mode}})

    def _model_info(self, text: str, source: str, lang: str) -> dict:
        if not self.modes:
            return self._response(text, source, lang, "model_info", "",
                                  f"I'm using {self.llm.model}.", "done", data={"model": self.llm.model})
        return self._response(text, source, lang, "model_info", "", self.modes.describe(lang), "done",
                              data={"mode": self.modes.status()})

    @staticmethod
    def _via(resp: dict, via: str) -> dict:
        resp["via"] = via
        return resp

    def _memory_context(self, text: str) -> list[dict]:
        if not self.memory:
            return []
        out = []
        facts = self.memory.facts_for_prompt(text, self.max_memory_facts)
        if facts:
            out.append({"role": "system", "content": "What you remember about the user:\n" +
                        "\n".join(f"- {f}" for f in facts)})
        if PAST_TALK_RE.search(text or ""):
            window = time_window(text)
            past = self.memory.search_conversations(text, limit=8, since=window[0] if window else None,
                                                    until=window[1] if window else None)
            if past:
                lines = [f"[{time.strftime('%Y-%m-%d %H:%M', time.localtime(r['ts']))}] User: {r['user_text']} | "
                         f"Kageon: {r['reply']}" for r in past]
                out.append({"role": "system", "content": "Earlier conversations (oldest first). Use them to answer "
                            "questions about what was said before:\n" + "\n".join(lines)})
        return out

    def _messages(self, text: str, pend: Pending | None, think: bool = False) -> list[dict]:
        date, clock = clock_text()
        msgs = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "system", "content": f"Right now it is {date}, {clock} (the user's local time). "
                                              "Use this for anything about today, the date, the day or the time."},
                *self._memory_context(text), *self.history]
        if think:
            msgs.append({"role": "system", "content": "The user asked you to think carefully. For chat answers, "
                         "\"reply\" may be up to 8 sentences of careful, well-reasoned analysis."})
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
        steps = data.get("steps") or []
        if not isinstance(steps, list):
            steps = [str(steps)]
        return {"intent": intent, "target": str(data.get("target") or "").strip(),
                "browser": str(data.get("browser") or "").strip(),
                "site": str(data.get("site") or "").strip(),
                "steps": [str(x).strip() for x in steps if str(x).strip()][:12],
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

        is_time, is_date = bool(TIME_RE.match(norm)), bool(DATE_RE.match(norm))
        if is_time or is_date:
            date, clock = clock_text()
            reply = f"It's {clock}." if is_time else f"Today is {date}."
            return {**base, "intent": "chat", "target": "", "reply": reply}

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

        m = PLAY_RE.match(soft_normalize(text))
        if m and normalize(m.group("t")) not in _MEDIA_LOOKUP:
            target, browser = split_browser(m.group("t"))
            return {**base, "intent": "play_media", "target": target, "browser": browser,
                    "site": m.group("site") or ""}

        m = SEARCH_RE.match(soft_normalize(text))
        if m:
            target, browser = split_browser(m.group("t"))
            site = m.group("site") or ""
            if not site and _VIDEO_WORDS.search(target):
                site = "youtube"
                target = re.sub(r"\s+", " ", re.sub(r"^(?:an?|the|some)\s+", "", _VIDEO_WORDS.sub(" ", target))).strip() or target
            if site or not re.search(r"\bby\b", target):     # "X by <artist>" -> let the LLM decide (song?)
                return {**base, "intent": "web_search", "target": target, "browser": browser,
                        "site": site or "google"}
            return None

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
            site = p.get("site", "")
            run = lambda: ex.web_search(target or text, browser or None, site)
            site_name = SEARCH_SITES[resolve_search_site(site)][0]
            reply = msg("searching", lang, q=target or text, site=site_name)
        elif intent == "play_media":
            if not target:
                return R(msg("unclear", lang), "needs_clarification")
            run = lambda: ex.play_media(target, p.get("site", ""), browser or None)
            site_name = SEARCH_SITES[resolve_search_site(p.get("site") or ex.play_site)][0]
            reply = msg("playing", lang, q=target, site=site_name)
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
