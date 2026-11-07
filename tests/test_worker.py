import ast
import hashlib
import json
import logging
import time
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from conftest import BOT_TOKEN, SIGNING_SECRET, sign

from slackkb import blob, capture, worker
from slackkb.config import Settings
from slackkb.models import CaptureJob, Note, NoteStatus
from slackkb.store import NoteNotFoundError, StoreError, get_note, put_if_absent

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
    assert get_note(notes_table, EXPECTED_NOTE_ID) is None
    # Only our own log lines; botocore's DEBUG output echoes request params.
    ours = [r for r in caplog.records if r.name.startswith("slackkb")]
    assert any(r.levelno == logging.WARNING and EXPECTED_NOTE_ID in r.getMessage() for r in ours)
    for secret in (NOTE_TEXT, SIGNING_SECRET, RESPONSE_URL):
        assert all(secret not in r.getMessage() for r in ours)


def test_failed_delete_after_failed_enqueue_still_returns_retry(
    slack_request, notes_table, capture_queue, caplog, monkeypatch
):
    def boom(table, note_id):
        raise StoreError("ClientError")

    monkeypatch.setattr(capture, "delete_if_captured", boom)
    sqs = _FailingSqs(EndpointConnectionError(endpoint_url="https://sqs.invalid"))
    with caplog.at_level(logging.DEBUG, logger="slackkb"):
        resp = _capture(slack_request(), notes_table, sqs=sqs)
    assert json.loads(resp["body"]) == {"response_type": "ephemeral", "text": capture.RETRY_TEXT}
    ours = [r for r in caplog.records if r.name.startswith("slackkb")]
    warnings = [r.getMessage() for r in ours if r.levelno == logging.WARNING]
    assert sum(EXPECTED_NOTE_ID in m for m in warnings) >= 2
    for secret in (NOTE_TEXT, SIGNING_SECRET, RESPONSE_URL):
        assert all(secret not in r.getMessage() for r in ours)


def test_worker_marks_routed(notes_table, notes_bucket):
    _put(notes_table, "a" * 32)
    resp = worker.handle(
        {"Records": [_record("m1", _job("a" * 32))]}, table=notes_table, bucket=notes_bucket
    )
    assert resp == {"batchItemFailures": []}
    assert get_note(notes_table, "a" * 32).status is NoteStatus.ROUTED


def test_worker_reports_partial_failure(notes_table, notes_bucket):
    _put(notes_table, "a" * 32)
    event = {
        "Records": [
            _record("ok", _job("a" * 32)),
            _record("not-json", "{not json"),
            _record("wrong-shape", json.dumps({"id": "a" * 32})),
            _record("missing-note", _job("b" * 32)),
        ]
    }
    resp = worker.handle(event, table=notes_table, bucket=notes_bucket)
    assert _failures(resp) == ["missing-note", "not-json", "wrong-shape"]
    assert get_note(notes_table, "a" * 32).status is NoteStatus.ROUTED
    assert get_note(notes_table, "b" * 32) is None


class _BrokenTable:
    def update_item(self, **kwargs):
        raise EndpointConnectionError(endpoint_url="https://dynamodb.invalid")

    def get_item(self, **kwargs):
        raise EndpointConnectionError(endpoint_url="https://dynamodb.invalid")


@pytest.mark.parametrize("kind", ["client_error", "botocore_error"])
def test_worker_reports_store_error(aws, notes_bucket, kind):
    if kind == "client_error":
        table = boto3.resource("dynamodb").Table("no-such-table")
    else:
        table = _BrokenTable()
    resp = worker.handle(
        {"Records": [_record("m1", _job("a" * 32))]}, table=table, bucket=notes_bucket
    )
    assert _failures(resp) == ["m1"]


def test_worker_is_idempotent(notes_table, notes_bucket):
    _put(notes_table, "a" * 32)
    event = {"Records": [_record("m1", _job("a" * 32))]}
    assert worker.handle(event, table=notes_table, bucket=notes_bucket) == {
        "batchItemFailures": []
    }
    assert worker.handle(event, table=notes_table, bucket=notes_bucket) == {
        "batchItemFailures": []
    }
    items = notes_table.scan()["Items"]
    assert len(items) == 1
    assert items[0]["status"] == "ROUTED"


def test_worker_leaves_failed_note_alone(notes_table, notes_bucket):
    _put(notes_table, "a" * 32, status=NoteStatus.FAILED)
    resp = worker.handle(
        {"Records": [_record("m1", _job("a" * 32))]}, table=notes_table, bucket=notes_bucket
    )
    assert resp == {"batchItemFailures": []}
    assert get_note(notes_table, "a" * 32).status is NoteStatus.FAILED


