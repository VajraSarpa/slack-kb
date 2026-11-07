diff --git a/src/slackkb/blob.py b/src/slackkb/blob.py
new file mode 100644
index 0000000..3628d57
--- /dev/null
+++ b/src/slackkb/blob.py
@@ -0,0 +1,30 @@
+"""The only module that talks to S3 (Slice 4, D-014). The caller passes the Bucket in."""
+
+from typing import Any
+
+from botocore.exceptions import ClientError
+
+from slackkb.models import Note
+from slackkb.okf_note import OkfNote, from_markdown, object_key, to_markdown
+
+CONTENT_TYPE = "text/markdown; charset=utf-8"
+_MISSING = {"NoSuchKey", "404", "NotFound"}
+
+
+def put_note(bucket: Any, note: Note) -> None:
+    """Write the note as an OKF Markdown object; an overwrite is fine."""
+    bucket.Object(object_key(note)).put(
+        Body=to_markdown(note).encode("utf-8"), ContentType=CONTENT_TYPE
+    )
+
+
+def get_note(bucket: Any, team_id: str, note_id: str) -> OkfNote | None:
+    """Read a note back; None if the key does not exist."""
+    key = f"notes/{team_id}/{note_id}.md"
+    try:
+        body = bucket.Object(key).get()["Body"].read()
+    except ClientError as exc:
+        if exc.response.get("Error", {}).get("Code") in _MISSING:
+            return None
+        raise
+    return from_markdown(body.decode("utf-8"))
diff --git a/src/slackkb/config.py b/src/slackkb/config.py
index 920c52f..8993266 100644
--- a/src/slackkb/config.py
+++ b/src/slackkb/config.py
@@ -13,5 +13,6 @@ class Settings(BaseSettings):
 
     signing_secret: SecretStr
     notes_table: str
+    notes_bucket: str
     capture_queue_url: str
     slack_bot_token: SecretStr
diff --git a/src/slackkb/okf_note.py b/src/slackkb/okf_note.py
new file mode 100644
index 0000000..dc5955f
--- /dev/null
+++ b/src/slackkb/okf_note.py
@@ -0,0 +1,77 @@
+"""Note <-> OKF Markdown, pure (Slice 4, D-014).
+
+Frontmatter holds only immutable fields; severity and status stay in DynamoDB.
+"""
+
+import yaml
+from pydantic import BaseModel, ConfigDict, ValidationError
+
+from slackkb.models import Note
+
+DELIMITER = "---\n"
+
+
+class OkfNoteError(ValueError):
+    """The Markdown is not a well-formed OKF note."""
+
+
+class OkfNote(BaseModel):
+    """A note as stored in S3: the five frontmatter fields plus the body text."""
+
+    model_config = ConfigDict(extra="forbid")
+
+    note_id: str
+    team_id: str
+    channel_id: str
+    user_id: str
+    created_at: str
+    text: str
+
+
+class _Frontmatter(BaseModel):
+    model_config = ConfigDict(extra="forbid")
+
+    note_id: str
+    team_id: str
+    channel_id: str
+    user_id: str
+    created_at: str
+
+
+def object_key(note: Note | OkfNote) -> str:
+    return f"notes/{note.team_id}/{note.note_id}.md"
+
+
+def to_markdown(note: Note) -> str:
+    frontmatter = {
+        "note_id": note.note_id,
+        "team_id": note.team_id,
+        "channel_id": note.channel_id,
+        "user_id": note.user_id,
+        "created_at": note.created_at,
+    }
+    return DELIMITER + yaml.safe_dump(frontmatter, sort_keys=True) + DELIMITER + note.text
+
+
+def from_markdown(md: str) -> OkfNote:
+    if not md.startswith(DELIMITER):
+        raise OkfNoteError("missing opening delimiter")
+    rest = md[len(DELIMITER) :]
+    if rest.startswith(DELIMITER):
+        head, body = "", rest[len(DELIMITER) :]
+    else:
+        end = rest.find("\n" + DELIMITER)
+        if end < 0:
+            raise OkfNoteError("missing closing delimiter")
+        head, body = rest[: end + 1], rest[end + 1 + len(DELIMITER) :]
+    try:
+        data = yaml.safe_load(head)
+    except yaml.YAMLError:
+        raise OkfNoteError("frontmatter is not valid YAML") from None
+    if not isinstance(data, dict):
+        raise OkfNoteError("frontmatter is not a mapping")
+    try:
+        front = _Frontmatter.model_validate(data)
+    except ValidationError as exc:
+        raise OkfNoteError(f"invalid frontmatter: {exc.error_count()} error(s)") from None
+    return OkfNote(**front.model_dump(), text=body)
diff --git a/src/slackkb/worker.py b/src/slackkb/worker.py
index 1765610..7415849 100644
--- a/src/slackkb/worker.py
+++ b/src/slackkb/worker.py
@@ -11,20 +11,48 @@ from typing import Any
 from botocore.exceptions import BotoCoreError, ClientError
 from pydantic import ValidationError
 
