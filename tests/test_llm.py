import boto3
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from botocore.stub import Stubber

from slackkb import llm

TOOL = {
    "toolSpec": {
        "name": "answer",
        "description": "Return the answer.",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            }
        },
    }
}


@pytest.fixture
def client():
    return boto3.client("bedrock-runtime", region_name="us-east-1")


def tool_response(payload):
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"toolUse": {"toolUseId": "t1", "name": "answer", "input": payload}}],
            }
        },
        "stopReason": "tool_use",
        "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
        "metrics": {"latencyMs": 1},
    }


def test_ask_sends_forced_tool_request(client):
    expected = {
        "modelId": "model-x",
        "system": [{"text": "SYS"}],
        "messages": [{"role": "user", "content": [{"text": "USER"}]}],
        "toolConfig": {"tools": [TOOL], "toolChoice": {"tool": {"name": "answer"}}},
        "inferenceConfig": {"maxTokens": 1024},
    }
    with Stubber(client) as stub:
        stub.add_response("converse", tool_response({"answer": "a"}), expected)
        llm.ask(client, model_id="model-x", system="SYS", user="USER", tool=TOOL)
        stub.assert_no_pending_responses()


def test_ask_caps_output_tokens(client):
    assert llm.MAX_TOKENS == 1024
    expected = {
        "modelId": "m",
        "system": [{"text": "s"}],
        "messages": [{"role": "user", "content": [{"text": "u"}]}],
        "toolConfig": {"tools": [TOOL], "toolChoice": {"tool": {"name": "answer"}}},
        "inferenceConfig": {"maxTokens": 1024},
    }
    with Stubber(client) as stub:
        stub.add_response("converse", tool_response({"answer": "a"}), expected)
        llm.ask(client, model_id="m", system="s", user="u", tool=TOOL)
        stub.assert_no_pending_responses()


def test_max_tokens_stop_is_an_error(client, caplog):
    caplog.set_level("INFO", logger="slackkb.llm")
    resp = tool_response({"answer": "cut off"})
    resp["stopReason"] = "max_tokens"
    with Stubber(client) as stub:
        stub.add_response("converse", resp)
        with pytest.raises(llm.LlmError, match="max_tokens"):
            llm.ask(client, model_id="model-x", system="s", user="u", tool=TOOL)
    records = _usage_records(caplog)
    assert [r.levelname for r in records] == ["INFO", "WARNING"]
    assert records[0].getMessage().startswith("bedrock usage, call=converse")
    assert "max_tokens" in records[1].getMessage()
    assert "model-x" in records[1].getMessage()


def test_ask_returns_tool_input(client):
    with Stubber(client) as stub:
        stub.add_response("converse", tool_response({"answer": "hello"}))
        result = llm.ask(client, model_id="m", system="s", user="u", tool=TOOL)
    assert result == {"answer": "hello"}


def test_ask_returns_first_tool_use_input(client):
    response = tool_response({})
    response["output"]["message"]["content"] = [
        {"text": "thinking"},
        {"toolUse": {"toolUseId": "a", "name": "answer", "input": {"answer": "A"}}},
        {"toolUse": {"toolUseId": "b", "name": "answer", "input": {"answer": "B"}}},
    ]
    with Stubber(client) as stub:
        stub.add_response("converse", response)
        result = llm.ask(client, model_id="m", system="s", user="u", tool=TOOL)
    assert result == {"answer": "A"}


def test_ask_without_tool_use_raises(client):
    response = tool_response({})
    response["output"]["message"]["content"] = [{"text": "just text"}]
    response["stopReason"] = "end_turn"
    with Stubber(client) as stub:
        stub.add_response("converse", response)
        with pytest.raises(llm.LlmError):
            llm.ask(client, model_id="m", system="s", user="u", tool=TOOL)


def test_ask_wraps_client_errors(client):
    with Stubber(client) as stub:
        stub.add_client_error("converse", service_error_code="ThrottlingException")
        with pytest.raises(llm.LlmError) as info:
            llm.ask(client, model_id="m", system="s", user="u", tool=TOOL)
    assert isinstance(info.value.__cause__, ClientError)


class RaisingClient:
    def __init__(self, exc):
        self.exc = exc

    def converse(self, **kwargs):
        raise self.exc


def test_ask_wraps_botocore_errors():
    exc = EndpointConnectionError(endpoint_url="https://bedrock-runtime.us-east-1.amazonaws.com")
    with pytest.raises(llm.LlmError) as info:
        llm.ask(RaisingClient(exc), model_id="m", system="s", user="u", tool=TOOL)
    assert info.value.__cause__ is exc


def _usage_records(caplog):
    return [r for r in caplog.records if r.name == "slackkb.llm"]


