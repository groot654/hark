import pytest

from conftest import FakeLLM
from hark.engine.core.dictation import app_style, clean, expand_snippet, format_dictation, polish
from hark.engine.core.transcript_filter import is_noise


@pytest.mark.parametrize(
    ("heard", "expected"),
    [
        ("um so I think we should uh go", "So I think we should go."),
        ("hello comma how are you question mark", "Hello, how are you?"),
        ("i think i can", "I think I can."),
        ("the the meeting is at noon", "The meeting is at noon."),
        ("meet at 5 make that 6", "Meet at 6."),
        ("first line new line second line", "First line\nSecond line"),
        ("dear team new paragraph thanks for coming", "Dear team\n\nThanks for coming"),
        ("shopping list bullet eggs bullet milk", "Shopping list\n- Eggs\n- Milk"),
        ("steps number one wash number two dry", "Steps\n1. Wash\n2. Dry"),
        ("she said open quote hi close quote", "She said “hi”."),
    ],
)
def test_clean_formal(heard, expected):
    assert clean(heard, "formal") == expected


@pytest.mark.parametrize(
    ("heard", "expected"),
    [
        ("send it Tuesday. Scratch that. Send it Wednesday", "Send it Wednesday."),
        ("hi John, see you at 5, scratch that, see you at 6", "Hi John, see you at 6."),
        ("scratch that hello", "Hello."),
        ("call Sam, actually no scratch that", "Call Sam."),
    ],
)
def test_scratch_that_removes_the_previous_clause(heard, expected):
    assert clean(heard, "formal") == expected


def test_casual_style_drops_final_full_stop():
    assert clean("see you soon", "casual") == "See you soon"


def test_code_style_keeps_case():
    assert clean("myVariable equals 5", "code") == "myVariable equals 5"


def test_dictionary_replacements():
    assert clean("ping hark about cooper netties", "formal", {"cooper netties": "Kubernetes"}) == \
        "Ping hark about Kubernetes."


def test_app_style():
    assert app_style("WhatsApp") == "casual"
    assert app_style("Code") == "code"
    assert app_style("winword") == "formal"


def test_snippets_fire_only_on_their_own():
    snippets = {"my address": "1 Main Street"}
    assert expand_snippet("my address.", snippets) == "1 Main Street"
    assert expand_snippet("insert my address", snippets) == "1 Main Street"
    assert expand_snippet("send it to my address", snippets) is None


def test_exact_mode_is_untouched():
    assert format_dictation("um hello", "exact", "") == "um hello"


def test_format_uses_store_snippets(store):
    store.set_setting("dictation.snippets", {"sign off": "Best,\nRauf"})
    assert format_dictation("sign off", "clean", "outlook", store) == "Best,\nRauf"


def test_polish_accepts_faithful_rewrite():
    llm = FakeLLM("Call me at 5:30 tomorrow.")
    assert polish("call me at 5:30 tomorrow.", llm) == "Call me at 5:30 tomorrow."


def test_polish_rejects_changed_numbers():
    llm = FakeLLM("Call me at 6:30 tomorrow.")
    assert polish("call me at 5:30 tomorrow.", llm) is None


def test_polished_falls_back_to_clean_without_a_model():
    assert format_dictation("um hello there", "polished", "", llm=FakeLLM()) == "Hello there."


@pytest.mark.parametrize("text", ["", "  ", "Thanks for watching!", "[Music]", "(applause)", "you",
                                  "the the the the the the"])
def test_noise(text):
    assert is_noise(text)


@pytest.mark.parametrize("text", ["thank you", "open spotify", "yes"])
def test_not_noise(text):
    assert not is_noise(text)