+from slackkb.blob import put_note
 from slackkb.models import CaptureJob, NoteStatus
-from slackkb.store import NoteNotFoundError, transition_status
+from slackkb.store import NoteNotFoundError, get_note, transition_status
 
 logger = logging.getLogger(__name__)
 
 
-def _process(record: Mapping[str, Any], table: Any) -> bool:
-    """Route one record's note. True on success, including a note already past CAPTURED."""
+def _process(record: Mapping[str, Any], table: Any, bucket: Any) -> bool:
+    """Write one record's note to S3, then route it. True on success, including a FAILED note."""
     message_id = record["messageId"]
     try:
         job = CaptureJob.model_validate_json(record.get("body") or "")
     except ValidationError:
         logger.warning("unparsable capture job, message_id=%s", message_id)
         return False
+    try:
+        note = get_note(table, job.note_id)
+        if note is None:
+            raise NoteNotFoundError(job.note_id)
+        if note.status is NoteStatus.FAILED:
+            return True
+    except NoteNotFoundError:
+        logger.warning("note not found, note_id=%s message_id=%s", job.note_id, message_id)
+        return False
+    except (ClientError, BotoCoreError) as exc:
+        logger.warning(
+            "store error %s, note_id=%s message_id=%s",
+            type(exc).__name__,
+            job.note_id,
+            message_id,
+        )
+        return False
+    try:
+        put_note(bucket, note)
+    except (ClientError, BotoCoreError) as exc:
+        logger.warning(
+            "blob error %s, note_id=%s message_id=%s",
+            type(exc).__name__,
+            job.note_id,
+            message_id,
+        )
+        return False
     try:
         transition_status(table, job.note_id, NoteStatus.ROUTED)
     except NoteNotFoundError:
@@ -41,11 +69,11 @@ def _process(record: Mapping[str, Any], table: Any) -> bool:
     return True
 
 
-def handle(event: Mapping[str, Any], *, table: Any) -> dict:
+def handle(event: Mapping[str, Any], *, table: Any, bucket: Any) -> dict:
     """Handle one SQS Lambda event; return the partial batch response."""
     failures = [
         {"itemIdentifier": record["messageId"]}
         for record in event.get("Records") or []
-        if not _process(record, table)
+        if not _process(record, table, bucket)
     ]
     return {"batchItemFailures": failures}
