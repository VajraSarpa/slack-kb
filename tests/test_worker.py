import ast
import hashlib
import json
import logging
import time
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import EndpointConnectionError
from conftest import SIGNING_SECRET

from slackkb import capture, worker
from slackkb.config import Settings
from slackkb.models import CaptureJob, Note, NoteStatus
from slackkb.store import get_note, put_if_absent

SRC = Path(__file__).parent.parent / "src" / "slackkb"
TEAM_ID = "T000TEST"
TRIGGER_ID = "1111.2222.abcdef"
EXPECTED_NOTE_ID = hashlib.sha256(f"{TEAM_ID}:{TRIGGER_ID}".encode()).hexdigest()[:32]
NOTE_TEXT = "db connection timeouts on /api/orders since 14:05"
RESPONSE_URL = "https://hooks.slack.invalid/commands/T000TEST/1/abc"


def _capture(event, table, sqs=None):
    sqs = boto3.client("sqs") if sqs is None else sqs
    return capture.handle(event, table=table, sqs=sqs, settings=Settings(), now=int(time.time()))


def _queued(url):
    resp = boto3.client("sqs").receive_message(QueueUrl=url, MaxNumberOfMessages=10)
    return resp.get("Messages", [])


def _put(table, note_id, status=NoteStatus.CAPTURED):
    note = Note(
        note_id=note_id, team_id=TEAM_ID, channel_id="C1", user_id="U1", text="t", status=status
    )
    assert put_if_absent(table, note)


def _record(message_id, body):
    return {"messageId": message_id, "receiptHandle": "rh", "body": body}


def _job(note_id):
    return CaptureJob(note_id=note_id).model_dump_json()


def _failures(resp):
    return sorted(f["itemIdentifier"] for f in resp["batchItemFailures"])


def test_ack_before_processing(slack_request, notes_table, capture_queue):
    resp = _capture(slack_request(), notes_table)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["response_type"] == "ephemeral"
    assert body["text"] == capture.ACK_TEXT
    # No worker has run: the note is still CAPTURED and its job is waiting on the queue.
    assert get_note(notes_table, EXPECTED_NOTE_ID).status is NoteStatus.CAPTURED
    messages = _queued(capture_queue.url)
    assert len(messages) == 1
    assert CaptureJob.model_validate_json(messages[0]["Body"]).note_id == EXPECTED_NOTE_ID


def test_duplicate_capture_enqueues_once(slack_request, notes_table, capture_queue):
    first = _capture(slack_request(), notes_table)
    second = _capture(slack_request(retry=1), notes_table)
    assert first == second
    assert len(_queued(capture_queue.url)) == 1


class _FailingSqs:
    def __init__(self, exc):
        self.exc = exc

    def send_message(self, **kwargs):
        raise self.exc


def _deleted_queue_sqs(url):
    sqs = boto3.client("sqs")
    sqs.delete_queue(QueueUrl=url)
    return sqs


@pytest.mark.parametrize("kind", ["client_error", "botocore_error"])
def test_enqueue_failure_returns_retry_message(
    slack_request, notes_table, capture_queue, caplog, kind
):
    if kind == "client_error":
        sqs = _deleted_queue_sqs(capture_queue.url)
    else:
        sqs = _FailingSqs(EndpointConnectionError(endpoint_url="https://sqs.invalid"))
    with caplog.at_level(logging.DEBUG, logger="slackkb"):
        resp = _capture(slack_request(), notes_table, sqs=sqs)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["response_type"] == "ephemeral"
    assert body == {"response_type": "ephemeral", "text": capture.RETRY_TEXT}
    assert "try again" in body["text"]
    assert get_note(notes_table, EXPECTED_NOTE_ID).status is NoteStatus.CAPTURED
    # Only our own log lines; botocore's DEBUG output echoes request params.
    ours = [r for r in caplog.records if r.name.startswith("slackkb")]
    assert any(r.levelno == logging.WARNING and EXPECTED_NOTE_ID in r.getMessage() for r in ours)
    for secret in (NOTE_TEXT, SIGNING_SECRET, RESPONSE_URL):
        assert all(secret not in r.getMessage() for r in ours)


def test_worker_marks_routed(notes_table):
    _put(notes_table, "a" * 32)
    resp = worker.handle({"Records": [_record("m1", _job("a" * 32))]}, table=notes_table)
    assert resp == {"batchItemFailures": []}
    assert get_note(notes_table, "a" * 32).status is NoteStatus.ROUTED


def test_worker_reports_partial_failure(notes_table):
    _put(notes_table, "a" * 32)
    event = {
        "Records": [
            _record("ok", _job("a" * 32)),
            _record("not-json", "{not json"),
            _record("wrong-shape", json.dumps({"id": "a" * 32})),
            _record("missing-note", _job("b" * 32)),
        ]
    }
    resp = worker.handle(event, table=notes_table)
    assert _failures(resp) == ["missing-note", "not-json", "wrong-shape"]
    assert get_note(notes_table, "a" * 32).status is NoteStatus.ROUTED
    assert get_note(notes_table, "b" * 32) is None


class _BrokenTable:
    def update_item(self, **kwargs):
        raise EndpointConnectionError(endpoint_url="https://dynamodb.invalid")

    def get_item(self, **kwargs):
        raise EndpointConnectionError(endpoint_url="https://dynamodb.invalid")


@pytest.mark.parametrize("kind", ["client_error", "botocore_error"])
def test_worker_reports_store_error(aws, kind):
    if kind == "client_error":
        table = boto3.resource("dynamodb").Table("no-such-table")
    else:
        table = _BrokenTable()
    resp = worker.handle({"Records": [_record("m1", _job("a" * 32))]}, table=table)
    assert _failures(resp) == ["m1"]


def test_worker_is_idempotent(notes_table):
    _put(notes_table, "a" * 32)
    event = {"Records": [_record("m1", _job("a" * 32))]}
    assert worker.handle(event, table=notes_table) == {"batchItemFailures": []}
    assert worker.handle(event, table=notes_table) == {"batchItemFailures": []}
    items = notes_table.scan()["Items"]
    assert len(items) == 1
    assert items[0]["status"] == "ROUTED"


def test_worker_leaves_failed_note_alone(notes_table):
    _put(notes_table, "a" * 32, status=NoteStatus.FAILED)
    resp = worker.handle({"Records": [_record("m1", _job("a" * 32))]}, table=notes_table)
    assert resp == {"batchItemFailures": []}
    assert get_note(notes_table, "a" * 32).status is NoteStatus.FAILED


def _imported_modules(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


BANNED = (
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


@pytest.mark.parametrize(
    ("name", "boundaries"),
    [("capture.py", {"slackkb.store", "slackkb.queue"}), ("worker.py", {"slackkb.store"})],
)
def test_handlers_import_no_boto3(name, boundaries):
    source = (SRC / name).read_text()
    modules = set(_imported_modules(ast.parse(source)))
    for module in modules - {"botocore.exceptions"}:
        for banned in BANNED:
            assert module != banned and not module.startswith(banned + "."), module
    assert boundaries <= modules
    assert "response_url" not in source
