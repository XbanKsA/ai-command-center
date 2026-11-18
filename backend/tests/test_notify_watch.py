import asyncio
from datetime import datetime

from notify_watch import NotificationWatcher, allowed_for


class Text:
    def __init__(self, t):
        self.text = t


class Binding:
    def __init__(self, texts):
        self.texts = texts

    def get_text_elements(self):
        return [Text(t) for t in self.texts]


class Visual:
    def __init__(self, texts):
        self.texts = texts

    def get_binding(self, _):
        return Binding(self.texts)


class Fake:
    """Looks like a Windows UserNotification."""

    def __init__(self, nid, app, *texts):
        self.id = nid
        self.app_info = type("A", (), {"display_info": type("D", (), {"display_name": app})()})()
        self.notification = type("N", (), {"visual": Visual(list(texts))})()
        self.creation_time = datetime(2026, 11, 17, 20, 0)


class FakeListener:
    def __init__(self):
        self.items = []

    async def get_notifications_async(self, _):
        return list(self.items)


def watcher_with(listener):
    w = NotificationWatcher()
    w._listener = listener
    w.status = "ok"
    return w


def test_first_read_only_remembers_whats_there():
    lis = FakeListener()
    lis.items = [Fake(1, "Discord", "Sara", "hey")]
    w = watcher_with(lis)
    assert asyncio.run(w.poll()) == []          # already in the Action Center: not replayed
    assert w.apps == ["Discord"]                # but offered as an app to pick


def test_new_notifications_come_once():
    lis = FakeListener()
    w = watcher_with(lis)
    asyncio.run(w.poll())
    lis.items = [Fake(5, "Steam", "Download finished", "Deadlock", "is ready")]
    new = asyncio.run(w.poll())
    assert len(new) == 1
    assert new[0]["app"] == "Steam" and new[0]["title"] == "Download finished" and new[0]["text"] == "Deadlock is ready"
    assert asyncio.run(w.poll()) == []          # not sent twice
    assert w.apps == ["Steam"]


def test_unavailable_without_windows():
    w = NotificationWatcher()
    assert asyncio.run(w.poll()) == []
    assert w.status == "unavailable"


def test_allowed_for():
    assert not allowed_for(None, "Discord")
    assert not allowed_for({"enabled": False, "apps": ["Discord"]}, "Discord")
    assert not allowed_for({"enabled": True, "apps": ["Steam"]}, "Discord")
    assert allowed_for({"enabled": True, "apps": ["Discord"]}, "Discord")
