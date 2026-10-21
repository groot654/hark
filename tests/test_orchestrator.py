import pytest

from conftest import FakeLLM, NoApps
from hark.engine.core import orchestrator as orch_module
from hark.engine.core.orchestrator import Orchestrator
from hark.engine.eventbus import EventBus


@pytest.fixture(autouse=True)
def _no_step_delay(monkeypatch):
    monkeypatch.setattr(orch_module.time, "sleep", lambda _s: None)


def make(store, *replies):
    llm = FakeLLM(*replies)
    return Orchestrator(store, llm, NoApps(), EventBus()), llm


def test_task_flow(store):
    o, _ = make(store)
    assert o.handle("add buy milk to my list")["say"] == "Added “buy milk” to your list."
    listed = o.handle("what's on my to-do list")
    assert listed["card"]["items"] == ["buy milk"]
    assert o.handle("mark buy milk as done")["say"] == "Done: buy milk."


def test_reminder_extracts_what_and_when(store):
    o, _ = make(store)
    say = o.handle("remind me in 10 minutes to call mum")["say"]
    assert say.startswith("I'll remind you in 10 minutes") and say.endswith("to call mum.")
    assert store.upcoming_reminders()[0]["text"] == "call mum"


def test_reminder_without_time_asks(store):
    o, _ = make(store)
    out = o.handle("remind me to call mum")
    assert out["status"] == "needs_input"


def test_destructive_command_needs_confirmation(store):
    store.add_task("x")
    store.complete_task("x")
    o, _ = make(store)
    out = o.handle("clear completed tasks")
    assert "can't be undone" in out["say"]
    assert "confirm_id" in out
    assert o.handle("yes")["say"] == "Cleared 1 finished tasks."


def test_confirmation_can_be_declined_by_voice(store):
    o, _ = make(store)
    store.remember("k", "secret")
    assert "confirm_id" in o.handle("forget secret")
    assert o.handle("no")["say"] == "Cancelled."
    assert store.list_memories()


def test_confirm_endpoint_path(store):
    o, _ = make(store)
    store.remember("k", "secret")
    cid = o.handle("forget secret")["confirm_id"]
    assert o.confirm(cid, True)["say"] == "Forgotten."
    assert o.confirm(cid, True)["say"] == "That request expired."


def test_noise_is_ignored(store):
    o, llm = make(store)
    out = o.handle("Thanks for watching!")
    assert out["say"] == ""
    assert llm.calls == []


def test_routine_save_and_run(store):
    o, _ = make(store)
    saved = o.handle("create a routine called wind down to mute and then add stretch to my list")
    assert saved["say"] == "Saved routine “wind down” with 2 steps."
    assert store.get_routine("wind down") == ["mute", "add stretch to my list"]
    o.tools.tools["volume.mute"].run = lambda a: orch_module.ToolResult(say="Muted.")
    out = o.handle("run my wind down routine")
    assert out["say"] == "Muted. Added “stretch” to your list."
    assert [t["title"] for t in store.open_tasks()] == ["stretch"]


def test_forget_reports_when_nothing_matched(store):
    o, _ = make(store)
    cid = o.handle("forget my blood type")["confirm_id"]
    assert o.confirm(cid, True)["say"] == "I didn't have anything about that."


def test_llm_router_picks_a_tool(store):
    o, _ = make(store, {"tool": "task.add", "args": {"title": "renew passport"}})
    assert o.handle("I really must not forget the passport renewal")["say"] == "Added “renew passport” to your list."


def test_llm_router_cannot_trigger_shutdown(store):
    o, _ = make(store, {"tool": "system.shutdown", "args": {}}, "I can't do that from a guess.")
    out = o.handle("make everything go dark forever")
    assert out["say"] == "I can't do that from a guess."


def test_chat_fallback_uses_memories(store):
    store.remember("name", "The user's name is Rauf")
    o, llm = make(store, {"tool": None}, "Hello Rauf!")
    assert o.handle("who am I")["say"] == "Hello Rauf!"
    system_prompt = llm.calls[1][0]["content"]
    assert "Rauf" in system_prompt


def test_without_a_model_commands_still_work(store):
    o, _ = make(store)
    assert "AI model" in o.handle("tell me a joke about cats")["say"]
    assert o.handle("take a note that milk is out")["say"] == "Noted."


def test_write_inserts_text(store):
    o, _ = make(store, "Hi Sam, running ten minutes late.")
    out = o.handle("write a message to Sam saying I'm late", {"app": "whatsapp"})
    assert out["client_actions"] == [{"type": "insert_text", "text": "Hi Sam, running ten minutes late."}]


def test_rewrite_uses_selection(store):
    o, llm = make(store, "Could you send the report?")
    out = o.handle("make this more polite", selection="send the report")
    assert out["client_actions"][0]["text"] == "Could you send the report?"
    assert "send the report" in llm.calls[0][1]["content"]


def test_agent_mode_runs_known_steps_and_skips_unknown(store):
    o, _ = make(store, {"steps": ["add pack bags to my list", "teleport to Paris", "take a note that flight is 9am"]})
    out = o.handle("take care of this: get me ready for the trip")
    assert "Added “pack bags”" in out["say"]
    assert "Noted." in out["say"]
    assert "skipped 1 step" in out["say"]


def test_briefing(store):
    store.add_task("call bank")
    o, _ = make(store)
    out = o.handle("good morning")
    assert "1 thing on your list" in out["say"]
    assert "call bank" in out["card"]["items"]


def test_summary_card(store):
    o, _ = make(store)
    assert o.summary_card()["items"] == ["Nothing on your list."]
    store.add_task("a")
    assert o.summary_card()["items"] == ["☐ a"]
