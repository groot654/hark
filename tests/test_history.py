import pytest

from conftest import FakeLLM, NoApps
from hark.engine.core import orchestrator as orch_module
from hark.engine.core.orchestrator import Orchestrator
from hark.engine.eventbus import EventBus


@pytest.fixture
def o(store):
    return Orchestrator(store, FakeLLM(), NoApps(), EventBus())


def test_every_exchange_is_kept(o, store):
    o.handle("add milk to my list")
    o.handle("what's on my to-do list")
    [conv] = store.conversations()
    assert conv["title"] == "add milk to my list" and conv["messages"] == 4
    assert [(m["role"], m["content"]) for m in store.conversation_messages(conv["id"])] == [
        ("user", "add milk to my list"), ("assistant", "Added “milk” to your list."),
        ("user", "what's on my to-do list"), ("assistant", "To-do: milk"),
    ]


def test_noise_is_not_kept(o, store):
    o.handle("Thanks for watching!")
    assert store.conversations() == []


def test_written_text_is_not_kept(store):
    o = Orchestrator(store, FakeLLM("Dear Sam, the report is attached."), NoApps(), EventBus())
    o.handle("write an email to Sam saying the report is attached")
    messages = store.conversation_messages(store.conversations()[0]["id"])
    assert messages[1]["content"] == "(Wrote it into the app.)"


def test_quiet_starts_a_new_conversation(o, store, monkeypatch):
    o.handle("add milk to my list")
    monkeypatch.setattr(orch_module, "CONVERSATION_IDLE_S", -1)
    o.handle("add eggs to my list")
    assert len(store.conversations()) == 2


def test_new_and_continue(o, store):
    o.handle("add milk to my list")
    first = store.conversations()[0]["id"]
    o.new_conversation()
    o.handle("add eggs to my list")
    o.continue_conversation(first)
    o.handle("add bread to my list")
    by_id = {c["id"]: c["messages"] for c in store.conversations()}
    assert by_id[first] == 4 and len(by_id) == 2


def test_chat_model_sees_earlier_turns_but_not_the_current_one(store):
    llm = FakeLLM({"tool": None}, "Hello!", {"tool": None}, "Still here.")
    o = Orchestrator(store, llm, NoApps(), EventBus())
    o.handle("hi there")
    o.handle("are you still there")
    chat_messages = llm.calls[3]  # second conversational reply
    assert [m["content"] for m in chat_messages[1:]] == ["hi there", "Hello!", "are you still there"]
