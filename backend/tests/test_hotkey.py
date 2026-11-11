import pytest

from hotkey import GlobalHotkey, parse_hotkey


def test_parse_hotkey():
    assert parse_hotkey("ctrl+shift+q") == (0x0002 | 0x0004, ord("Q"))
    assert parse_hotkey("Ctrl + Alt + F12") == (0x0002 | 0x0001, 0x7B)
    assert parse_hotkey("win+shift+1") == (0x0008 | 0x0004, ord("1"))
    for bad in ("", "q", "ctrl+", "hyper+q", "ctrl+shift+arrow"):
        with pytest.raises(ValueError):
            parse_hotkey(bad)


def test_hotkey_not_windows_is_graceful():
    import sys
    hk = GlobalHotkey("ctrl+shift+q", lambda: None)
    if sys.platform != "win32":
        assert hk.start() is False and "Windows" in hk.error
