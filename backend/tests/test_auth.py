import pytest

from auth import AuthError, AuthManager


def test_pin_is_four_digits(tmp_path):
    for _ in range(50):
        pin = AuthManager(tmp_path).pin
        assert len(pin) == 4 and pin.isdigit()


def test_correct_pin_returns_token_and_token_works(tmp_path):
    a = AuthManager(tmp_path, pin="1234")
    token = a.pair_with_pin("1234", "10.0.0.5", "Galaxy Tab")
    assert len(token) > 30
    assert a.verify_token(token)
    assert a.device_name(token) == "Galaxy Tab"
    assert not a.verify_token("not-a-token")
    assert not a.verify_token(None)


def test_token_survives_restart_but_pin_changes(tmp_path):
    token = AuthManager(tmp_path, pin="1111").pair_with_pin("1111", "10.0.0.5")
    again = AuthManager(tmp_path)          # new process -> new random PIN
    assert again.verify_token(token)
    assert token not in (tmp_path / "paired_devices.json").read_text()   # only hashes stored


def test_wrong_pin_then_lockout(tmp_path):
    a = AuthManager(tmp_path, pin="1234", max_attempts=3, lockout_seconds=60)
    for _ in range(2):
        with pytest.raises(AuthError) as e:
            a.pair_with_pin("0000", "10.0.0.9")
        assert e.value.reason == "invalid_pin"
    with pytest.raises(AuthError) as e:
        a.pair_with_pin("0000", "10.0.0.9")
    assert e.value.reason == "locked_out" and e.value.retry_after == 60
    # even the right PIN is refused while locked
    with pytest.raises(AuthError) as e:
        a.pair_with_pin("1234", "10.0.0.9")
    assert e.value.reason == "locked_out"
    # other devices are not affected
    assert a.pair_with_pin("1234", "10.0.0.10")


def test_revoke_all(tmp_path):
    a = AuthManager(tmp_path, pin="1234")
    t = a.pair_with_pin("1234", "1.1.1.1")
    assert a.revoke_all() == 1
    assert not a.verify_token(t)


def test_corrupted_device_file_does_not_crash(tmp_path):
    (tmp_path / "paired_devices.json").write_text("{broken")
    assert AuthManager(tmp_path).paired_devices() == []
