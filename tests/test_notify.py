import hashlib
import json
import logging
import time

import boto3
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from conftest import MAX_RECEIVES

from slackkb import blob, capture, notify
from slackkb.config import Settings
from slackkb.models import CaptureJob, Note, NoteStatus
from slackkb.slack_api import ResponseUrlError
from slackkb.store import get_note, put_if_absent
from slackkb.vectors import DIMENSIONS, list_vectors, put_vector

TEAM_ID = "T000TEST"
TRIGGER_ID = "1111.2222.abcdef"
NOTE_ID = hashlib.sha256(f"{TEAM_ID}:{TRIGGER_ID}".encode()).hexdigest()[:32]
OTHER_ID = "b" * 32
NOTE_TEXT = "db connection timeouts on /api/orders since 14:05"
SECRET_TEXT = "secret-note-text-xyzzy"
RESPONSE_URL = "https://hooks.slack.invalid/commands/T000TEST/1/abc"
EXPECTED_TEXT = "Sorry, your /bnote note couldn't be saved. Please run /bnote again."


class Poster:
    def __init__(self, exc=None):
        self.calls = []
        self.exc = exc

    def __call__(self, url, text):
        self.calls.append((url, text))
        if self.exc is not None:
            raise self.exc


def _note(note_id=NOTE_ID, status=NoteStatus.CAPTURED, text=SECRET_TEXT):
    return Note(
        note_id=note_id,
        team_id=TEAM_ID,
        channel_id="C1",
        user_id="U1",
        text=text if status is not NoteStatus.ROUTED else None,
        status=status,
    )


def _seed(table, bucket, vectors, note_id=NOTE_ID, status=NoteStatus.CAPTURED):
    note = _note(note_id, status)
    assert put_if_absent(table, note)
    blob.put_note(bucket, _note(note_id, NoteStatus.CAPTURED))
    put_vector(vectors, TEAM_ID, note_id, [0.5] * DIMENSIONS)


def _record(message_id, note_id=NOTE_ID, url=RESPONSE_URL):
    body = CaptureJob(note_id=note_id, response_url=url).model_dump_json()
    return {"messageId": message_id, "receiptHandle": "rh", "body": body}


def _event(*records):
    return {"Records": list(records)}


def _run(event, table, bucket, vectors, post):
    return notify.handle(event, table=table, bucket=bucket, vectors_table=vectors, post=post)


def _gone(bucket, vectors, note_id=NOTE_ID):
    return (
        blob.get_note(bucket, TEAM_ID, note_id) is None
        and list_vectors(vectors, TEAM_ID) == []
    )


def _present(bucket, vectors, note_id=NOTE_ID):
    return blob.get_note(bucket, TEAM_ID, note_id) is not None and [
        n for n, _ in list_vectors(vectors, TEAM_ID)
    ] == [note_id]


def _client_error(code="InternalError"):
    return ClientError({"Error": {"Code": code, "Message": "m"}}, "Op")


def test_failed_note_notifies_user(
    slack_request, notes_table, notes_bucket, vectors_table, capture_queue
):
    sqs = boto3.client("sqs")
    capture.handle(
        slack_request(), table=notes_table, sqs=sqs, settings=Settings(), now=int(time.time())
    )
    for _ in range(MAX_RECEIVES):
        got = sqs.receive_message(QueueUrl=capture_queue.url, VisibilityTimeout=0)
        assert len(got["Messages"]) == 1
    assert "Messages" not in sqs.receive_message(QueueUrl=capture_queue.url, VisibilityTimeout=0)
    message = sqs.receive_message(QueueUrl=capture_queue.dlq_url)["Messages"][0]
    event = {
        "Records": [
            {
                "messageId": message["MessageId"],
                "receiptHandle": message["ReceiptHandle"],
                "body": message["Body"],
            }
        ]
    }
    post = Poster()
    result = _run(event, notes_table, notes_bucket, vectors_table, post)
    assert get_note(notes_table, NOTE_ID).status is NoteStatus.FAILED
    assert post.calls == [(RESPONSE_URL, EXPECTED_TEXT)]
    assert result == {"batchItemFailures": []}


def test_failed_text_is_fixed():
    assert notify.FAILED_TEXT == EXPECTED_TEXT


def test_failed_note_object_and_vector_removed(notes_table, notes_bucket, vectors_table):
    _seed(notes_table, notes_bucket, vectors_table)
    assert _present(notes_bucket, vectors_table)
    post = Poster()
    result = _run(_event(_record("m1")), notes_table, notes_bucket, vectors_table, post)
    assert result == {"batchItemFailures": []}
    assert _gone(notes_bucket, vectors_table)
    assert get_note(notes_table, NOTE_ID).status is NoteStatus.FAILED
    assert post.calls == [(RESPONSE_URL, EXPECTED_TEXT)]


def test_routed_note_gets_no_notice(notes_table, notes_bucket, vectors_table):
    _seed(notes_table, notes_bucket, vectors_table, status=NoteStatus.ROUTED)
    post = Poster()
    result = _run(_event(_record("m1")), notes_table, notes_bucket, vectors_table, post)
    assert result == {"batchItemFailures": []}
    assert post.calls == []
    assert get_note(notes_table, NOTE_ID).status is NoteStatus.ROUTED
    assert _present(notes_bucket, vectors_table)


