import ast
import base64
import hashlib
import json
import logging
import time
import urllib.parse
from pathlib import Path

import boto3
import pytest
from conftest import BOT_TOKEN, SIGNING_SECRET, sign

from slackkb import capture
from slackkb.capture import handle
from slackkb.config import Settings
from slackkb.store import StoreError, get_note

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


def test_capture_job_carries_response_url(slack_request, notes_table, capture_queue, caplog):
    with caplog.at_level(logging.DEBUG, logger="slackkb"):
        _handle(slack_request(), notes_table)
    messages = boto3.client("sqs").receive_message(QueueUrl=capture_queue.url)["Messages"]
    assert json.loads(messages[0]["Body"]) == {
        "note_id": EXPECTED_NOTE_ID,
        "response_url": "https://hooks.slack.invalid/commands/T000TEST/1/abc",
    }
    # Requirement 7: the job carries the URL; no capture log line does.
    assert "note captured" in caplog.text
    assert "https://hooks.slack.invalid/commands/T000TEST/1/abc" not in caplog.text
    assert "response_url" not in caplog.text


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


NOTE_TEXT = "db connection timeouts on /api/orders since 14:05"
RESPONSE_URL = "https://hooks.slack.invalid/commands/T000TEST/1/abc"
SHORT_TEXT = "short note"


def _records(caplog, level):
    return [r for r in caplog.records if r.name == "slackkb.capture" and r.levelno == level]


def _only_message(caplog, level):
    """The module's single log record, which must be at `level`."""
    records = [r for r in caplog.records if r.name == "slackkb.capture"]
    assert [r.levelno for r in records] == [level]
    return records[0].getMessage()


def _signed_body(fields):
    body = urllib.parse.urlencode(fields)
    ts = int(time.time())
    return {
        "headers": {"X-Slack-Request-Timestamp": str(ts), "X-Slack-Signature": sign(body, ts)},
        "body": body,
        "isBase64Encoded": False,
    }


def _run(event, table, caplog, sqs=None):
    sqs = boto3.client("sqs") if sqs is None else sqs
    # Only our loggers at DEBUG; botocore's DEBUG output echoes request params.
    with caplog.at_level(logging.DEBUG, logger="slackkb"):
        return handle(event, table=table, sqs=sqs, settings=Settings(), now=int(time.time()))


def _bad_base64(slack_request):
    event = slack_request()
    event["body"] = "!!not base64!!"
    event["isBase64Encoded"] = True
    return event


def _bad_utf8(slack_request):
    event = slack_request()
    event["body"] = base64.b64encode(b"\xff\xfe").decode()
    event["isBase64Encoded"] = True
    return event


@pytest.mark.parametrize(
    ("make", "reason"),
    [
        (lambda r: r(secret="wrong"), "signature mismatch"),
        (lambda r: r(drop=("X-Slack-Signature",)), "missing signature header"),
        (lambda r: r(drop=("X-Slack-Request-Timestamp",)), "missing timestamp header"),
        (lambda r: r(ts=1), "timestamp outside allowed window"),
        (_bad_base64, "bad body encoding"),
        (_bad_utf8, "bad body encoding"),
    ],
)
def test_logs_401_reason(slack_request, notes_table, capture_queue, caplog, make, reason):
    resp = _run(make(slack_request), notes_table, caplog)
    assert resp["statusCode"] == 401
    msg = _only_message(caplog, logging.WARNING)
    assert "capture rejected" in msg and reason in msg


@pytest.mark.parametrize(
    ("drop", "names"),
    [(("team_id",), {"team_id"}), (("trigger_id", "user_id"), {"trigger_id", "user_id"})],
)
def test_logs_400_field_names_only(notes_table, capture_queue, caplog, drop, names):
    fields = json.loads((Path(__file__).parent / "fixtures" / "slash_bnote.json").read_text())
    for name in drop:
        del fields[name]
    resp = _run(_signed_body(fields), notes_table, caplog)
    assert resp["statusCode"] == 400
    msg = _only_message(caplog, logging.WARNING)
    assert all(name in msg for name in names)
    for value in (NOTE_TEXT, "C000TEST", "U000TEST", TEAM_ID, TRIGGER_ID):
        assert value not in msg


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("empty_text", ("usage", TEAM_ID, "U000TEST")),
        ("captured", ("note captured", EXPECTED_NOTE_ID)),
        ("duplicate", ("duplicate capture", EXPECTED_NOTE_ID)),
    ],
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_logs_accepted_paths(slack_request, notes_table, capture_queue, caplog, path, expected):
    if path == "duplicate":
        _run(slack_request(), notes_table, caplog)
        caplog.clear()
    event = slack_request(text="  ") if path == "empty_text" else slack_request()
    assert _run(event, notes_table, caplog)["statusCode"] == 200
    msg = _only_message(caplog, logging.INFO)
    assert all(value in msg for value in expected)


def test_logs_note_not_deleted_after_failed_enqueue(
    slack_request, notes_table, capture_queue, caplog, monkeypatch
):
    monkeypatch.setattr(capture, "delete_if_captured", lambda table, note_id: False)
    sqs = boto3.client("sqs")
    sqs.delete_queue(QueueUrl=capture_queue.url)
    resp = _run(slack_request(), notes_table, caplog, sqs=sqs)
    assert json.loads(resp["body"])["text"] == capture.RETRY_TEXT
    msgs = [r.getMessage() for r in _records(caplog, logging.WARNING)]
    matching = [m for m in msgs if "note not deleted, not captured or gone" in m]
    assert len(matching) == 1 and EXPECTED_NOTE_ID in matching[0]


def _with_trigger(slack_request, trigger_id):
    event = slack_request()
    event["body"] = event["body"].replace(TRIGGER_ID, trigger_id)
    event["headers"]["X-Slack-Signature"] = sign(
        event["body"], int(event["headers"]["X-Slack-Request-Timestamp"])
    )
    return event


def test_logs_never_contain_secrets(slack_request, notes_table, capture_queue, caplog, monkeypatch):
    events = [
        slack_request(),
        slack_request(retry=1),
        slack_request(text=" "),
        slack_request(secret="wrong"),
        _bad_base64(slack_request),
        # Short, because pydantic truncates long input values in its error messages.
        _signed_body({"text": SHORT_TEXT}),
    ]
    for event in events:
        _run(event, notes_table, caplog)
    sqs = boto3.client("sqs")
    sqs.delete_queue(QueueUrl=capture_queue.url)

    def boom(table, note_id):
        raise StoreError("ClientError")

    failed_enqueues = [
        (None, _with_trigger(slack_request, "9999.0001.a")),
        (lambda table, note_id: False, _with_trigger(slack_request, "9999.0002.b")),
        (boom, _with_trigger(slack_request, "9999.0003.c")),
    ]
    for delete, event in failed_enqueues:
        if delete is not None:
            monkeypatch.setattr(capture, "delete_if_captured", delete)
        _run(event, notes_table, caplog, sqs=sqs)
        events.append(event)
    assert caplog.text
    for value in (NOTE_TEXT, SHORT_TEXT, SIGNING_SECRET, BOT_TOKEN, RESPONSE_URL, "response_url"):
        assert value not in caplog.text
    for event in events:
        assert event["body"] not in caplog.text
        assert event["headers"]["X-Slack-Signature"] not in caplog.text


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
    assert "post_response_url" not in source and "urlopen" not in source
