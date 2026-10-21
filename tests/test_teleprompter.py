import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from togo.app.look import get_look  # noqa: E402
from togo.app.teleprompter import LINE_HEIGHT, ScriptPacer, Teleprompter, wrap_lines  # noqa: E402

SCRIPT = "one two three four five six seven eight\n\nnine ten eleven twelve"


def test_pacer_moves_only_while_speaking():
    pacer = ScriptPacer(SCRIPT, words_per_second=2.0)
    pacer.advance(1.0, speaking=False)
    assert pacer.position == 0
    pacer.advance(1.5, speaking=True)
    assert pacer.position == 3.0
    pacer.paused = True
    pacer.advance(1.0, speaking=True)
    assert pacer.position == 3.0


def test_pacer_stops_at_the_end():
    pacer = ScriptPacer(SCRIPT, words_per_second=10)
    pacer.advance(5, speaking=True)
    assert pacer.finished and pacer.progress == 1.0
    assert pacer.position == pacer.total == 12


def test_nudge_is_clamped():
    pacer = ScriptPacer(SCRIPT)
    pacer.nudge(-5)
    assert pacer.position == 0
    pacer.nudge(100)
    assert pacer.position == 12


def test_empty_script_counts_as_finished():
    assert ScriptPacer("   ").finished


def test_wrap_keeps_word_ranges_and_paragraphs():
    lines = wrap_lines(SCRIPT, width=20, measure=lambda text: len(text) * 1.0)
    words = [w for line in lines for w in line.words]
    assert words == SCRIPT.split()
    assert all(sum(map(len, line.words)) + len(line.words) - 1 <= 20 for line in lines if len(line.words) > 1)
    assert any(not line.words for line in lines)  # the blank line between paragraphs
    for line in lines:
        assert line.end - line.start == len(line.words)
    assert lines[-1].end == 12 and lines[-1].words


def test_wrap_puts_an_overlong_word_on_its_own_line():
    lines = wrap_lines("a supercalifragilistic b", width=5, measure=lambda text: len(text) * 1.0)
    assert [line.words for line in lines] == [["a"], ["supercalifragilistic"], ["b"]]


@pytest.fixture(scope="module")
def qt():
    return QApplication.instance() or QApplication([])


def test_window_scrolls_to_new_lines_and_closes(qt):
    prompter = Teleprompter("word " * 200, get_look("arc"))
    prompter.start()
    prompter._timer.stop()
    closed = []
    prompter.closed.connect(lambda: closed.append(True))
    assert not prompter.grab().isNull()
    prompter.pacer.nudge(len(prompter.lines[0].words) + 1)
    prompter._tick()
    assert prompter._shown_line == 1
    assert 0 < prompter._scroll <= LINE_HEIGHT  # gliding up into place
    for _ in range(40):
        prompter._tick()
    assert prompter._scroll == 0.0
    prompter.toggle_pause()
    assert prompter.pacer.paused and not prompter.grab().isNull()
    prompter.close()
    assert closed == [True]