diff --git a/tests/test_blob.py b/tests/test_blob.py
new file mode 100644
index 0000000..295f30a
--- /dev/null
+++ b/tests/test_blob.py
@@ -0,0 +1,42 @@
+import pytest
+from botocore.exceptions import ClientError
+
+from slackkb import blob
+from slackkb.models import Note
+from slackkb.okf_note import object_key, to_markdown
+
+
+def _note(text="hello ünï\n---\nworld"):
+    return Note(note_id="a" * 32, team_id="T1", channel_id="C1", user_id="U1", text=text)
+
+
+def test_put_then_get_round_trips(notes_bucket):
+    note = _note()
+    assert blob.put_note(notes_bucket, note) is None
+    obj = notes_bucket.Object(object_key(note))
+    assert obj.content_type == "text/markdown; charset=utf-8"
+    assert obj.get()["Body"].read() == to_markdown(note).encode("utf-8")
+    got = blob.get_note(notes_bucket, "T1", "a" * 32)
+    assert got is not None
+    assert (got.note_id, got.team_id, got.channel_id, got.user_id) == ("a" * 32, "T1", "C1", "U1")
+    assert got.created_at == note.created_at
+    assert got.text == note.text
+
+
+def test_get_missing_returns_none(notes_bucket):
+    assert blob.get_note(notes_bucket, "T1", "b" * 32) is None
+
+
+def test_get_other_s3_errors_propagate(aws):
+    import boto3
+
+    missing_bucket = boto3.resource("s3").Bucket("no-such-bucket")
+    with pytest.raises(ClientError):
+        blob.get_note(missing_bucket, "T1", "a" * 32)
+
+
+def test_put_overwrites(notes_bucket):
+    blob.put_note(notes_bucket, _note("first"))
+    blob.put_note(notes_bucket, _note("second"))
+    assert blob.get_note(notes_bucket, "T1", "a" * 32).text == "second"
+    assert len(list(notes_bucket.objects.all())) == 1
diff --git a/tests/test_config.py b/tests/test_config.py
index 076e59a..ec8d88d 100644
--- a/tests/test_config.py
+++ b/tests/test_config.py
@@ -1,5 +1,5 @@
 import pytest
-from conftest import BOT_TOKEN, NOTES_TABLE, SIGNING_SECRET
+from conftest import BOT_TOKEN, NOTES_BUCKET, NOTES_TABLE, SIGNING_SECRET
 from pydantic import SecretStr, ValidationError
 
 from slackkb.config import Settings
@@ -32,6 +32,16 @@ def test_missing_notes_table_fails(monkeypatch):
         Settings()
 
 
+def test_reads_notes_bucket():
+    assert Settings().notes_bucket == NOTES_BUCKET
+
+
+def test_missing_notes_bucket_fails(monkeypatch):
+    monkeypatch.delenv("SLACKKB_NOTES_BUCKET")
+    with pytest.raises(ValidationError):
+        Settings()
+
+
 def test_missing_capture_queue_url_fails(monkeypatch):
     monkeypatch.delenv("SLACKKB_CAPTURE_QUEUE_URL")
     with pytest.raises(ValidationError):