def _event(note_id="a" * 32, message_id="m1"):
    return {"Records": [_record(message_id, _job(note_id))]}


def _keys(bucket):
    return [o.key for o in bucket.objects.all()]


def test_worker_writes_okf_then_routes(notes_table, notes_bucket):
    note_id = "a" * 32
    _put(notes_table, note_id)
    resp = worker.handle(_event(note_id), table=notes_table, bucket=notes_bucket)
    assert resp == {"batchItemFailures": []}
    parsed = blob.get_note(notes_bucket, TEAM_ID, note_id)
    assert parsed is not None
    assert parsed.note_id == note_id
    assert parsed.text == "t"
    assert get_note(notes_table, note_id).status is NoteStatus.ROUTED


class _RaisingObject:
    def __init__(self, exc):
        self.exc = exc

    def put(self, **kwargs):
        raise self.exc


class _RaisingBucket:
    def __init__(self, exc):
        self.exc = exc

    def Object(self, key):  # noqa: N802 - boto3 resource API
        return _RaisingObject(self.exc)


@pytest.mark.parametrize("kind", ["client_error", "botocore_error"])
def test_worker_s3_failure_keeps_captured(notes_table, caplog, kind):
    note_id = "a" * 32
    secret_text = "super secret note text"
    note = Note(note_id=note_id, team_id=TEAM_ID, channel_id="C1", user_id="U1", text=secret_text)
    assert put_if_absent(notes_table, note)
    if kind == "client_error":
        exc = ClientError({"Error": {"Code": "AccessDenied", "Message": secret_text}}, "PutObject")
    else:
        exc = EndpointConnectionError(endpoint_url="https://s3.invalid")
    with caplog.at_level(logging.DEBUG, logger="slackkb"):
        resp = worker.handle(
            _event(note_id, "m-s3"), table=notes_table, bucket=_RaisingBucket(exc)
        )
    assert _failures(resp) == ["m-s3"]
    assert get_note(notes_table, note_id).status is NoteStatus.CAPTURED
    ours = [r for r in caplog.records if r.name.startswith("slackkb")]
    warnings = [r.getMessage() for r in ours if r.levelno == logging.WARNING]
    assert any(note_id in m and "m-s3" in m for m in warnings)
    assert all(secret_text not in r.getMessage() for r in ours)


@pytest.mark.parametrize(
    ("exc", "logged"),
    [
        (EndpointConnectionError(endpoint_url="https://dynamodb.invalid"), "store error"),
        (ClientError({"Error": {"Code": "Throttled"}}, "UpdateItem"), "store error"),
        (NoteNotFoundError("a" * 32), "note not found"),
    ],
)
def test_worker_route_failure_after_write_is_a_batch_failure(
    notes_table, notes_bucket, caplog, monkeypatch, exc, logged
):
    def boom(table, note_id, to):
        raise exc

    note_id = "a" * 32
    _put(notes_table, note_id)
    monkeypatch.setattr(worker, "transition_status", boom)
    with caplog.at_level(logging.WARNING, logger="slackkb"):
        resp = worker.handle(_event(note_id, "m-route"), table=notes_table, bucket=notes_bucket)
    assert _failures(resp) == ["m-route"]
    assert blob.get_note(notes_bucket, TEAM_ID, note_id) is not None
    assert get_note(notes_table, note_id).status is NoteStatus.CAPTURED
    warnings = [r.getMessage() for r in caplog.records if r.name.startswith("slackkb")]
    assert any(logged in m and note_id in m and "m-route" in m for m in warnings)


def test_worker_missing_note_warns_and_writes_nothing(notes_table, notes_bucket, caplog):
    note_id = "b" * 32
    with caplog.at_level(logging.WARNING, logger="slackkb"):
        resp = worker.handle(_event(note_id, "m-gone"), table=notes_table, bucket=notes_bucket)
    assert _failures(resp) == ["m-gone"]
    assert _keys(notes_bucket) == []
    warnings = [r.getMessage() for r in caplog.records if r.name.startswith("slackkb")]
    assert any("note not found" in m and note_id in m and "m-gone" in m for m in warnings)


def test_worker_failed_note_writes_nothing(notes_table, notes_bucket):
    _put(notes_table, "a" * 32, status=NoteStatus.FAILED)
    resp = worker.handle(_event(), table=notes_table, bucket=notes_bucket)
    assert resp == {"batchItemFailures": []}
    assert _keys(notes_bucket) == []
    assert get_note(notes_table, "a" * 32).status is NoteStatus.FAILED


