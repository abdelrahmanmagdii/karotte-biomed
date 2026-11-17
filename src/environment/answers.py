"""What the biomedical tasks share: a per-run seed, read-only task data, and a
judge that accepts one exactly formatted answer."""

import re
import secrets
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import override

from karotte import EvaluationRunConfig, ProtectedStore
from karotte.judges import Judge
from karotte.schemas.scoring import Scoring
from karotte.schemas.transcript import Transcript
from pydantic import BaseModel

# An answer is one short number; anything longer is not an answer.
MAX_ANSWER_BYTES = 64


class Answer(BaseModel):
    """What the grader needs, kept where the student can't read it."""

    expected: str
    seed: int


def run_seed(config: EvaluationRunConfig) -> int:
    """A fresh seed for every run, so the answer can't be memorized or found
    in the image. `extra_config["seed"]` pins it to reproduce a run."""
    seed = (config.extra_config or {}).get("seed")
    return seed if isinstance(seed, int) else secrets.randbits(63)


def provision_read_only(dest: Path, files: Mapping[str, bytes]) -> None:
    """Write `files` into a fresh root-owned `dest` the student can read but
    not change."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for name, data in files.items():
        path = dest / name
        path.write_bytes(data)
        path.chmod(0o444)
    dest.chmod(0o555)


def store_answer(task_id: str, answer: Answer) -> None:
    ProtectedStore().write(_store_name(task_id), answer)


def read_answer(task_id: str) -> Answer:
    return ProtectedStore().read(_store_name(task_id), Answer)


def _store_name(task_id: str) -> str:
    return f"{task_id}-answer"


class AnswerJudge(Judge):
    """Scores 1 when the saved submission is exactly one answer in `pattern`'s
    format and `same` says it equals `expected`. A list of guesses, extra
    text or a second number fails the format check and scores 0."""

    def __init__(
        self,
        submission: Path,
        pattern: re.Pattern[str],
        answer: Answer,
        same: Callable[[str, str], bool] = str.__eq__,
    ) -> None:
        self.submission = submission
        self.pattern = pattern
        self.answer = answer
        self.same = same

    @override
    def evaluate(self, transcript: Transcript) -> Scoring:
        metadata = {"expected": self.answer.expected, "seed": str(self.answer.seed)}
        if not self.submission.is_file():
            return _fail(metadata, "no answer file")
        with open(self.submission, "rb") as f:
            raw = f.read(MAX_ANSWER_BYTES + 1)
        if len(raw) > MAX_ANSWER_BYTES:
            return _fail(metadata, "answer too long")
        submitted = raw.decode("utf-8", errors="replace").strip()
        metadata["submitted"] = submitted
        if not self.pattern.fullmatch(submitted):
            return _fail(metadata, "answer not in the required format")
        passed = self.same(submitted, self.answer.expected)
        return Scoring(
            score=float(passed),
            metadata={**metadata, "reason": "correct" if passed else "wrong value"},
            continue_task=passed,
        )


def _fail(metadata: dict[str, str], reason: str) -> Scoring:
    return Scoring(
        score=0.0, metadata={**metadata, "reason": reason}, continue_task=False
    )
