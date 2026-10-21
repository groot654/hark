import time

from togo.engine.eventbus import EventBus
from togo.engine.reminders import ReminderScheduler


def test_settings_round_trip(store):
    assert store.get_setting("missing", 3) == 3
    store.set_setting("dictation.dictionary", {"a": "b"})
    store.set_setting("dictation.dictionary", {"c": "d"})
    assert store.get_setting("dictation.dictionary") == {"c": "d"}


def test_memories_upsert_and_forget(store):
    store.remember("sister", "Sister is Ayesha")
    store.remember("sister", "Sister is Sara")
    assert [m["value"] for m in store.list_memories()] == ["Sister is Sara"]
    assert store.forget("sara") == 1
    assert store.list_memories() == []


def test_tasks(store):
    store.add_task("buy milk")
    store.add_task("buy milk and bread")
    assert store.complete_task("milk") == "buy milk"  # shortest match wins
    assert [t["title"] for t in store.open_tasks()] == ["buy milk and bread"]
    assert store.clear_completed_tasks() == 1


def test_habit_logging_is_idempotent(store):
    store.log_habit("reading", "2026-10-20")
    store.log_habit("reading", "2026-10-20")
    store.log_habit("reading", "2026-10-21")
    assert store.habit_days("reading") == ["2026-10-21", "2026-10-20"]


def test_routines(store):
    store.save_routine("morning", ["open spotify", "good morning"])
    assert store.get_routine("morning") == ["open spotify", "good morning"]
    assert store.get_routine("night") is None


def test_conversation_history_order(store):
    cid = store.new_conversation()
    for i in range(5):
        store.add_message(cid, "user", f"m{i}")
    assert [m["content"] for m in store.recent_messages(cid, limit=3)] == ["m2", "m3", "m4"]


def test_export_and_clear(store):
    store.add_note("hello")
    store.set_setting("keep", True)
    assert store.export_all()["notes"][0]["body"] == "hello"
    store.clear_all()
    assert store.recent_notes() == []
    assert store.get_setting("keep") is True  # settings survive a data wipe


def test_scheduler_fires_due_reminders_once(store):
    bus = EventBus()
    sched = ReminderScheduler(store, bus)
    store.add_reminder("stretch", time.time() - 1)
    store.add_reminder("later", time.time() + 3600)
    sched.tick(time.time())
    assert [r["text"] for r in store.upcoming_reminders()] == ["later"]
    sched.tick(time.time())
    assert store.due_reminders(time.time()) == []


def test_scheduler_ends_finished_focus(store):
    store.start_focus(1, "essay")
    ReminderScheduler(store, EventBus()).tick(time.time() + 61)
    assert store.active_focus() is None


def test_scheduler_announces_focus_end(store):
    bus = EventBus()
    events = []
    bus.publish = lambda kind, **data: events.append(kind)
    store.start_focus(1, None)
    ReminderScheduler(store, bus).tick(time.time() + 61)
    assert events == ["focus.ended", "notify"]
