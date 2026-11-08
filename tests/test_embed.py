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


@pytest.mark.parametrize(
    "literal", ["NaN", "Infinity", "-Infinity", "1e39", "-1e39", "1" + "0" * 400]
)
def test_embed_rejects_non_finite_or_out_of_range(client, literal):
    rest = ", ".join(["0.1"] * (DIMENSIONS - 1))
    raw = f'{{"embedding": [{literal}, {rest}]}}'.encode()
    with Stubber(client) as stub:
        stub.add_response("invoke_model", resp_of(raw))
        with pytest.raises(EmbedError):
            embed_text(client, model_id=EMBED_MODEL_ID, text="x")


def _embed_records(caplog):
    return [r for r in caplog.records if r.name == "slackkb.embed"]


def test_embed_usage_logged(client, caplog):
    caplog.set_level("INFO", logger="slackkb.embed")
    payload = {"embedding": [0.5] * DIMENSIONS, "inputTextTokenCount": 7}
    with Stubber(client) as stub:
        stub.add_response("invoke_model", resp_of(payload))
        embed_text(client, model_id=EMBED_MODEL_ID, text="x")
    records = _embed_records(caplog)
    assert len(records) == 1
    assert records[0].levelname == "INFO"
    assert records[0].getMessage() == (
        f"bedrock usage, call=embed model_id={EMBED_MODEL_ID} input_tokens=7"
    )


def test_embed_usage_logged_on_bad_embedding(client, caplog):
    caplog.set_level("INFO", logger="slackkb.embed")
    payload = {"embedding": [0.5] * (DIMENSIONS - 1), "inputTextTokenCount": 7}
    with Stubber(client) as stub:
        stub.add_response("invoke_model", resp_of(payload))
        with pytest.raises(EmbedError):
            embed_text(client, model_id=EMBED_MODEL_ID, text="x")
    records = _embed_records(caplog)
    assert [r.getMessage() for r in records] == [
        f"bedrock usage, call=embed model_id={EMBED_MODEL_ID} input_tokens=7"
    ]


def test_embed_error_and_bad_json_log_no_usage(client, caplog):
    caplog.set_level("INFO", logger="slackkb.embed")
    with Stubber(client) as stub:
        stub.add_client_error("invoke_model", service_error_code="ThrottlingException")
        with pytest.raises(EmbedError):
            embed_text(client, model_id=EMBED_MODEL_ID, text="x")
    with Stubber(client) as stub:
        stub.add_response("invoke_model", resp_of(b"not json"))
        with pytest.raises(EmbedError):
            embed_text(client, model_id=EMBED_MODEL_ID, text="x")
    assert not [r for r in caplog.records if "bedrock usage" in r.getMessage()]


def test_embed_usage_missing_warns(client, caplog):
    caplog.set_level("INFO", logger="slackkb.embed")
    vec = [0.5] * DIMENSIONS
    payloads = [
        {"embedding": vec},
        {"embedding": vec, "inputTextTokenCount": "7"},
        {"embedding": vec, "inputTextTokenCount": True},
        {"embedding": vec, "inputTextTokenCount": -1},
    ]
    for payload in payloads:
        caplog.clear()
        with Stubber(client) as stub:
            stub.add_response("invoke_model", resp_of(payload))
            out = embed_text(client, model_id=EMBED_MODEL_ID, text="x")
        assert out == vec
        records = _embed_records(caplog)
        assert len(records) == 1
        assert records[0].levelname == "WARNING"
        assert records[0].getMessage() == (
            f"bedrock usage missing, call=embed model_id={EMBED_MODEL_ID}"
        )


def test_embed_usage_line_has_no_text_or_vector(client, caplog):
    caplog.set_level("DEBUG", logger="slackkb.embed")
    payload = {"embedding": [0.123] * DIMENSIONS, "inputTextTokenCount": 3}
    with Stubber(client) as stub:
        stub.add_response("invoke_model", resp_of(payload))
        embed_text(client, model_id=EMBED_MODEL_ID, text="TEXT-SECRET")
    records = _embed_records(caplog)
    assert records
    for r in records:
        text = r.getMessage()
        assert "TEXT-SECRET" not in text and "0.123" not in text
        assert "$" not in text
        assert "usd" not in text.lower() and "cost" not in text.lower()