def test_repeat_dlq_delivery_posts_again(notes_table, notes_bucket, vectors_table):
    _seed(notes_table, notes_bucket, vectors_table, status=NoteStatus.FAILED)
    post = Poster()
    result = _run(_event(_record("m1")), notes_table, notes_bucket, vectors_table, post)
    assert result == {"batchItemFailures": []}
    assert post.calls == [(RESPONSE_URL, EXPECTED_TEXT)]
    assert _gone(notes_bucket, vectors_table)
    assert get_note(notes_table, NOTE_ID).status is NoteStatus.FAILED


def test_missing_response_url_finishes_without_notice(notes_table, notes_bucket, vectors_table):
    _seed(notes_table, notes_bucket, vectors_table)
    post = Poster()
    record = _record("m1", url=None)
    assert "response_url" in record["body"]  # serialized as null
    result = _run(_event(record), notes_table, notes_bucket, vectors_table, post)
    assert result == {"batchItemFailures": []}
    assert post.calls == []
    assert get_note(notes_table, NOTE_ID).status is NoteStatus.FAILED
    assert _gone(notes_bucket, vectors_table)
    bare = {"messageId": "m2", "receiptHandle": "rh", "body": json.dumps({"note_id": NOTE_ID})}
    assert _run(_event(bare), notes_table, notes_bucket, vectors_table, post) == {
        "batchItemFailures": []
    }
    assert post.calls == []


@pytest.mark.parametrize("status", [403, 404])
def test_post_4xx_is_not_retried(notes_table, notes_bucket, vectors_table, status):
    _seed(notes_table, notes_bucket, vectors_table)
    post = Poster(ResponseUrlError("response_url returned status", status))
    result = _run(_event(_record("m1")), notes_table, notes_bucket, vectors_table, post)
    assert result == {"batchItemFailures": []}
    assert len(post.calls) == 1
    assert get_note(notes_table, NOTE_ID).status is NoteStatus.FAILED


@pytest.mark.parametrize("status", [500, 503, None])
def test_post_5xx_and_transport_error_are_retried(
    notes_table, notes_bucket, vectors_table, status
):
    _seed(notes_table, notes_bucket, vectors_table)
    post = Poster(ResponseUrlError("failed", status))
    result = _run(_event(_record("m1")), notes_table, notes_bucket, vectors_table, post)
    assert result == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    assert len(post.calls) == 1
    assert _gone(notes_bucket, vectors_table)


@pytest.mark.parametrize("exc", [_client_error(), EndpointConnectionError(endpoint_url="http://x")])
def test_store_error_is_retried(
    monkeypatch, notes_table, notes_bucket, vectors_table, exc
):
    _seed(notes_table, notes_bucket, vectors_table)

    def boom(table, note_id, to, **kwargs):
        raise exc

    monkeypatch.setattr(notify, "transition_status", boom)
    post = Poster()
    result = _run(_event(_record("m1")), notes_table, notes_bucket, vectors_table, post)
    assert result == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    assert post.calls == []
    assert get_note(notes_table, NOTE_ID).status is NoteStatus.CAPTURED
    assert _present(notes_bucket, vectors_table)


def test_store_error_on_reread_is_retried(monkeypatch, notes_table, notes_bucket, vectors_table):
    _seed(notes_table, notes_bucket, vectors_table, status=NoteStatus.ROUTED)

    def boom(table, note_id):
        raise _client_error()

    monkeypatch.setattr(notify, "get_note", boom)
    post = Poster()
    result = _run(_event(_record("m1")), notes_table, notes_bucket, vectors_table, post)
    assert result == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    assert post.calls == []


def test_missing_note_on_reread_finishes(monkeypatch, notes_table, notes_bucket, vectors_table):
    _seed(notes_table, notes_bucket, vectors_table, status=NoteStatus.ROUTED)
    monkeypatch.setattr(notify, "get_note", lambda table, note_id: None)
    post = Poster()
    result = _run(_event(_record("m1")), notes_table, notes_bucket, vectors_table, post)
    assert result == {"batchItemFailures": []}
    assert post.calls == []


@pytest.mark.parametrize("which", ["delete_note", "delete_vector"])
def test_delete_error_is_retried_before_post(
    monkeypatch, notes_table, notes_bucket, vectors_table, which
):
    _seed(notes_table, notes_bucket, vectors_table)

    def boom(*args):
        raise _client_error()

    monkeypatch.setattr(notify, which, boom)
    post = Poster()
    result = _run(_event(_record("m1")), notes_table, notes_bucket, vectors_table, post)
    assert result == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    assert post.calls == []
    assert get_note(notes_table, NOTE_ID).status is NoteStatus.FAILED


