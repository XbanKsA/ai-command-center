import time

import pytest

from memory import MemoryStore, relevance, time_window


@pytest.fixture
def mem(tmp_path):
    m = MemoryStore(tmp_path / "memory.db")
    yield m
    m.close()


def test_facts_add_dedupe_search_delete(mem):
    fid, updated = mem.add_fact("My games are on D:\\Games")
    assert not updated
    fid2, updated = mem.add_fact("my games are on D:\\Games.")          # same fact again -> update, no duplicate
    assert updated and fid2 == fid and len(mem.facts()) == 1
    mem.add_fact("My favorite game is Deadlock")
    mem.add_fact("My birthday is March 3")
    found = mem.search_facts("where are my games")
    assert found[0]["text"].startswith("My games are on")
    assert mem.search_facts("favorite game")[0]["text"] == "My favorite game is Deadlock."
    assert mem.search_facts("quantum physics") == []
    assert mem.delete_fact(fid) and not mem.delete_fact(fid)
    assert mem.clear_facts() == 2 and mem.facts() == []


def test_facts_persist_across_restarts(tmp_path):
    a = MemoryStore(tmp_path / "m.db")
    a.add_fact("My name is Saud")
    a.close()
    b = MemoryStore(tmp_path / "m.db")
    assert b.facts()[0]["text"] == "My name is Saud."


def test_facts_for_prompt_limits(mem):
    for i in range(30):
        mem.add_fact(f"Fact number {i} about topic{i}")
    mem.add_fact("My GPU is an RTX 5070")
    chosen = mem.facts_for_prompt("what gpu do I have", max_facts=10)
    assert len(chosen) == 10 and "My GPU is an RTX 5070." in chosen


def test_conversations(mem):
    mem.log_exchange("open spotify", "Opening Spotify.", "open_app", "voice")
    mem.log_exchange("who wrote hamlet", "Shakespeare.", "chat", "voice")
    assert [r["user_text"] for r in mem.recent_exchanges(5)] == ["open spotify", "who wrote hamlet"]
    assert mem.search_conversations("did we talk about hamlet")[0]["reply"] == "Shakespeare."
    assert mem.count_conversations() == 2


def test_time_window():
    now = time.mktime((2026, 11, 13, 13, 0, 0, 0, 0, -1))
    y = time_window("what did we talk about yesterday", now)
    assert y[1] - y[0] == 86400 and y[1] <= now
    assert time_window("hello", now) is None


def test_routines(mem):
    rid, updated = mem.add_routine("gaming time", ["open steam", "open discord", "gaming mode"])
    assert not updated
    assert mem.match_routine("Gaming time!")["steps"] == ["open steam", "open discord", "gaming mode"]
    assert mem.match_routine("run the gaming time routine")["id"] == rid
    assert mem.match_routine("gaming") is None
    _, updated = mem.add_routine("Gaming Time", ["open steam"])
    assert updated and mem.routines()[0]["steps"] == ["open steam"]
    assert mem.delete_routine("gaming time routine")["id"] == rid
    assert mem.routines() == []
    with pytest.raises(ValueError):
        mem.add_routine("x", [])


def test_relevance():
    assert relevance("where are my games", "My games are on D drive") >= 1.0
    assert relevance("pizza", "My games are on D drive") == 0.0
