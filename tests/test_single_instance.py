from hark import single_instance
from hark.engine.security import HEADER


def test_header_matches_the_engine():
    assert single_instance.TOKEN_HEADER == HEADER


def test_second_acquire_is_refused_until_the_first_is_released():
    first = single_instance.acquire()
    assert first is not None
    assert single_instance.acquire() is None
    first.Close()
    again = single_instance.acquire()
    assert again is not None
    again.Close()


def test_lock_is_per_data_folder(tmp_path, monkeypatch):
    name = single_instance.mutex_name()
    monkeypatch.setenv("HARK_DATA_DIR", str(tmp_path / "other"))
    assert single_instance.mutex_name() != name


def test_notify_without_a_running_hark_is_harmless():
    assert single_instance.notify_running() is False
