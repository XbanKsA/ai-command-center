import pytest

from executor import Executor, match_app, normalize


def names(result):
    return [e.name for e, _ in result.candidates]


def test_normalize():
    assert normalize("  Google   Chrome! ") == "google chrome"
    assert normalize("Notepad++") == "notepad++"
    assert normalize("افتح كروم") == "افتح كروم"


@pytest.mark.parametrize("query,expected", [
    ("chrome", "Google Chrome"),          # alias
    ("Google Chrome", "Google Chrome"),   # exact
    ("spotify", "Spotify"),               # not "Uninstall Spotify"
    ("vs code", "Visual Studio Code"),    # alias
    ("notepad", "Notepad"),               # not Notepad++
    ("notepad++", "Notepad++"),
    ("steam", "Steam"),
    ("كروم", "Google Chrome"),            # Arabic alias
    ("discrod", "Discord"),               # typo -> still found? (fuzzy)
])
def test_match_app(fake_index, query, expected):
    r = match_app(query, fake_index.entries)
    if query == "discrod":
        assert expected in names(r)       # typo => offered as candidate, never auto-launched blindly
    else:
        assert r.status == "match", (query, r.status, names(r))
        assert r.best.name == expected


def test_ambiguous_returns_options(fake_index):
    r = match_app("visual studio", fake_index.entries)
    assert r.status == "ambiguous"
    assert {"Visual Studio Code", "Visual Studio 2022"} <= set(names(r))


def test_no_match(fake_index):
    assert match_app("photoshop", fake_index.entries).status == "none"
    assert match_app("", fake_index.entries).status == "none"


def test_search(fake_index):
    assert fake_index.search("spot")[0]["name"] == "Spotify"
    assert len(fake_index.search("")) == len({e.norm for e in fake_index.entries})


def test_url_normalization():
    n = Executor.normalize_url
    assert n("youtube.com") == "https://youtube.com"
    assert n("http://x.org/a?b=1") == "http://x.org/a?b=1"
    assert n("file:///C:/Windows") is None
    assert n("javascript:alert(1)") is None
    assert n("not a url") is None
    assert n("localhost") is None


def test_dry_run_actions(dry_executor):
    ex = dry_executor
    assert ex.launch_target("spotify").ok
    assert ex.launch_target("https://github.com").ok
    assert not ex.launch_target("visual studio").ok and ex.launch_target("visual studio").data["ambiguous"]
    assert not ex.launch_target("photoshop").ok
    assert not ex.launch_target(r"C:\does\not\exist.exe").ok
    assert ex.media("volume_up").ok
    assert not ex.media("explode").ok
    for fn in (ex.lock_pc, ex.sleep_pc, ex.shutdown_pc, ex.restart_pc, ex.cancel_shutdown):
        r = fn()
        assert r.ok and r.data["dry_run"]


def test_find_processes_never_returns_protected_or_self(dry_executor):
    found = dry_executor.find_processes("python")
    assert found == {}              # python is protected (that's us)
    assert dry_executor.find_processes("svchost") == {}