diff --git a/tests/test_okf_note.py b/tests/test_okf_note.py
new file mode 100644
index 0000000..61eaaf9
--- /dev/null
+++ b/tests/test_okf_note.py
@@ -0,0 +1,126 @@
+import pytest
+import yaml
+
+from slackkb.models import Note, NoteStatus, Severity
+from slackkb.okf_note import OkfNote, OkfNoteError, from_markdown, object_key, to_markdown
+
+FIELDS = ("note_id", "team_id", "channel_id", "user_id", "created_at")
+
+
+def _note(**over):
+    base = {
+        "note_id": "a" * 32,
+        "team_id": "T000TEST",
+        "channel_id": "C1",
+        "user_id": "U1",
+        "text": "db connection timeouts on /api/orders",
+        "created_at": "2026-11-05T12:30:00.123456+00:00",
+    }
+    return Note(**{**base, **over})
+
+
+def _assert_round_trip(note):
+    parsed = from_markdown(to_markdown(note))
+    assert isinstance(parsed, OkfNote)
+    for field in FIELDS:
+        assert getattr(parsed, field) == getattr(note, field)
+    assert parsed.text == note.text
+
+
+def test_note_round_trips_as_okf():
+    note = _note(severity=Severity.HIGH, status=NoteStatus.ROUTED)
+    md = to_markdown(note)
+    frontmatter = {f: getattr(note, f) for f in FIELDS}
+    assert md == "---\n" + yaml.safe_dump(frontmatter, sort_keys=True) + "---\n" + note.text
+    _assert_round_trip(note)
+
+
+def test_frontmatter_excludes_severity_status_and_text():
+    note = _note(severity=Severity.CRITICAL, status=NoteStatus.ROUTED, text="unique-body-text")
+    md = to_markdown(note)
+    head = md.split("---\n")[1]
+    assert set(yaml.safe_load(head)) == set(FIELDS)
+    for absent in ("severity", "status", "CRITICAL", "ROUTED", "unique-body-text"):
+        assert absent not in head
+    assert md.endswith("---\nunique-body-text")
+
+
+@pytest.mark.parametrize(
+    "text",
+    [
+        "line\n---\nmore",
+        "---\n---\n",
+        "---\nnote_id: evil\n---\nx",
+        "key: value\nlist:\n  - a\n  - b\n",
+        "# heading\n\n- bullet: yes\n",
+    ],
+)
+def test_body_with_delimiter_and_yaml_round_trips(text):
+    _assert_round_trip(_note(text=text))
+
+
+@pytest.mark.parametrize(
+    "over",
+    [
+        {"note_id": "1e10"},
+        {"note_id": "0123"},
+        {"note_id": "123456"},
+        {"note_id": "true"},
+        {"note_id": "null"},
+        {"team_id": "0x1F"},
+        {"channel_id": "1_000"},
+        {"user_id": "yes"},
+        {"created_at": "2026-11-05"},
+        {"created_at": "2026-11-05T12:30:00+00:00"},
+        {"text": ""},
+        {"text": "trailing newline\n"},
+        {"text": "unicode: héllo — 日本語 🚀"},
+        {"user_id": "ünï: \"quoted\" #x"},
+    ],
+)
+def test_yaml_lookalike_values_stay_strings(over):
+    note = _note(**over)
+    _assert_round_trip(note)
+    parsed = from_markdown(to_markdown(note))
+    for field in FIELDS:
+        assert isinstance(getattr(parsed, field), str)
+
+
+VALID_HEAD = (
+    "note_id: abc\nteam_id: T1\nchannel_id: C1\nuser_id: U1\n"
+    "created_at: '2026-11-05T00:00:00+00:00'\n"
+)
+
+
+@pytest.mark.parametrize(
+    ("md", "reason"),
+    [
+        ("note_id: abc\n", "missing opening delimiter"),
+        ("", "missing opening delimiter"),
+        ("--- \n" + VALID_HEAD + "---\nbody", "missing opening delimiter"),  # not an exact line
+        ("---\n" + VALID_HEAD + "body", "missing closing delimiter"),
+        ("---\n" + VALID_HEAD + "---", "missing closing delimiter"),  # no newline, no real line
+        ("---\n", "missing closing delimiter"),
+        ("---\n- a\n- b\n---\nbody", "not a mapping"),  # sequence frontmatter
+        ("---\njust a string\n---\nbody", "not a mapping"),  # scalar frontmatter
+        ("---\n---\nbody", "not a mapping"),  # empty frontmatter
+        ("---\n: : [\n---\nbody", "not valid YAML"),
+        ("---\n" + VALID_HEAD.replace("team_id: T1\n", "") + "---\nbody", "invalid frontmatter"),
+        ("---\n" + VALID_HEAD + "severity: HIGH\n---\nbody", "invalid frontmatter"),  # unknown key
+        (
+            "---\n" + VALID_HEAD.replace("note_id: abc", "note_id: 123") + "---\nbody",
+            "invalid frontmatter",  # not a string
+        ),
+    ],
+)
+def test_malformed_markdown_raises(md, reason):
+    with pytest.raises(OkfNoteError, match=reason):
+        from_markdown(md)
+
+
+def test_okf_note_error_is_value_error():
+    assert issubclass(OkfNoteError, ValueError)
+
+
+def test_object_key():
+    assert object_key(_note()) == f"notes/T000TEST/{'a' * 32}.md"
diff --git a/tests/test_worker.py b/tests/test_worker.py
index b1524ba..837a397 100644
--- a/tests/test_worker.py
+++ b/tests/test_worker.py
@@ -7,13 +7,13 @@ from pathlib import Path
 
 import boto3
 import pytest
