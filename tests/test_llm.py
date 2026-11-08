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
    }
    with Stubber(client) as stub:
        stub.add_response("converse", tool_response({"answer": "a"}), expected)
        llm.ask(client, model_id="model-x", system="SYS", user="USER", tool=TOOL)
        stub.assert_no_pending_responses()


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
