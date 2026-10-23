import ast
import base64
import hashlib
import json
import time
from pathlib import Path

import boto3
import pytest
from conftest import SIGNING_SECRET

from slackkb.capture import handle
from slackkb.config import Settings
from slackkb.store import get_note

CAPTURE_SRC = Path(__file__).parent.parent / "src" / "slackkb" / "capture.py"
TEAM_ID = "T000TEST"
TRIGGER_ID = "1111.2222.abcdef"
EXPECTED_NOTE_ID = hashlib.sha256(f"{TEAM_ID}:{TRIGGER_ID}".encode()).hexdigest()[:32]


def _handle(event, table, now=None):
    now = int(time.time()) if now is None else now
    sqs = boto3.client("sqs")
    return handle(event, table=table, sqs=sqs, settings=Settings(), now=now)


def _items(table):
    return table.scan()["Items"]


def _assert_rejected(resp, table):
    assert resp["statusCode"] == 401
    assert SIGNING_SECRET not in resp["body"]
    assert _items(table) == []


def test_valid_request_writes_note(slack_request, notes_table, capture_queue):
    resp = _handle(slack_request(), notes_table)
    assert resp["statusCode"] == 200
    note = get_note(notes_table, EXPECTED_NOTE_ID)
    assert note is not None
    assert note.team_id == TEAM_ID
    assert note.channel_id == "C000TEST"
    assert note.user_id == "U000TEST"
    assert note.text == "db connection timeouts on /api/orders since 14:05"
    assert note.severity.value == "LOW"
    assert note.status.value == "CAPTURED"


def test_text_saved_as_typed(slack_request, notes_table, capture_queue):
    _handle(slack_request(text="  padded note  "), notes_table)
    assert get_note(notes_table, EXPECTED_NOTE_ID).text == "  padded note  "


def test_bad_signature_returns_401_and_writes_nothing(slack_request, notes_table, capture_queue):
    _assert_rejected(_handle(slack_request(secret="wrong-secret"), notes_table), notes_table)


def test_bad_signature_rejected_before_parsing(slack_request, notes_table, capture_queue):
    event = slack_request()
    event["body"] = "not=a&valid=form"
    _assert_rejected(_handle(event, notes_table), notes_table)


@pytest.mark.parametrize(
    "drop",
    [
        ("X-Slack-Signature",),
        ("X-Slack-Request-Timestamp",),
        ("X-Slack-Signature", "X-Slack-Request-Timestamp"),
    ],
)
def test_missing_headers_rejected(slack_request, notes_table, capture_queue, drop):
    _assert_rejected(_handle(slack_request(drop=drop), notes_table), notes_table)


def test_missing_headers_map_rejected(slack_request, notes_table, capture_queue):
    event = slack_request()
    event["headers"] = None
    _assert_rejected(_handle(event, notes_table), notes_table)


def test_stale_timestamp_rejected(slack_request, notes_table, capture_queue):
    now = int(time.time())
    event = slack_request(ts=now - 301)
    _assert_rejected(_handle(event, notes_table, now=now), notes_table)


def test_lowercase_headers_accepted(slack_request, notes_table, capture_queue):
    resp = _handle(slack_request(lowercase_headers=True), notes_table)
    assert resp["statusCode"] == 200
    assert get_note(notes_table, EXPECTED_NOTE_ID) is not None


def test_base64_body_accepted(slack_request, notes_table, capture_queue):
    event = slack_request()
    event["body"] = base64.b64encode(event["body"].encode()).decode()
    event["isBase64Encoded"] = True
    resp = _handle(event, notes_table)
    assert resp["statusCode"] == 200
    assert get_note(notes_table, EXPECTED_NOTE_ID) is not None


def test_retry_does_not_duplicate(slack_request, notes_table, capture_queue):
    first = _handle(slack_request(), notes_table)
    # Same trigger_id, different text: the conditional put must keep the first note.
    second = _handle(slack_request(retry=1, text="replayed text"), notes_table)
    assert first["statusCode"] == second["statusCode"] == 200
    assert first["body"] == second["body"]
    assert get_note(notes_table, EXPECTED_NOTE_ID).text.startswith("db connection")
    assert len(_items(notes_table)) == 1


def test_note_id_is_sha256_of_team_and_trigger(slack_request, notes_table, capture_queue):
    _handle(slack_request(), notes_table)
    items = _items(notes_table)
    assert len(items) == 1
    assert items[0]["note_id"] == EXPECTED_NOTE_ID
    assert len(EXPECTED_NOTE_ID) == 32


@pytest.mark.parametrize("text", ["", "   ", "\t\n"])
def test_empty_text_returns_usage_hint(slack_request, notes_table, capture_queue, text):
    resp = _handle(slack_request(text=text), notes_table)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["response_type"] == "ephemeral"
    assert "/bnote" in body["text"]
    assert _items(notes_table) == []


def test_ack_is_ephemeral_200(slack_request, notes_table, capture_queue):
    resp = _handle(slack_request(), notes_table)
    assert resp["statusCode"] == 200
    assert resp["headers"]["Content-Type"] == "application/json"
    body = json.loads(resp["body"])
    assert body["response_type"] == "ephemeral"
    assert isinstance(body["text"], str) and body["text"]


def _imported_modules(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def test_capture_imports_no_boto3_or_http_client():
    source = CAPTURE_SRC.read_text()
    modules = set(_imported_modules(ast.parse(source)))
    banned = (
        "boto3",
        "botocore",
        "aiobotocore",
        "requests",
        "httpx",
        "urllib3",
        "aiohttp",
        "http",
        "urllib.request",
        "socket",
        "slack_sdk",
        "slack_bolt",
    )
    for module in modules:
        for name in banned:
            assert module != name and not module.startswith(name + "."), module
    assert "slackkb.store" in modules
    # Requirement 8: the ack is the return value; response_url is never used.
    assert "response_url" not in source
