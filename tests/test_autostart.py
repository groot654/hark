import winreg

import pytest

from hark.app import autostart

TEST_KEY = r"Software\Hark\test-run"  # never the real Run key


@pytest.fixture
def key():
    yield TEST_KEY
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, TEST_KEY)
    except OSError:
        pass


def test_enable_and_disable(key):
    assert not autostart.is_enabled(key)
    autostart.set_enabled(True, key)
    assert autostart.is_enabled(key)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
        command, _ = winreg.QueryValueEx(k, autostart.VALUE)
    assert command == autostart.launch_command()
    autostart.set_enabled(False, key)
    autostart.set_enabled(False, key)  # harmless when already off
    assert not autostart.is_enabled(key)


def test_from_source_starts_without_a_console():
    command = autostart.launch_command()
    assert command.endswith(" -m hark") and "pythonw.exe" in command
