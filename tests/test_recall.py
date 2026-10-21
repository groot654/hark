import pytest

from hark.engine.core.recall import recall, second_person

MEMORIES = [
    {"key": "my name is rauf", "value": "My name is Rauf"},
    {"key": "i live in lahore", "value": "I live in Lahore"},
    {"key": "my sister's birthday is", "value": "My sister's birthday is on 3 March"},
    {"key": "i'm allergic to peanuts", "value": "I'm allergic to peanuts"},
]


@pytest.mark.parametrize(
    ("question", "answer"),
    [
        ("who am I", "Your name is Rauf."),
        ("what's my name?", "Your name is Rauf."),
        ("where do I live", "You live in Lahore."),
        ("when is my sister's birthday", "Your sister's birthday is on 3 March."),
        ("what am I allergic to", "You're allergic to peanuts."),
    ],
)
def test_answers_from_memory(question, answer):
    assert recall(question, MEMORIES) == answer


@pytest.mark.parametrize("question", ["what's the capital of Australia", "what's my favourite colour",
                                      "tell me a joke", "open my email"])
def test_no_answer_when_nothing_fits(question):
    assert recall(question, MEMORIES) is None


def test_no_memories():
    assert recall("who am I", []) is None


def test_second_person():
    assert second_person("I'm Rauf and my cat is called Milo.") == "You're Rauf and your cat is called Milo."
