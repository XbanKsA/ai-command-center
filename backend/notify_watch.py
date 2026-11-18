"""Reads the notifications Windows shows on this PC, so the tablet can show them too.

Nothing is sent anywhere by this module. main.py decides which tablet gets what: a tablet only
receives notifications after it turns the feature on, and only from the apps it picked.

Windows asks once for permission ("Let Kageon access your notifications?"). If it says no, or the
Windows packages are missing, status is "denied" / "unavailable" and nothing is read.
"""
from __future__ import annotations

import logging
from datetime import datetime

log = logging.getLogger("notify")

KEEP_APPS = 40  # remember up to this many app names to offer on the tablet


class NotificationWatcher:
    def __init__(self):
        self._listener = None
        self._kinds = None
        self._binding = None
        self.status = "starting"     # starting | ok | denied | unavailable
        self._seen: set[int] = set()
        self._primed = False         # the first read only remembers what's already there
        self.apps: list[str] = []    # app names seen so far, newest first

    async def _get_listener(self):
        if self._listener is not None or self.status in ("denied", "unavailable"):
            return self._listener
        try:
            from winrt.windows.ui.notifications import KnownNotificationBindings, NotificationKinds
            from winrt.windows.ui.notifications.management import (
                UserNotificationListener,
                UserNotificationListenerAccessStatus,
            )
            listener = UserNotificationListener.current
            access = await listener.request_access_async()
            if access != UserNotificationListenerAccessStatus.ALLOWED:
                self.status = "denied"
                log.info("Windows did not allow reading notifications (%s)", access)
                return None
            self._listener = listener
            self._kinds = NotificationKinds.TOAST
            self._binding = KnownNotificationBindings.toast_generic
            self.status = "ok"
        except Exception as exc:
            self.status = "unavailable"
            log.info("PC notifications unavailable (%s)", exc)
        return self._listener

    def _remember_app(self, name: str) -> bool:
        """Returns True if this app wasn't in the list before."""
        if not name:
            return False
        new = name not in self.apps
        if not new:
            self.apps.remove(name)
        self.apps.insert(0, name)
        del self.apps[KEEP_APPS:]
        return new

    def _read_one(self, n) -> dict:
        app = ""
        try:
            app = n.app_info.display_info.display_name
        except Exception:
            pass
        texts: list[str] = []
        try:
            binding = n.notification.visual.get_binding(self._binding)
            if binding is not None:
                texts = [t.text for t in binding.get_text_elements() if t.text]
        except Exception:
            pass
        when = ""
        try:
            when = n.creation_time.isoformat() if isinstance(n.creation_time, datetime) else str(n.creation_time)
        except Exception:
            pass
        return {"id": int(n.id), "app": app or "Windows", "title": texts[0] if texts else "",
                "text": " ".join(texts[1:]), "time": when}

    async def poll(self) -> list[dict]:
        """New notifications since the last call (oldest first). Also keeps self.apps up to date."""
        listener = await self._get_listener()
        if listener is None:
            return []
        try:
            current = [self._read_one(n) for n in await listener.get_notifications_async(self._kinds)]
        except Exception as exc:
            log.debug("reading notifications failed: %s", exc)
            return []
        new = [n for n in current if n["id"] not in self._seen]
        self._seen = {n["id"] for n in current}   # forget ones the user dismissed
        for n in reversed(new):
            self._remember_app(n["app"])
        if not self._primed:                      # don't replay what was already in the Action Center
            self._primed = True
            return []
        return new


def allowed_for(settings: dict | None, app: str) -> bool:
    """Does this tablet want notifications from this app? Off unless it said yes."""
    return bool(settings and settings.get("enabled") and app in (settings.get("apps") or []))
