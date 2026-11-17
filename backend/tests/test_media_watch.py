import asyncio

from media_watch import MediaWatcher, app_name


def test_app_names():
    assert app_name("Spotify.exe") == "Spotify"
    assert app_name("SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify") == "Spotify"
    assert app_name("MSEdge") == "Edge"
    assert app_name("chrome") == "Chrome"
    assert app_name("Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic") == "Media Player"
    assert app_name("C:\\Program Files\\VideoLAN\\VLC\\vlc.exe") == "VLC"
    assert app_name("someplayer") == "Someplayer"
    assert app_name("") == ""


def test_unavailable_without_windows_packages():
    w = MediaWatcher()
    assert asyncio.run(w.read()) == {"available": False}
    assert asyncio.run(w.read()) == {"available": False}   # doesn't retry the import every second


class FakeInfo:
    def __init__(self, status):
        self.playback_status = status


class FakeProps:
    title, artist = "Shape of You", "Ed Sheeran"


class FakeSession:
    source_app_user_model_id = "Spotify.exe"

    def __init__(self, status):
        self.status = status

    def get_playback_info(self):
        return FakeInfo(self.status)

    async def try_get_media_properties_async(self):
        return FakeProps()


class FakeManager:
    def __init__(self, session):
        self.session = session

    def get_current_session(self):
        return self.session


def read_with(session):
    w = MediaWatcher()
    w._manager = FakeManager(session)
    return asyncio.run(w.read())


def test_reads_playing_song():
    assert read_with(FakeSession(4)) == {"available": True, "active": True, "playing": True,
                                         "title": "Shape of You", "artist": "Ed Sheeran", "app": "Spotify"}
    assert read_with(FakeSession(5))["playing"] is False


def test_nothing_playing():
    s = read_with(None)
    assert s["available"] and not s["active"] and not s["playing"]
