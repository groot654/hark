import hashlib
import threading
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler

import pytest

from hark.engine.core.local_model import Asset, LocalModel, LocalModelError, _download


@pytest.fixture
def served(tmp_path):
    root = tmp_path / "www"
    root.mkdir()
    (root / "file.bin").write_bytes(b"hello model")
    handler = partial(SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/file.bin"
    server.shutdown()


def test_download_verifies_and_reports(served, tmp_path):
    seen = []
    asset = Asset(served, hashlib.sha256(b"hello model").hexdigest(), 11)
    dest = tmp_path / "out.bin"
    _download(asset, dest, seen.append)
    assert dest.read_bytes() == b"hello model"
    assert sum(seen) == 11
    assert not (tmp_path / "out.bin.part").exists()


def test_download_rejects_wrong_hash(served, tmp_path):
    dest = tmp_path / "out.bin"
    with pytest.raises(LocalModelError):
        _download(Asset(served, "0" * 64, 11), dest)
    assert not dest.exists()
    assert not (tmp_path / "out.bin.part").exists()


def test_status_before_start(tmp_path):  # small by default
    model = LocalModel(tmp_path)
    assert not model.installed
    assert model.status() == {"state": "idle", "progress": 0.0, "error": None, "model": "qwen3.5-0.8b"}


def test_sizes_have_pinned_files_and_names(tmp_path):
    from hark.engine.core.local_model import MODELS

    assert list(MODELS) == ["small", "medium", "large"]
    for size, choice in MODELS.items():
        model = LocalModel(tmp_path, size=size)
        assert model.model_path.name == choice.asset.filename
        assert len(choice.asset.sha256) == 64 and choice.asset.size > 0
        assert model.status()["model"] == choice.name
    assert [m.ram_gb for m in MODELS.values()] == sorted(m.ram_gb for m in MODELS.values())


def test_unknown_size_falls_back_to_small(tmp_path):
    assert LocalModel(tmp_path, size="huge").choice.name == "qwen3.5-0.8b"


def test_memory_warning(tmp_path, monkeypatch):
    import psutil

    class Mem:
        available = 1.2e9

    monkeypatch.setattr(psutil, "virtual_memory", lambda: Mem)
    assert LocalModel(tmp_path, size="small").memory_short() is None
    assert LocalModel(tmp_path, size="large").memory_short() == 1.2