def test_worker_redelivery_rewrites_routed_note(notes_table, notes_bucket):
    note_id = "a" * 32
    _put(notes_table, note_id, status=NoteStatus.ROUTED)
    assert _keys(notes_bucket) == []
    resp = worker.handle(_event(note_id), table=notes_table, bucket=notes_bucket)
    assert resp == {"batchItemFailures": []}
    assert _keys(notes_bucket) == [f"notes/{TEAM_ID}/{note_id}.md"]
    assert blob.get_note(notes_bucket, TEAM_ID, note_id) is not None
    assert get_note(notes_table, note_id).status is NoteStatus.ROUTED


def _worker_records(caplog, level):
    return [
        r for r in caplog.records if r.name == "slackkb.worker" and r.levelno == level
    ]


def _run(notes_table, bucket, caplog, note_id="a" * 32, message_id="m1"):
    with caplog.at_level(logging.DEBUG, logger="slackkb"):
        return worker.handle(_event(note_id, message_id), table=notes_table, bucket=bucket)


def test_worker_logs_failed_note_not_written(notes_table, notes_bucket, caplog):
    _put(notes_table, "a" * 32, status=NoteStatus.FAILED)
    assert _run(notes_table, notes_bucket, caplog) == {"batchItemFailures": []}
    (rec,) = _worker_records(caplog, logging.INFO)
    msg = rec.getMessage()
    assert "note failed, no object" in msg and "a" * 32 in msg and "m1" in msg
    assert _worker_records(caplog, logging.WARNING) == []
    assert _keys(notes_bucket) == []


def test_worker_logs_note_routed(notes_table, notes_bucket, caplog):
    _put(notes_table, "a" * 32)
    assert _run(notes_table, notes_bucket, caplog) == {"batchItemFailures": []}
    (rec,) = _worker_records(caplog, logging.INFO)
    msg = rec.getMessage()
    assert "note routed" in msg and "a" * 32 in msg and "m1" in msg
    assert _worker_records(caplog, logging.WARNING) == []


def test_worker_logs_redelivery_rewritten(notes_table, notes_bucket, caplog):
    _put(notes_table, "a" * 32, status=NoteStatus.ROUTED)
    assert _run(notes_table, notes_bucket, caplog) == {"batchItemFailures": []}
    (rec,) = _worker_records(caplog, logging.INFO)
    msg = rec.getMessage()
    assert "note already routed, rewritten" in msg and "a" * 32 in msg and "m1" in msg
    assert _worker_records(caplog, logging.WARNING) == []
    assert _keys(notes_bucket) == [f"notes/{TEAM_ID}/{'a' * 32}.md"]


class _RaceTable:
    """Passes through to a real table, but flips the status just before the first update."""

    def __init__(self, table, new_status):
        self.table = table
        self.new_status = new_status

    def update_item(self, **kwargs):
        if self.new_status is not None:
            self.table.update_item(
                Key=kwargs["Key"],
                UpdateExpression="SET #status = :s",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":s": self.new_status.value},
            )
            self.new_status = None
        return self.table.update_item(**kwargs)

    def __getattr__(self, name):
        return getattr(self.table, name)


def test_worker_lost_race_to_routed_keeps_object(notes_table, notes_bucket, caplog):
    note_id = "a" * 32
    _put(notes_table, note_id)
    table = _RaceTable(notes_table, NoteStatus.ROUTED)
    assert _run(table, notes_bucket, caplog) == {"batchItemFailures": []}
    assert _keys(notes_bucket) == [f"notes/{TEAM_ID}/{note_id}.md"]
    (rec,) = _worker_records(caplog, logging.INFO)
    assert note_id in rec.getMessage() and "m1" in rec.getMessage()
    assert _worker_records(caplog, logging.WARNING) == []


def test_worker_lost_race_to_failed_removes_object(notes_table, notes_bucket, caplog):
    note_id = "a" * 32
    _put(notes_table, note_id)
    table = _RaceTable(notes_table, NoteStatus.FAILED)
    assert _run(table, notes_bucket, caplog) == {"batchItemFailures": []}
    assert _keys(notes_bucket) == []
    assert get_note(notes_table, note_id).status is NoteStatus.FAILED
    (rec,) = _worker_records(caplog, logging.WARNING)
    msg = rec.getMessage()
    assert note_id in msg and "m1" in msg and "removed" in msg


