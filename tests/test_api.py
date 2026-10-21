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


def test_summary_reports_running_focus(client):
    assert client.get("/v1/productivity/summary").json()["focus"] == {"type": "focus", "ends_at": None}
    client.post("/v1/chat", json={"text": "start a 25 minute focus session"})
    focus = client.get("/v1/productivity/summary").json()["focus"]
    assert focus["minutes"] == 25 and focus["ends_at"] > 0


def test_notify_shows_a_message(client, engine):
    seen = []
    engine.bus.publish = lambda kind, **data: seen.append((kind, data))
    assert client.post("/v1/system/notify", json={"text": "Build finished"}).json() == {"ok": True}
    assert seen == [("notify", {"title": "Hark", "text": "Build finished"})]
    assert client.post("/v1/system/notify", json={"text": ""}).status_code == 422


def wav_of(seconds):
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\0\0" * int(16000 * seconds))
    return buf.getvalue()


def listen_wake(client, engine, heard):
    engine.stt.transcribe = lambda samples: heard
    files = {"audio": ("a.wav", wav_of(1), "audio/wav")}
    return client.post("/v1/listen", files=files, data={"mode": "wake", "target": "{}"}).json()


def test_wake_runs_the_command_after_the_phrase(client, engine):
    out = listen_wake(client, engine, "Hey hark, take a note that the bins go out Tuesday.")
    assert out["wake"] is True
    assert out["transcript"] == "take a note that the bins go out Tuesday."
    assert out["say"] == "Noted."


def test_wake_phrase_alone_asks_for_a_follow_up(client, engine):
    assert listen_wake(client, engine, "Hey Hark!") == {"transcript": "Hey Hark!", "wake": True, "follow_up": True,
                                                         "client_actions": []}


def test_background_speech_is_dropped_without_its_text(client, engine):
    assert listen_wake(client, engine, "Hey Mark, take a note") == {"transcript": "", "wake": False,
                                                                     "client_actions": []}
    assert client.get("/v1/data/export").json()["notes"] == []


def tool(client, name, **args):
    return client.post("/v1/integrations/tool", json={"name": name, "args": args})


def test_integrations_reach_lists_and_timers(client):
    assert tool(client, "task.add", title="ship v2").json() == {"ok": True, "text": "Added “ship v2” to your list.",
                                                               "items": None}
    listed = tool(client, "task.list").json()
    assert listed["items"] == ["ship v2"]
    assert tool(client, "focus.status").json()["text"] == "No focus session is running."
    assert tool(client, "focus.start", minutes=15).json()["ok"]
    assert "of 15 minutes left" in tool(client, "focus.status").json()["text"]


def test_integrations_cannot_type_click_open_delete_or_read_memory(client):
    for name in ("input.type", "input.keys", "ui.click", "app.open", "web.open", "system.shutdown",
                 "task.clear_completed", "memory.list", "memory.forget", "persona.thanks"):
        assert tool(client, name, text="x").status_code == 403, name


def test_integration_focus_start_reaches_the_notch(client, engine):
    seen = []
    engine.bus.publish = lambda kind, **data: seen.append((kind, data))
    tool(client, "focus.start", minutes=10)
    [(kind, data)] = [e for e in seen if e[0] == "client.actions"]
    assert data["actions"][0]["type"] == "focus" and data["actions"][0]["minutes"] == 10