def test_converse_usage_logged(client, caplog):
    caplog.set_level("INFO", logger="slackkb.llm")
    resp = tool_response({"answer": "a"})
    resp["usage"] = {"inputTokens": 123, "outputTokens": 45, "totalTokens": 168}
    with Stubber(client) as stub:
        stub.add_response("converse", resp)
        llm.ask(client, model_id="model-x", system="s", user="u", tool=TOOL)
    records = _usage_records(caplog)
    assert len(records) == 1
    assert records[0].levelname == "INFO"
    assert records[0].getMessage() == (
        "bedrock usage, call=converse model_id=model-x input_tokens=123 output_tokens=45"
    )


def test_converse_usage_logged_without_tool_use(client, caplog):
    caplog.set_level("INFO", logger="slackkb.llm")
    resp = tool_response({"answer": "a"})
    resp["output"]["message"]["content"] = [{"text": "no tool"}]
    resp["stopReason"] = "end_turn"
    resp["usage"] = {"inputTokens": 5, "outputTokens": 6, "totalTokens": 11}
    with Stubber(client) as stub:
        stub.add_response("converse", resp)
        with pytest.raises(llm.LlmError):
            llm.ask(client, model_id="m", system="s", user="u", tool=TOOL)
    records = _usage_records(caplog)
    assert [r.getMessage() for r in records] == [
        "bedrock usage, call=converse model_id=m input_tokens=5 output_tokens=6"
    ]


def test_converse_error_logs_no_usage(client, caplog):
    caplog.set_level("INFO", logger="slackkb.llm")
    with Stubber(client) as stub:
        stub.add_client_error("converse", service_error_code="ThrottlingException")
        with pytest.raises(llm.LlmError):
            llm.ask(client, model_id="m", system="s", user="u", tool=TOOL)
    assert not [r for r in caplog.records if "bedrock usage" in r.getMessage()]


class FakeClient:
    def __init__(self, response):
        self.response = response

    def converse(self, **kwargs):
        return self.response


def test_converse_usage_missing_warns(caplog):
    caplog.set_level("INFO", logger="slackkb.llm")
    base = tool_response({"answer": "ok"})
    del base["usage"]
    variants = [
        base,
        {**base, "usage": {"inputTokens": "3", "outputTokens": 1}},
        {**base, "usage": {"inputTokens": True, "outputTokens": 1}},
        {**base, "usage": {"inputTokens": 1, "outputTokens": -1}},
    ]
    for resp in variants:
        caplog.clear()
        result = llm.ask(FakeClient(resp), model_id="m", system="s", user="u", tool=TOOL)
        assert result == {"answer": "ok"}
        records = _usage_records(caplog)
        assert len(records) == 1
        assert records[0].levelname == "WARNING"
        assert records[0].getMessage() == "bedrock usage missing, call=converse model_id=m"


def _assert_usage_warns(caplog, usage):
    caplog.set_level("INFO", logger="slackkb.llm")
    resp = {**tool_response({"answer": "ok"}), "usage": usage}
    result = llm.ask(FakeClient(resp), model_id="m", system="s", user="u", tool=TOOL)
    assert result == {"answer": "ok"}
    records = _usage_records(caplog)
    assert len(records) == 1
    assert records[0].levelname == "WARNING"
    assert records[0].getMessage() == "bedrock usage missing, call=converse model_id=m"


def test_converse_usage_negative_input_warns(caplog):
    _assert_usage_warns(caplog, {"inputTokens": -1, "outputTokens": 1})


def test_converse_usage_output_absent_warns(caplog):
    _assert_usage_warns(caplog, {"inputTokens": 1})


def test_converse_usage_line_has_no_prompt_text(client, caplog):
    caplog.set_level("DEBUG", logger="slackkb.llm")
    with Stubber(client) as stub:
        stub.add_response("converse", tool_response({"answer": "a"}))
        llm.ask(client, model_id="m", system="SYS-SECRET", user="USER-SECRET", tool=TOOL)
    records = _usage_records(caplog)
    assert records
    for r in records:
        text = r.getMessage()
        assert "SYS-SECRET" not in text and "USER-SECRET" not in text
        assert "$" not in text
        assert "usd" not in text.lower() and "cost" not in text.lower()


def test_converse_usage_line_carries_trace(client):
    import io
    import json
    import logging

    from slackkb import obs

    root = logging.getLogger()
    names = ["", "botocore", "boto3", "urllib3"]
    levels = {n: logging.getLogger(n).level for n in names}
    buf = io.StringIO()
    handler = obs.configure(buf)
    try:
        with obs.trace():
            obs.bind("Ev1")
            with Stubber(client) as stub:
                stub.add_response("converse", tool_response({"answer": "a"}))
                llm.ask(client, model_id="m", system="s", user="u", tool=TOOL)
    finally:
        root.removeHandler(handler)
        for n, lvl in levels.items():
            logging.getLogger(n).setLevel(lvl)
    lines = [json.loads(x) for x in buf.getvalue().splitlines()]
    usage = [x for x in lines if x["msg"].startswith("bedrock usage")]
    assert len(usage) == 1
    assert usage[0]["trace_id"] == "Ev1"