-from botocore.exceptions import EndpointConnectionError
+from botocore.exceptions import ClientError, EndpointConnectionError
 from conftest import SIGNING_SECRET
 
-from slackkb import capture, worker
+from slackkb import blob, capture, worker
 from slackkb.config import Settings
 from slackkb.models import CaptureJob, Note, NoteStatus
-from slackkb.store import StoreError, get_note, put_if_absent
+from slackkb.store import NoteNotFoundError, StoreError, get_note, put_if_absent
 
 SRC = Path(__file__).parent.parent / "src" / "slackkb"
 TEAM_ID = "T000TEST"
@@ -127,14 +127,16 @@ def test_failed_delete_after_failed_enqueue_still_returns_retry(
         assert all(secret not in r.getMessage() for r in ours)
 
 
-def test_worker_marks_routed(notes_table):
+def test_worker_marks_routed(notes_table, notes_bucket):
     _put(notes_table, "a" * 32)
-    resp = worker.handle({"Records": [_record("m1", _job("a" * 32))]}, table=notes_table)
+    resp = worker.handle(
+        {"Records": [_record("m1", _job("a" * 32))]}, table=notes_table, bucket=notes_bucket
+    )
     assert resp == {"batchItemFailures": []}
     assert get_note(notes_table, "a" * 32).status is NoteStatus.ROUTED
 
 
-def test_worker_reports_partial_failure(notes_table):
+def test_worker_reports_partial_failure(notes_table, notes_bucket):
     _put(notes_table, "a" * 32)
     event = {
         "Records": [
@@ -144,7 +146,7 @@ def test_worker_reports_partial_failure(notes_table):
             _record("missing-note", _job("b" * 32)),
         ]
     }
-    resp = worker.handle(event, table=notes_table)
+    resp = worker.handle(event, table=notes_table, bucket=notes_bucket)
     assert _failures(resp) == ["missing-note", "not-json", "wrong-shape"]
     assert get_note(notes_table, "a" * 32).status is NoteStatus.ROUTED
     assert get_note(notes_table, "b" * 32) is None
@@ -159,32 +161,153 @@ class _BrokenTable:
 
 
 @pytest.mark.parametrize("kind", ["client_error", "botocore_error"])
-def test_worker_reports_store_error(aws, kind):
+def test_worker_reports_store_error(aws, notes_bucket, kind):
     if kind == "client_error":
         table = boto3.resource("dynamodb").Table("no-such-table")
     else:
         table = _BrokenTable()
-    resp = worker.handle({"Records": [_record("m1", _job("a" * 32))]}, table=table)
+    resp = worker.handle(
+        {"Records": [_record("m1", _job("a" * 32))]}, table=table, bucket=notes_bucket
+    )
     assert _failures(resp) == ["m1"]
 
 
-def test_worker_is_idempotent(notes_table):
+def test_worker_is_idempotent(notes_table, notes_bucket):
     _put(notes_table, "a" * 32)
     event = {"Records": [_record("m1", _job("a" * 32))]}
-    assert worker.handle(event, table=notes_table) == {"batchItemFailures": []}
-    assert worker.handle(event, table=notes_table) == {"batchItemFailures": []}
+    assert worker.handle(event, table=notes_table, bucket=notes_bucket) == {
+        "batchItemFailures": []
+    }
+    assert worker.handle(event, table=notes_table, bucket=notes_bucket) == {
+        "batchItemFailures": []
+    }
     items = notes_table.scan()["Items"]
     assert len(items) == 1
     assert items[0]["status"] == "ROUTED"
 
 
-def test_worker_leaves_failed_note_alone(notes_table):
+def test_worker_leaves_failed_note_alone(notes_table, notes_bucket):
+    _put(notes_table, "a" * 32, status=NoteStatus.FAILED)
+    resp = worker.handle(
+        {"Records": [_record("m1", _job("a" * 32))]}, table=notes_table, bucket=notes_bucket
+    )
+    assert resp == {"batchItemFailures": []}
+    assert get_note(notes_table, "a" * 32).status is NoteStatus.FAILED
+
+
+def _event(note_id="a" * 32, message_id="m1"):
+    return {"Records": [_record(message_id, _job(note_id))]}
+
+
+def _keys(bucket):
+    return [o.key for o in bucket.objects.all()]
+
+
+def test_worker_writes_okf_then_routes(notes_table, notes_bucket):
+    note_id = "a" * 32
+    _put(notes_table, note_id)
+    resp = worker.handle(_event(note_id), table=notes_table, bucket=notes_bucket)
+    assert resp == {"batchItemFailures": []}
+    parsed = blob.get_note(notes_bucket, TEAM_ID, note_id)
+    assert parsed is not None
+    assert parsed.note_id == note_id
+    assert parsed.text == "t"
+    assert get_note(notes_table, note_id).status is NoteStatus.ROUTED
+
+
+class _RaisingObject:
+    def __init__(self, exc):
+        self.exc = exc
+
+    def put(self, **kwargs):
+        raise self.exc
+
+
+class _RaisingBucket:
+    def __init__(self, exc):
+        self.exc = exc
+
+    def Object(self, key):  # noqa: N802 - boto3 resource API
+        return _RaisingObject(self.exc)
+
+
+@pytest.mark.parametrize("kind", ["client_error", "botocore_error"])
+def test_worker_s3_failure_keeps_captured(notes_table, caplog, kind):
+    note_id = "a" * 32
+    secret_text = "super secret note text"
+    note = Note(note_id=note_id, team_id=TEAM_ID, channel_id="C1", user_id="U1", text=secret_text)
+    assert put_if_absent(notes_table, note)
+    if kind == "client_error":
+        exc = ClientError({"Error": {"Code": "AccessDenied", "Message": secret_text}}, "PutObject")
+    else:
+        exc = EndpointConnectionError(endpoint_url="https://s3.invalid")
+    with caplog.at_level(logging.DEBUG, logger="slackkb"):
+        resp = worker.handle(
+            _event(note_id, "m-s3"), table=notes_table, bucket=_RaisingBucket(exc)
+        )
+    assert _failures(resp) == ["m-s3"]
+    assert get_note(notes_table, note_id).status is NoteStatus.CAPTURED
+    ours = [r for r in caplog.records if r.name.startswith("slackkb")]
+    warnings = [r.getMessage() for r in ours if r.levelno == logging.WARNING]
+    assert any(note_id in m and "m-s3" in m for m in warnings)
+    assert all(secret_text not in r.getMessage() for r in ours)
+
+
+@pytest.mark.parametrize(
+    ("exc", "logged"),
+    [
+        (EndpointConnectionError(endpoint_url="https://dynamodb.invalid"), "store error"),
+        (ClientError({"Error": {"Code": "Throttled"}}, "UpdateItem"), "store error"),
+        (NoteNotFoundError("a" * 32), "note not found"),
+    ],
+)
+def test_worker_route_failure_after_write_is_a_batch_failure(
+    notes_table, notes_bucket, caplog, monkeypatch, exc, logged
+):
+    def boom(table, note_id, to):
+        raise exc
+
+    note_id = "a" * 32
+    _put(notes_table, note_id)
+    monkeypatch.setattr(worker, "transition_status", boom)
+    with caplog.at_level(logging.WARNING, logger="slackkb"):
+        resp = worker.handle(_event(note_id, "m-route"), table=notes_table, bucket=notes_bucket)
+    assert _failures(resp) == ["m-route"]
+    assert blob.get_note(notes_bucket, TEAM_ID, note_id) is not None
+    assert get_note(notes_table, note_id).status is NoteStatus.CAPTURED
+    warnings = [r.getMessage() for r in caplog.records if r.name.startswith("slackkb")]
+    assert any(logged in m and note_id in m and "m-route" in m for m in warnings)
+
+
+def test_worker_missing_note_warns_and_writes_nothing(notes_table, notes_bucket, caplog):
+    note_id = "b" * 32
+    with caplog.at_level(logging.WARNING, logger="slackkb"):
+        resp = worker.handle(_event(note_id, "m-gone"), table=notes_table, bucket=notes_bucket)
+    assert _failures(resp) == ["m-gone"]
+    assert _keys(notes_bucket) == []
+    warnings = [r.getMessage() for r in caplog.records if r.name.startswith("slackkb")]
+    assert any("note not found" in m and note_id in m and "m-gone" in m for m in warnings)
+
+
+def test_worker_failed_note_writes_nothing(notes_table, notes_bucket):
     _put(notes_table, "a" * 32, status=NoteStatus.FAILED)
-    resp = worker.handle({"Records": [_record("m1", _job("a" * 32))]}, table=notes_table)
+    resp = worker.handle(_event(), table=notes_table, bucket=notes_bucket)
     assert resp == {"batchItemFailures": []}
+    assert _keys(notes_bucket) == []
     assert get_note(notes_table, "a" * 32).status is NoteStatus.FAILED
 
 
+def test_worker_redelivery_rewrites_routed_note(notes_table, notes_bucket):
+    note_id = "a" * 32
+    _put(notes_table, note_id, status=NoteStatus.ROUTED)
+    assert _keys(notes_bucket) == []
+    resp = worker.handle(_event(note_id), table=notes_table, bucket=notes_bucket)
+    assert resp == {"batchItemFailures": []}
+    assert _keys(notes_bucket) == [f"notes/{TEAM_ID}/{note_id}.md"]
+    assert blob.get_note(notes_bucket, TEAM_ID, note_id) is not None
+    assert get_note(notes_table, note_id).status is NoteStatus.ROUTED
+
+
 def _imported_modules(tree):
     for node in ast.walk(tree):
         if isinstance(node, ast.Import):
@@ -211,7 +334,10 @@ BANNED = (
 
 @pytest.mark.parametrize(
     ("name", "boundaries"),
-    [("capture.py", {"slackkb.store", "slackkb.queue"}), ("worker.py", {"slackkb.store"})],
+    [
+        ("capture.py", {"slackkb.store", "slackkb.queue"}),
+        ("worker.py", {"slackkb.store", "slackkb.blob"}),
+    ],
 )
 def test_handlers_import_no_boto3(name, boundaries):
     source = (SRC / name).read_text()

review PASS: The diff meets requirements 1-8 and D-014/D-009, and it touches only SCOPE paths. Each behavior requirement has a test that would fail if it broke: exact markdown, first-delimiter split, malformed-input reasons, content type and bytes, propagation of other S3 errors, S3 failure keeps CAPTURED and logs no note text (checked by value), FAILED writes nothing, and redelivery starts from an empty bucket. Existing worker tests only gain the bucket, with the same expected values. I traced c5 through the code and it holds. c2 matches the diff's file list. The c3 and c4 mutant runs can't be re-run from the brief, but they are consistent with what the tests assert. One minor robustness gap in from_markdown is reported; it is outside the failure rules the spec lists.
  [minor] src/slackkb/okf_note.py: from_markdown catches only yaml.YAMLError around yaml.safe_load, but PyYAML's constructors can raise a plain ValueError. For example, frontmatter `created_at: 2026-13-45` matches the timestamp resolver and then fails in datetime.date(); `note_id: 0x_` fails the same way in int(). The caller gets a bare ValueError rather than OkfNoteError, so `except OkfNoteError` misses it, even though other bad YAML is wrapped. The spec's listed OkfNoteError cases don't name this input, so this is not a requirement breach. Fix by catching ValueError alongside yaml.YAMLError, and add a case to test_malformed_markdown_raises.
merge prama/personal_150f0a7c into the current branch of /home/vajrasarpa/Projects/slack-kb? [y/N]: merged as 0255d6a3cbab. Nothing was pushed.
