"""
Kageon long-term memory -- everything stays on this PC in backend/data/memory.db (SQLite).

  facts          "remember that my games are on D:\\Games"   -> used automatically in later answers
  conversations  every exchange is logged -> context survives restarts, "what did we talk about yesterday?"
  routines       "when I say gaming time, open Steam and Discord" -> saying "gaming time" runs the steps
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

log = logging.getLogger("memory")

_STOP = {"the", "a", "an", "my", "is", "are", "was", "were", "am", "to", "of", "in", "on", "at", "and", "or", "for",
         "it", "that", "this", "i", "im", "me", "we", "us", "you", "your", "do", "does", "did", "what", "whats", "about",
         "with", "be", "have", "has", "had", "will", "remember", "know", "tell", "told", "please", "can", "could",
         "would", "should", "where", "when", "why", "how", "who", "which", "there", "here", "now", "just", "also",
         "talk", "talked", "talking", "say", "said", "ask", "asked", "discuss", "discussed", "yesterday", "today",
         "earlier", "last", "time", "thing", "things", "something", "anything", "any", "some", "get", "got",
         "installed", "saved", "again", "kageon", "hey"}


def _norm(text: str) -> str:
    text = re.sub(r"[^\w\s+:\\\\/.-]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", text).strip(" .")


def _words(text: str) -> set[str]:
    return {w.strip(".:") for w in _norm(text).split() if w.strip(".:") and w.strip(".:") not in _STOP}


def _stem(w: str) -> str:
    """Tiny plural/verb stemmer: games->game, matches->match, stories->story, playing->play."""
    if len(w) <= 3:
        return w
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith(("ches", "shes", "sses", "xes", "zes")):
        return w[:-2]
    if w.endswith("ing") and len(w) > 5:
        return w[:-3]
    if w.endswith("ed") and len(w) > 4:
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def relevance(query: str, text: str) -> float:
    """0..1 keyword overlap between a query and a stored text (stemmed, stop-words removed)."""
    q = {_stem(w) for w in _words(query)}
    t = {_stem(w) for w in _words(text)}
    if not q or not t:
        return 0.0
    overlap = len(q & t)
    # mostly: how much of the question is covered; small bonus for specific (short, focused) memories
    return overlap / len(q) + 0.1 * overlap / len(t)


class MemoryStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._db:
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL,
                    created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, source TEXT,
                    user_text TEXT, reply TEXT, intent TEXT);
                CREATE TABLE IF NOT EXISTS routines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, trigger TEXT NOT NULL UNIQUE,
                    display TEXT NOT NULL, steps TEXT NOT NULL, created REAL NOT NULL);
            """)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ================================================================ facts
    def add_fact(self, text: str) -> tuple[int, bool]:
        """Store a fact. If a very similar one exists, it is replaced (updated=True)."""
        text = re.sub(r"\s+", " ", (text or "").strip()).rstrip(".") + "."
        text = text[:1].upper() + text[1:]
        if len(text) < 3:
            raise ValueError("empty fact")
        now = time.time()
        with self._lock, self._db:
            for row in self._db.execute("SELECT id, text FROM facts"):
                a, b = _norm(row["text"]), _norm(text)
                if a == b or SequenceMatcher(None, a, b).ratio() > 0.93:
                    self._db.execute("UPDATE facts SET text=?, updated=? WHERE id=?", (text, now, row["id"]))
                    return row["id"], True
            cur = self._db.execute("INSERT INTO facts(text, created, updated) VALUES (?,?,?)", (text, now, now))
            log.info("Remembered: %s", text)
            return cur.lastrowid, False

    def facts(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute("SELECT * FROM facts ORDER BY updated DESC")]

    def search_facts(self, query: str, limit: int = 5, min_score: float = 0.34) -> list[dict]:
        scored = [(relevance(query, f["text"]), f) for f in self.facts()]
        scored = [(sc, f) for sc, f in scored if sc >= min_score]
        scored.sort(key=lambda x: (-x[0], -x[1]["updated"]))
        return [dict(f, score=round(sc, 2)) for sc, f in scored[:limit]]

    def facts_for_prompt(self, query: str, max_facts: int = 20) -> list[str]:
        """All facts when there are few; otherwise the most relevant + most recent ones."""
        facts = self.facts()
        if len(facts) <= max_facts:
            return [f["text"] for f in facts]
        relevant = self.search_facts(query, limit=max_facts // 2, min_score=0.2)
        chosen = {f["id"]: f for f in relevant}
        for f in facts:
            if len(chosen) >= max_facts:
                break
            chosen.setdefault(f["id"], f)
        return [f["text"] for f in chosen.values()]

    def delete_fact(self, fact_id: int) -> bool:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM facts WHERE id=?", (fact_id,)).rowcount > 0

    def clear_facts(self) -> int:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM facts").rowcount

    # ================================================================ conversations
    def log_exchange(self, user_text: str, reply: str, intent: str = "", source: str = "") -> None:
        if not user_text:
            return
        with self._lock, self._db:
            self._db.execute("INSERT INTO conversations(ts, source, user_text, reply, intent) VALUES (?,?,?,?,?)",
                             (time.time(), source, user_text, reply or "", intent or ""))

    def recent_exchanges(self, n: int = 6) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM conversations ORDER BY id DESC LIMIT ?", (n,)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def search_conversations(self, query: str, limit: int = 6, since: float | None = None,
                             until: float | None = None) -> list[dict]:
        sql, args = "SELECT * FROM conversations WHERE 1=1", []
        if since is not None:
            sql += " AND ts >= ?"
            args.append(since)
        if until is not None:
            sql += " AND ts < ?"
            args.append(until)
        with self._lock:
            rows = [dict(r) for r in self._db.execute(sql + " ORDER BY id DESC LIMIT 500", args)]
        if not _words(query) or since is not None:
            # a time window ("yesterday") -> most recent exchanges in it, keyword-boosted
            rows.sort(key=lambda r: (-relevance(query, r["user_text"] + " " + r["reply"]), -r["ts"]))
            return sorted(rows[:limit], key=lambda r: r["ts"])
        scored = [(relevance(query, r["user_text"] + " " + r["reply"]), r) for r in rows]
        scored = [x for x in scored if x[0] >= 0.34]
        scored.sort(key=lambda x: (-x[0], -x[1]["ts"]))
        return sorted([r for _, r in scored[:limit]], key=lambda r: r["ts"])

    def count_conversations(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]

    def clear_conversations(self) -> int:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM conversations").rowcount

    # ================================================================ routines
    @staticmethod
    def routine_key(trigger: str) -> str:
        t = _norm(trigger).strip("\"' ")
        t = re.sub(r"^(?:the |my )", "", t)
        return re.sub(r"\s+(?:routine|mode routine)$", "", t).strip()

    def add_routine(self, trigger: str, steps: list[str]) -> tuple[int, bool]:
        key = self.routine_key(trigger)
        steps = [s.strip() for s in steps if s and s.strip()]
        if not key or not steps:
            raise ValueError("a routine needs a trigger phrase and at least one step")
        with self._lock, self._db:
            row = self._db.execute("SELECT id FROM routines WHERE trigger=?", (key,)).fetchone()
            if row:
                self._db.execute("UPDATE routines SET steps=?, display=? WHERE id=?",
                                 (json.dumps(steps), trigger.strip(), row["id"]))
                return row["id"], True
            cur = self._db.execute("INSERT INTO routines(trigger, display, steps, created) VALUES (?,?,?,?)",
                                   (key, trigger.strip(), json.dumps(steps), time.time()))
            log.info("Routine saved: %s -> %s", key, steps)
            return cur.lastrowid, False

    def routines(self) -> list[dict]:
        with self._lock:
            rows = [dict(r) for r in self._db.execute("SELECT * FROM routines ORDER BY trigger")]
        for r in rows:
            r["steps"] = json.loads(r["steps"])
        return rows

    def match_routine(self, text: str) -> dict | None:
        """Exact trigger, or 'run / start / do / activate <trigger> (routine)'."""
        t = self.routine_key(text)
        t2 = self.routine_key(re.sub(r"^(?:please )?(?:run|start|do|activate|execute|launch)\s+", "", t))
        for r in self.routines():
            if r["trigger"] in (t, t2):
                return r
        return None

    def delete_routine(self, trigger: str) -> dict | None:
        key = self.routine_key(trigger)
        best = None
        for r in self.routines():
            if r["trigger"] == key:
                best = r
                break
            if SequenceMatcher(None, r["trigger"], key).ratio() > 0.8:
                best = r
        if best:
            with self._lock, self._db:
                self._db.execute("DELETE FROM routines WHERE id=?", (best["id"],))
        return best

    def delete_routine_id(self, routine_id: int) -> bool:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM routines WHERE id=?", (routine_id,)).rowcount > 0

    # ================================================================ summary
    def summary(self) -> dict:
        return {"facts": self.facts(), "routines": self.routines(), "conversations": self.count_conversations(),
                "path": str(self.path)}


def time_window(text: str, now: float | None = None) -> tuple[float, float] | None:
    """'yesterday' / 'today' / 'last week' / 'this morning' -> (since, until) timestamps."""
    t = (text or "").lower()
    now_dt = datetime.fromtimestamp(now or time.time())
    midnight = now_dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    if "yesterday" in t:
        return midnight - 86400, midnight
    if "today" in t or "this morning" in t or "earlier" in t:
        return midnight, now_dt.timestamp() + 1
    if "last week" in t or "this week" in t or "few days" in t:
        return midnight - 7 * 86400, now_dt.timestamp() + 1
    return None
