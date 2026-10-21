import pytest
from fastapi.testclient import TestClient

from conftest import FakeLLM
from hark.engine.main import Engine
from hark.engine.security import HEADER


@pytest.fixture
def engine():
    eng = Engine()
    eng.llm = FakeLLM()
    eng.orchestrator.llm = eng.llm
    return eng


@pytest.fixture
def client(engine):
    with TestClient(engine.build_app()) as c:
        c.headers[HEADER] = engine.token
        yield c


def test_requests_without_token_are_rejected(engine):
    with TestClient(engine.build_app()) as c:
        assert c.get("/v1/memory").status_code == 401
        assert c.get("/v1/memory", headers={HEADER: "wrong"}).status_code == 401


def test_token_written_for_client(engine):
    from hark.engine.security import read_token

    assert read_token() == engine.token


def test_chat_runs_a_command(client):
    out = client.post("/v1/chat", json={"text": "take a note that the cat is fed"}).json()
    assert out["transcript"] == "take a note that the cat is fed"
    assert out["say"] == "Noted."


def test_confirm_round_trip(client):
    client.post("/v1/chat", json={"text": "remember that my pin is secret"})
    pending = client.post("/v1/chat", json={"text": "forget pin"}).json()
    out = client.post("/v1/confirm", json={"id": pending["confirm_id"], "approved": True}).json()
    assert out["say"] == "Forgotten."
    assert client.get("/v1/memory").json() == {"memories": []}


def test_polish_endpoint(client):
    out = client.post("/v1/dictation/polish", json={"text": "um hello comma world", "style": "clean"}).json()
    assert out == {"text": "Hello, world."}


def test_summary_export_and_clear(client):
    client.post("/v1/chat", json={"text": "add water plants to my list"})
    assert client.get("/v1/productivity/summary").json()["card"]["items"] == ["☐ water plants"]
    assert client.get("/v1/data/export").json()["tasks"][0]["title"] == "water plants"
    assert client.post("/v1/data/clear").json() == {"ok": True}
    assert client.get("/v1/data/export").json()["tasks"] == []