class _DeleteFailingBucket:
    def __init__(self, bucket, exc):
        self.bucket = bucket
        self.exc = exc

    def Object(self, key):  # noqa: N802 - boto3 resource API
        obj = self.bucket.Object(key)
        exc = self.exc

        class _Obj:
            def put(self, **kwargs):
                return obj.put(**kwargs)

            def delete(self, **kwargs):
                raise exc

        return _Obj()


@pytest.mark.parametrize("kind", ["client_error", "botocore_error"])
def test_worker_lost_race_to_failed_delete_failure_retries(
    notes_table, notes_bucket, caplog, kind
):
    note_id = "a" * 32
    _put(notes_table, note_id)
    if kind == "client_error":
        exc = ClientError({"Error": {"Code": "AccessDenied"}}, "DeleteObject")
    else:
        exc = EndpointConnectionError(endpoint_url="https://s3.invalid")
    table = _RaceTable(notes_table, NoteStatus.FAILED)
    resp = _run(table, _DeleteFailingBucket(notes_bucket, exc), caplog, message_id="m-del")
    assert _failures(resp) == ["m-del"]
    assert _keys(notes_bucket) == [f"notes/{TEAM_ID}/{note_id}.md"]
    (rec,) = _worker_records(caplog, logging.WARNING)
    msg = rec.getMessage()
    assert type(exc).__name__ in msg and note_id in msg and "m-del" in msg


def _lost_race(monkeypatch, second):
    """transition_status reports a lost race; the re-read returns `second` (or raises it)."""
    real = worker.get_note
    calls = []

    def fake_get(table, note_id):
        calls.append(note_id)
        if len(calls) == 1:
            return real(table, note_id)
        if isinstance(second, Exception):
            raise second
        return second

    monkeypatch.setattr(worker, "get_note", fake_get)
    monkeypatch.setattr(worker, "transition_status", lambda table, note_id, to: False)


@pytest.mark.parametrize(
    "second",
    [
        None,
        EndpointConnectionError(endpoint_url="https://dynamodb.invalid"),
        ClientError({"Error": {"Code": "Throttled"}}, "GetItem"),
    ],
    ids=["gone", "botocore_error", "client_error"],
)
def test_worker_lost_race_reread_unusable_is_batch_failure(
    notes_table, notes_bucket, caplog, monkeypatch, second
):
    note_id = "a" * 32
    _put(notes_table, note_id)
    _lost_race(monkeypatch, second)
    resp = _run(notes_table, notes_bucket, caplog, message_id="m-re")
    assert _failures(resp) == ["m-re"]
    (rec,) = _worker_records(caplog, logging.WARNING)
    assert note_id in rec.getMessage() and "m-re" in rec.getMessage()


def test_worker_lost_race_still_captured_is_batch_failure(
    notes_table, notes_bucket, caplog, monkeypatch
):
    note_id = "a" * 32
    _put(notes_table, note_id)
    still_captured = Note(note_id=note_id, team_id=TEAM_ID, channel_id="C1", user_id="U1", text="t")
    _lost_race(monkeypatch, still_captured)
    resp = _run(notes_table, notes_bucket, caplog, message_id="m-cap")
    assert _failures(resp) == ["m-cap"]
    (rec,) = _worker_records(caplog, logging.WARNING)
    assert note_id in rec.getMessage()


def test_worker_failed_note_deletes_object(notes_table, notes_bucket, monkeypatch):
    note_id = "a" * 32
    _put(notes_table, note_id, status=NoteStatus.FAILED)
    calls = []
    real = worker.delete_note
    monkeypatch.setattr(worker, "delete_note", lambda *a: (calls.append(a), real(*a))[1])
    assert worker.handle(_event(note_id), table=notes_table, bucket=notes_bucket) == {
        "batchItemFailures": []
    }
    assert calls == [(notes_bucket, TEAM_ID, note_id)]


@pytest.mark.parametrize("kind", ["client_error", "botocore_error"])
def test_worker_failed_note_delete_failure_retries_then_removes(
    notes_table, notes_bucket, caplog, kind
):
    note_id = "a" * 32
    _put(notes_table, note_id, status=NoteStatus.FAILED)
    blob.put_note(
        notes_bucket,
        Note(note_id=note_id, team_id=TEAM_ID, channel_id="C1", user_id="U1", text="t"),
    )
    if kind == "client_error":
        exc = ClientError({"Error": {"Code": "AccessDenied"}}, "DeleteObject")
    else:
        exc = EndpointConnectionError(endpoint_url="https://s3.invalid")
    first = _run(notes_table, _DeleteFailingBucket(notes_bucket, exc), caplog, message_id="m-d1")
    assert _failures(first) == ["m-d1"]
    assert _keys(notes_bucket) == [f"notes/{TEAM_ID}/{note_id}.md"]
    (rec,) = _worker_records(caplog, logging.WARNING)
    msg = rec.getMessage()
    assert type(exc).__name__ in msg and note_id in msg and "m-d1" in msg
    caplog.clear()
    second = _run(notes_table, notes_bucket, caplog, message_id="m-d2")
    assert second == {"batchItemFailures": []}
    assert _keys(notes_bucket) == []
    assert get_note(notes_table, note_id).status is NoteStatus.FAILED
    (info,) = _worker_records(caplog, logging.INFO)
    assert "note failed, no object" in info.getMessage()


