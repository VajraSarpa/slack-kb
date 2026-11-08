import io
import json

import boto3
import pytest
from botocore.exceptions import EndpointConnectionError
from botocore.response import StreamingBody
from botocore.stub import Stubber
from conftest import EMBED_MODEL_ID

from slackkb.embed import DIMENSIONS, EmbedError, embed_text


def body_of(payload):
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return StreamingBody(io.BytesIO(raw), len(raw))


def resp_of(payload):
    return {"contentType": "application/json", "body": body_of(payload)}


@pytest.fixture
def client():
    return boto3.client("bedrock-runtime", region_name="us-east-1")


def test_dimensions_is_512():
    assert DIMENSIONS == 512


def test_embed_sends_titan_request(client):
    vec = [0.5] * DIMENSIONS
    expected = {
        "modelId": EMBED_MODEL_ID,
        "contentType": "application/json",
        "accept": "application/json",
        "body": json.dumps({"inputText": "hello", "dimensions": 512, "normalize": True}),
    }
    with Stubber(client) as stub:
        stub.add_response("invoke_model", resp_of({"embedding": vec}), expected)
        embed_text(client, model_id=EMBED_MODEL_ID, text="hello")
        stub.assert_no_pending_responses()


def test_embed_returns_vector(client):
    vec = list(range(DIMENSIONS))
    with Stubber(client) as stub:
        stub.add_response("invoke_model", resp_of({"embedding": vec}))
        out = embed_text(client, model_id=EMBED_MODEL_ID, text="x")
    assert out == [float(x) for x in vec]
    assert all(isinstance(x, float) for x in out)


def test_embed_wrong_length_raises(client):
    for n in (DIMENSIONS - 1, DIMENSIONS + 1, 0):
        with Stubber(client) as stub:
            stub.add_response("invoke_model", resp_of({"embedding": [0.1] * n}))
            with pytest.raises(EmbedError):
                embed_text(client, model_id=EMBED_MODEL_ID, text="x")


@pytest.mark.parametrize(
    "payload",
    [b"not json", json.dumps({"other": []}).encode(), b"[1, 2]", json.dumps(
        {"embedding": ["a"] * DIMENSIONS}
    ).encode()],
)
def test_embed_bad_body_raises(client, payload):
    with Stubber(client) as stub:
        stub.add_response("invoke_model", resp_of(payload))
        with pytest.raises(EmbedError):
            embed_text(client, model_id=EMBED_MODEL_ID, text="x")


def test_embed_wraps_client_errors(client):
    with Stubber(client) as stub:
        stub.add_client_error("invoke_model", service_error_code="ThrottlingException")
        with pytest.raises(EmbedError) as info:
            embed_text(client, model_id=EMBED_MODEL_ID, text="x")
    assert info.value.__cause__ is not None


def test_embed_wraps_botocore_errors():
    class Broken:
        def invoke_model(self, **kwargs):
            raise EndpointConnectionError(endpoint_url="https://bedrock.invalid")

    with pytest.raises(EmbedError) as info:
        embed_text(Broken(), model_id=EMBED_MODEL_ID, text="x")
    assert isinstance(info.value.__cause__, EndpointConnectionError)
