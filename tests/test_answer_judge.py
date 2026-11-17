import re

import pytest
from karotte.schemas.transcript import Transcript

from environment.answers import MAX_ANSWER_BYTES, Answer, AnswerJudge

INTEGER = re.compile(r"[0-9]+")
TWO_DECIMALS = re.compile(r"[0-9]+\.[0-9]{2}")


def _score(tmp_path, content: str | None, pattern=INTEGER, expected="137", **kwargs):
    path = tmp_path / "answer.txt"
    if content is not None:
        path.write_text(content)
    judge = AnswerJudge(path, pattern, Answer(expected=expected, seed=1), **kwargs)
    return judge.evaluate(Transcript(run_id="test"))


@pytest.mark.parametrize("content", ["137", "137\n", "  137  "])
def test_the_exact_answer_passes(tmp_path, content):
    scoring = _score(tmp_path, content)
    assert scoring.score == 1.0
    assert scoring.continue_task


@pytest.mark.parametrize(
    "content",
    [
        "136",  # Wrong value.
        "137 138",  # A list of guesses.
        "136\n137",
        "answer: 137",  # Extra text.
        "137 patients",
        "137.0",
        "",
        "-137",
    ],
)
def test_anything_else_fails(tmp_path, content):
    scoring = _score(tmp_path, content)
    assert scoring.score == 0.0
    assert not scoring.continue_task


def test_a_missing_answer_file_fails(tmp_path):
    scoring = _score(tmp_path, None)
    assert scoring.score == 0.0
    assert scoring.metadata["reason"] == "no answer file"


def test_a_long_answer_fails_without_being_read_whole(tmp_path):
    scoring = _score(tmp_path, "137 " * MAX_ANSWER_BYTES)
    assert scoring.score == 0.0
    assert scoring.metadata["reason"] == "answer too long"


def test_same_decides_equality(tmp_path):
    same_int = {"same": lambda a, b: int(a) == int(b)}
    assert _score(tmp_path, "0137", **same_int).score == 1.0
    assert _score(tmp_path, "0137").score == 0.0


@pytest.mark.parametrize(
    ("content", "score"),
    [("3.47", 1.0), ("3.470", 0.0), ("3.5", 0.0), ("3.47 3.48", 0.0), ("3.46", 0.0)],
)
def test_two_decimal_answers(tmp_path, content, score):
    assert _score(tmp_path, content, TWO_DECIMALS, "3.47").score == score