def test_delete_error_retry_then_success(monkeypatch, notes_table, notes_bucket, vectors_table):
    _seed(notes_table, notes_bucket, vectors_table)
    with monkeypatch.context() as patch:
        patch.setattr(notify, "delete_note", lambda *a: (_ for _ in ()).throw(_client_error()))
        post = Poster()
        assert _run(_event(_record("m1")), notes_table, notes_bucket, vectors_table, post) == {
            "batchItemFailures": [{"itemIdentifier": "m1"}]
        }
    result = _run(_event(_record("m1")), notes_table, notes_bucket, vectors_table, post)
    assert result == {"batchItemFailures": []}
    assert post.calls == [(RESPONSE_URL, EXPECTED_TEXT)]
    assert _gone(notes_bucket, vectors_table)


def test_unparsable_job_and_missing_note_finish(notes_table, notes_bucket, vectors_table):
    post = Poster()
    records = [
        {"messageId": "bad1", "receiptHandle": "rh", "body": "not json"},
        {"messageId": "bad2", "receiptHandle": "rh", "body": json.dumps({"note_id": "short"})},
        {"messageId": "bad3", "receiptHandle": "rh"},
        _record("gone"),
    ]
    result = _run(_event(*records), notes_table, notes_bucket, vectors_table, post)
    assert result == {"batchItemFailures": []}
    assert post.calls == []


def test_mixed_batch_reports_only_retries(notes_table, notes_bucket, vectors_table):
    ids = {name: f"{i:032x}" for i, name in enumerate(["ok", "retry", "perm", "routed"], 1)}
    for name, note_id in ids.items():
        status = NoteStatus.ROUTED if name == "routed" else NoteStatus.CAPTURED
        _seed(notes_table, notes_bucket, vectors_table, note_id, status)
    urls = {
        "ok": "https://hooks.slack.invalid/ok",
        "retry": "https://hooks.slack.invalid/retry",
        "perm": "https://hooks.slack.invalid/perm",
        "routed": "https://hooks.slack.invalid/routed",
    }
    calls = []

    def post(url, text):
        calls.append(url)
        if url.endswith("/retry"):
            raise ResponseUrlError("failed", 502)
        if url.endswith("/perm"):
            raise ResponseUrlError("failed", 404)

    event = _event(
        _record("m-ok", ids["ok"], urls["ok"]),
        _record("m-retry", ids["retry"], urls["retry"]),
        {"messageId": "m-bad", "receiptHandle": "rh", "body": "{"},
        _record("m-perm", ids["perm"], urls["perm"]),
        _record("m-routed", ids["routed"], urls["routed"]),
    )
    result = _run(event, notes_table, notes_bucket, vectors_table, post)
    assert result == {"batchItemFailures": [{"itemIdentifier": "m-retry"}]}
    assert calls == [urls["ok"], urls["retry"], urls["perm"]]


def test_notify_logs_name_ids_never_url_or_text(
    caplog, monkeypatch, notes_table, notes_bucket, vectors_table
):
    caplog.set_level(logging.DEBUG, logger="slackkb")
    ids = [f"{i:032x}" for i in range(10, 17)]
    for note_id in ids[:6]:
        _seed(notes_table, notes_bucket, vectors_table, note_id)
    _seed(notes_table, notes_bucket, vectors_table, ids[6], status=NoteStatus.ROUTED)
    url = "https://hooks.slack.invalid/commands/SECRETURL/zzz"

    def post(u, text):
        if u.endswith("A"):
            raise ResponseUrlError(f"boom {u}", 404)
        if u.endswith("B"):
            raise ResponseUrlError(f"boom {u}", 500)
        if u.endswith("C"):
            raise ResponseUrlError(f"boom {u}")

    records = [
        _record("m0", ids[0], url + "OK"),
        _record("m1", ids[1], url + "A"),
        _record("m2", ids[2], url + "B"),
        _record("m3", ids[3], url + "C"),
        _record("m4", ids[4], None),
        {"messageId": "m5", "receiptHandle": "rh", "body": "garbage " + url},
        _record("m6", "e" * 32, url + "OK"),
        _record("m7", ids[6], url + "OK"),
    ]
    _run(_event(*records), notes_table, notes_bucket, vectors_table, post)
    monkeypatch.setattr(
        notify, "delete_vector", lambda *a: (_ for _ in ()).throw(_client_error())
    )
    _run(_event(_record("m8", ids[5], url + "OK")), notes_table, notes_bucket, vectors_table, post)
    monkeypatch.setattr(
        notify, "transition_status", lambda *a, **k: (_ for _ in ()).throw(_client_error())
    )
    _run(_event(_record("m9", ids[5], url + "OK")), notes_table, notes_bucket, vectors_table, post)

    ours = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("slackkb"))
    assert ours
    for forbidden in (url, "SECRETURL", "hooks.slack", "response_url", SECRET_TEXT, NOTE_TEXT):
        assert forbidden not in ours
    for record in caplog.records:
        if record.name != "slackkb.notify":
            continue
        message = record.getMessage()
        assert "message_id=m" in message
        if "message_id=m5" not in message:
            assert "note_id=" in message
    names = {r.getMessage() for r in caplog.records if r.name == "slackkb.notify"}
    assert any("note failed" in m for m in names)
    assert any("user notified" in m for m in names)