def test_worker_lost_race_still_captured_warns_and_retries(
    notes_table, notes_bucket, caplog, monkeypatch
):
    note_id = "a" * 32
    _put(notes_table, note_id)
    still_captured = Note(note_id=note_id, team_id=TEAM_ID, channel_id="C1", user_id="U1", text="t")
    _lost_race(monkeypatch, still_captured)
    resp = _run(notes_table, notes_bucket, caplog, message_id="m-cap2")
    assert _failures(resp) == ["m-cap2"]
    (rec,) = _worker_records(caplog, logging.WARNING)
    msg = rec.getMessage()
    assert "after lost race" in msg and "CAPTURED" in msg and note_id in msg and "m-cap2" in msg
    assert _worker_records(caplog, logging.INFO) == []


def test_worker_logs_never_contain_secrets(notes_table, notes_bucket, caplog, monkeypatch):
    signature = sign(NOTE_TEXT, 1)
    raw_body = json.dumps(
        {
            "text": NOTE_TEXT,
            "signing_secret": SIGNING_SECRET,
            "bot_token": BOT_TOKEN,
            "signature": signature,
            "response_url": RESPONSE_URL,
        }
    )
    # str(ClientError) carries the service's message, so logging the exception would leak these.
    leaky = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": f"{NOTE_TEXT} {RESPONSE_URL}"}}, "Op"
    )

    def raises(*args, **kwargs):
        raise leaky

    def put(fill, status=NoteStatus.CAPTURED):
        note_id = fill * 32
        note = Note(
            note_id=note_id,
            team_id=TEAM_ID,
            channel_id="C1",
            user_id="U1",
            text=NOTE_TEXT,
            status=status,
        )
        assert put_if_absent(notes_table, note)
        return note_id

    delete_fails = _DeleteFailingBucket(notes_bucket, leaky)
    seen = []

    def run(note_id, table=notes_table, bucket=notes_bucket):
        seen.append(note_id)
        _run(table, bucket, caplog, note_id=note_id, message_id=f"m-{note_id[0]}")

    with caplog.at_level(logging.DEBUG, logger="slackkb"):
        worker.handle(
            {"Records": [_record("m-bad", raw_body)]}, table=notes_table, bucket=notes_bucket
        )
    run(put("0"))
    run(put("1", NoteStatus.FAILED))
    run(put("2", NoteStatus.ROUTED))
    run("3" * 32)
    run(put("4"), bucket=_RaisingBucket(leaky))
    run(put("5"), table=_RaceTable(notes_table, NoteStatus.ROUTED))
    run(put("6"), table=_RaceTable(notes_table, NoteStatus.FAILED))
    run(put("7"), table=_RaceTable(notes_table, NoteStatus.FAILED), bucket=delete_fails)
    with monkeypatch.context() as m:
        m.setattr(worker, "get_note", raises)
        run(put("8"))
    with monkeypatch.context() as m:
        m.setattr(worker, "transition_status", raises)
        run(put("9"))
    with monkeypatch.context() as m:
        _lost_race(m, None)
        run(put("a"))
    with monkeypatch.context() as m:
        _lost_race(m, leaky)
        run(put("b"))

    assert "m-bad" in caplog.text
    assert all(note_id in caplog.text for note_id in seen)
    for value in (NOTE_TEXT, SIGNING_SECRET, BOT_TOKEN, signature, RESPONSE_URL, raw_body):
        assert value not in caplog.text
    assert "response_url" not in caplog.text


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
    [
        ("capture.py", {"slackkb.store", "slackkb.queue"}),
        ("worker.py", {"slackkb.store", "slackkb.blob"}),
    ],
)
def test_handlers_import_no_boto3(name, boundaries):
    source = (SRC / name).read_text()
    modules = set(_imported_modules(ast.parse(source)))
    for module in modules - {"botocore.exceptions"}:
        for banned in BANNED:
            assert module != banned and not module.startswith(banned + "."), module
    assert boundaries <= modules
    assert "response_url" not in source
