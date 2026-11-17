import pytest
from karotte import EvaluationRunConfig
from karotte.schemas import HttpMcpServerConfig, Message


def _config(task_id: str, extra_config: dict) -> EvaluationRunConfig:
    return EvaluationRunConfig(
        run_id="test",
        task_id=task_id,
        model="test-model",
        model_api_key="test-key",
        mcp_server_config=HttpMcpServerConfig(host="0.0.0.0", port=8080),
        transcript_file="transcript.json",
        extra_config=extra_config,
    )


@pytest.mark.parametrize("task_id", ["cohort-query", "adverse-event-signal"])
@pytest.mark.parametrize("scenario", ["solve", "guess", "peek"])
def test_every_task_has_every_fake_scenario(task_id, scenario):
    from environment.fake_model import get_messages

    messages = get_messages(_config(task_id, {"seed": 1, "fake_scenario": scenario}))

    assert all(isinstance(m, Message) for m in messages)
    assert messages[0].tool_calls
    assert not messages[-1].tool_calls, (
        "a step only ends on a message without a tool call"
    )


def test_fake_runs_need_a_seed():
    from environment.fake_model import get_messages

    with pytest.raises(ValueError, match="seed"):
        get_messages(_config("cohort-query", {}))
