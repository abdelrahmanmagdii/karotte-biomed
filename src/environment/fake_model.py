"""Scripted students for testing the tasks without a real model.

Pick a scenario with `extra_config["fake_scenario"]`:

- `solve` (default): runs the task's reference solution on the files the
  student sees. Must score 1.
- `guess`: writes a list of candidate answers. Must score 0.
- `peek`: tries to read the answer from root-only storage. Must score 0.

Fake runs need a pinned `extra_config["seed"]`: the script is fixed before
`pre_hook` picks the drug-event pair, so `solve` rederives the pair from the
seed. It reads nothing else the student couldn't.
"""

import json
from pathlib import Path

from karotte import EvaluationRunConfig
from karotte.protected_store import PROTECTED_STORE_DIR
from karotte.schemas import ChatCompletionMessageToolCall, Function, Message

from environment.tasks import adverse_event_signal, cohort_query
from environment.tasks.adverse_event_signal import data as ae_data

PYTHON = "/workdir/.venv/bin/python"


def get_messages(config: EvaluationRunConfig) -> list[Message]:
    extra = config.extra_config or {}
    scenario = extra.get("fake_scenario", "solve")
    seed = extra.get("seed")
    if not isinstance(seed, int):
        raise ValueError('Fake runs need an integer extra_config["seed"].')

    match config.task_id, scenario:
        case cohort_query.CohortQuery.id, "solve":
            command = _run_reference(
                cohort_query, f"{cohort_query.DB_PATH}", cohort_query.ANSWER_PATH
            )
        case adverse_event_signal.AdverseEventSignal.id, "solve":
            ds = ae_data.generate(seed, extra.get("cases", ae_data.DEFAULT_CASES))
            args = f"{adverse_event_signal.DATA_DIR} {ds.drug} '{ds.event}'"
            command = _run_reference(
                adverse_event_signal, args, adverse_event_signal.ANSWER_PATH
            )
        case task_id, "guess":
            answer = _answer_path(task_id)
            if task_id == cohort_query.CohortQuery.id:
                command = f"seq 100 300 | tr '\\n' ' ' > {answer}"
            else:
                command = f"seq 1 0.01 20 | tr '\\n' ' ' > {answer}"
        case task_id, "peek":
            secret = PROTECTED_STORE_DIR / f"{task_id}-answer"
            read = f"import json; print(json.load(open('{secret}'))['expected'])"
            command = (
                f"ls -la /root_data {PROTECTED_STORE_DIR}; "
                f'{PYTHON} -c "{read}" > {_answer_path(task_id)}'
            )
        case _:
            raise ValueError(f"No fake script for {config.task_id!r} / {scenario!r}.")

    return [_bash(command), Message(role="assistant", content="Done.")]


def _run_reference(task_module, args: str, answer: Path) -> str:
    source = (Path(task_module.__file__).parent / "reference_solution.py").read_text()
    return (
        f"cat > /tmp/solve.py <<'EOF'\n{source}\nEOF\n"
        f"{PYTHON} /tmp/solve.py {args} > {answer} && cat {answer}"
    )


def _answer_path(task_id: str) -> Path:
    if task_id == cohort_query.CohortQuery.id:
        return cohort_query.ANSWER_PATH
    return adverse_event_signal.ANSWER_PATH


def _bash(command: str) -> Message:
    # A step keeps running until a message has no tool call, so the script
    # ends with a plain message.
    return Message(
        role="assistant",
        content="Working on it.",
        tool_calls=[
            ChatCompletionMessageToolCall(
                id="tool_call_1",
                type="function",
                function=Function(
                    name="bash", arguments=json.dumps({"command": command})
                ),
            )
        ],
    )
