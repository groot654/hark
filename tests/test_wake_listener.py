import numpy as np

from hark.app.wake_listener import BurstCollector, Endpointer, frames

SILENT, SPEECH = 0, 1


def stream(*parts):
    """('speech'|'silence', seconds) pairs -> frames whose first sample says which they are."""
    out = []
    for kind, seconds in parts:
        out += [np.full(512, SPEECH if kind == "speech" else SILENT, np.int16)] * frames(seconds)
    return out


def collect(frames_in, **kw):
    bursts = []
    collector = BurstCollector(lambda f: float(f[0]), bursts.append, **kw)
    for f in frames_in:
        collector.feed(f)
    return bursts


def test_a_burst_includes_the_audio_just_before_speech_started():
    [burst] = collect(stream(("silence", 2), ("speech", 1.5), ("silence", 1)))
    seconds = burst.size / 16000
    assert 1.5 + 0.4 < seconds < 1.5 + 0.45 + 0.6 + 0.1  # preroll + speech + end-of-burst silence
    assert burst[0] == SILENT  # starts with preroll


def test_separate_sentences_give_separate_bursts():
    bursts = collect(stream(("speech", 1), ("silence", 1), ("speech", 2), ("silence", 1)))
    assert len(bursts) == 2


def test_short_pauses_stay_in_one_burst():
    bursts = collect(stream(("speech", 1), ("silence", 0.3), ("speech", 1), ("silence", 1)))
    assert len(bursts) == 1


def test_clicks_are_ignored():
    assert collect(stream(("speech", 0.1), ("silence", 1))) == []


def test_long_talk_is_cut_into_chunks():
    bursts = collect(stream(("speech", 20), ("silence", 1)), max_s=9)
    assert len(bursts) >= 2
    assert all(b.size / 16000 <= 9.05 for b in bursts)


def run(endpointer, *parts):
    verdict = "continue"
    for f in stream(*parts):
        verdict = endpointer.feed(float(f[0]))
        if verdict != "continue":
            return verdict
    return verdict


def test_request_ends_after_a_pause():
    assert run(Endpointer(), ("silence", 0.5), ("speech", 2), ("silence", 1)) == "end"


def test_no_request_is_cancelled():
    assert run(Endpointer(no_speech_s=5), ("silence", 6)) == "cancel"


def test_long_request_is_capped():
    assert run(Endpointer(max_s=15), ("speech", 16)) == "end"


def test_still_talking_continues():
    assert run(Endpointer(), ("speech", 3)) == "continue"


def test_take_hands_over_a_burst_in_progress():
    bursts = []
    collector = BurstCollector(lambda f: float(f[0]), bursts.append)
    for f in stream(("silence", 1), ("speech", 0.5)):
        collector.feed(f)
    taken, flags = collector.take()
    assert len(taken) == len(flags) and sum(flags) == frames(0.5)
    assert not flags[0]  # starts with the quiet just before speech
    for f in stream(("silence", 1)):
        collector.feed(f)
    assert bursts == []  # handed over, so not reported again
    assert collector.take() == ([], [])


def test_endpointer_primed_with_speech_ends_at_the_next_pause():
    endpointer = Endpointer()
    for _ in range(frames(1.0)):
        endpointer.feed(1.0)
    assert run(endpointer, ("silence", 1)) == "end"
