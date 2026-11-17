"""What is playing on the PC right now, read from Windows' media controls.

Windows keeps a list of apps that play media (Spotify, Chrome, Edge, the Media Player app...) --
the same list behind the volume pop-up. This module reads the current one so the tablet can show
the real play/pause state and the song. It never changes anything; the media keys in executor.py do that.

If the Windows packages are missing (or this isn't Windows) read() returns {"available": False}
and the tablet just shows a plain play/pause button.
"""
from __future__ import annotations

import logging

log = logging.getLogger("media")

PLAYING = 4  # GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING

# app ids Windows reports -> the name to show
_KNOWN_APPS = {
    "chrome": "Chrome", "msedge": "Edge", "firefox": "Firefox", "opera": "Opera", "brave": "Brave",
    "spotify": "Spotify", "vlc": "VLC", "zunemusic": "Media Player", "zunevideo": "Films & TV",
    "microsoft.media.player": "Media Player", "discord": "Discord", "steam": "Steam",
}

NOTHING = {"available": True, "active": False, "playing": False, "title": "", "artist": "", "app": ""}


def app_name(app_id: str) -> str:
    """'Spotify.exe' -> 'Spotify', 'SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify' -> 'Spotify',
    'MSEdge' -> 'Edge'. Unknown ids come back tidied up rather than raw."""
    s = (app_id or "").strip()
    if not s:
        return ""
    if "!" in s:                       # packaged (Store) app: the part after "!" is the app's own name
        s = s.split("!")[-1]
    s = s.split("\\")[-1]
    if s.lower().endswith(".exe"):
        s = s[:-4]
    key = s.lower()
    for known, name in _KNOWN_APPS.items():
        if key == known or key.endswith("." + known):
            return name
    return s[:1].upper() + s[1:]


class MediaWatcher:
    def __init__(self):
        self._manager = None
        self._failed = False

    async def _get_manager(self):
        if self._manager is None and not self._failed:
            try:
                from winrt.windows.media.control import (
                    GlobalSystemMediaTransportControlsSessionManager as Manager,
                )
                self._manager = await Manager.request_async()
            except Exception as exc:  # not Windows, packages missing, or Windows refused
                self._failed = True
                log.info("Media state unavailable (%s) -- the tablet shows a plain play/pause button", exc)
        return self._manager

    async def read(self) -> dict:
        manager = await self._get_manager()
        if manager is None:
            return {"available": False}
        try:
            session = manager.get_current_session()
            if session is None:
                return dict(NOTHING)
            info = session.get_playback_info()
            playing = int(info.playback_status) == PLAYING if info else False
            title = artist = ""
            try:
                props = await session.try_get_media_properties_async()
                title, artist = props.title or "", props.artist or ""
            except Exception:
                pass  # some apps don't share the song name; the play state still works
            return {"available": True, "active": True, "playing": playing, "title": title, "artist": artist,
                    "app": app_name(session.source_app_user_model_id)}
        except Exception as exc:
            log.debug("media read failed: %s", exc)
            return dict(NOTHING)
