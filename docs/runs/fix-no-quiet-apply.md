rechecked: `python -m pytest` exit 0, `python -m ruff check src tests` exit 0, `python -m pytest tests/test_okf_note.py tests/test_blob.py tests/test_worker.py tests/test_capture.py tests/test_modal.py` exit 0, `python -m pytest -q` exit 0
note: the capped attempt logged no claims, so prama eval had nothing of it to replay
diff --git a/src/slackkb/blob.py b/src/slackkb/blob.py
index 3628d57..4c956d3 100644
--- a/src/slackkb/blob.py
+++ b/src/slackkb/blob.py
@@ -5,22 +5,31 @@ from typing import Any
 from botocore.exceptions import ClientError
 
 from slackkb.models import Note
-from slackkb.okf_note import OkfNote, from_markdown, object_key, to_markdown
+from slackkb.okf_note import OkfNote, from_markdown, to_markdown
 
 CONTENT_TYPE = "text/markdown; charset=utf-8"
 _MISSING = {"NoSuchKey", "404", "NotFound"}
 
 
+def _key(team_id: str, note_id: str) -> str:
+    return f"notes/{team_id}/{note_id}.md"
+
+
 def put_note(bucket: Any, note: Note) -> None:
     """Write the note as an OKF Markdown object; an overwrite is fine."""
-    bucket.Object(object_key(note)).put(
+    bucket.Object(_key(note.team_id, note.note_id)).put(
         Body=to_markdown(note).encode("utf-8"), ContentType=CONTENT_TYPE
     )
 
 
+def delete_note(bucket: Any, team_id: str, note_id: str) -> None:
+    """Remove a note's object; a missing key is not an error (D-014)."""
+    bucket.Object(_key(team_id, note_id)).delete()
+
+
 def get_note(bucket: Any, team_id: str, note_id: str) -> OkfNote | None:
     """Read a note back; None if the key does not exist."""
-    key = f"notes/{team_id}/{note_id}.md"
+    key = _key(team_id, note_id)
     try:
         body = bucket.Object(key).get()["Body"].read()
     except ClientError as exc:
diff --git a/src/slackkb/capture.py b/src/slackkb/capture.py
index 96345d8..efa8115 100644
--- a/src/slackkb/capture.py
+++ b/src/slackkb/capture.py
@@ -72,16 +72,27 @@ def handle(
     try:
         body = _raw_body(event)
         verify(headers, body, settings.signing_secret.get_secret_value(), now)
-    except (SignatureError, binascii.Error, UnicodeDecodeError):
+    except SignatureError as exc:
+        logger.warning("capture rejected, reason=%s", exc)
+        return _response(401, "unauthorized", "text/plain")
+    except (binascii.Error, UnicodeDecodeError):
+        logger.warning("capture rejected, reason=bad body encoding")
         return _response(401, "unauthorized", "text/plain")
 
     fields = dict(urllib.parse.parse_qsl(body, keep_blank_values=True))
     try:
         request = CaptureRequest.model_validate(fields)
-    except ValidationError:
+    except ValidationError as exc:
+        invalid = sorted({".".join(str(part) for part in e["loc"]) for e in exc.errors()})
+        logger.warning("capture bad request, invalid_fields=%s", ",".join(invalid))
         return _response(400, "bad request", "text/plain")
 
     if not request.text.strip():
+        logger.info(
+            "empty capture, usage reply sent, team_id=%s user_id=%s",
+            request.team_id,
+            request.user_id,
+        )
         return _ephemeral(USAGE_TEXT)
 
     note = Note(
@@ -92,14 +103,19 @@ def handle(
         text=request.text,
     )
     if not put_if_absent(table, note):
+        logger.info("duplicate capture, note_id=%s", note.note_id)
         return _ack(note.note_id)
     try:
         send_capture_job(sqs, settings.capture_queue_url, CaptureJob(note_id=note.note_id))
     except EnqueueError as exc:
         logger.warning("enqueue failed (%s), note_id=%s", exc, note.note_id)
         try:
-            delete_if_captured(table, note.note_id)
+            deleted = delete_if_captured(table, note.note_id)
         except StoreError as delete_exc:
             logger.warning("note delete failed (%s), note_id=%s", delete_exc, note.note_id)
+        else:
+            if not deleted:
+                logger.warning("note not deleted, not captured or gone, note_id=%s", note.note_id)
         return _ephemeral(RETRY_TEXT)
+    logger.info("note captured, note_id=%s", note.note_id)
     return _ack(note.note_id)
diff --git a/src/slackkb/modal.py b/src/slackkb/modal.py
index 8728839..6d9720b 100644
--- a/src/slackkb/modal.py
+++ b/src/slackkb/modal.py
@@ -87,25 +87,43 @@ def _view(note_id: str, current: Severity) -> dict[str, Any]:
 def _block_actions(payload: Mapping[str, Any], table: Any, slack: SlackClient) -> dict[str, Any]:
     actions = payload.get("actions")
     action = actions[0] if isinstance(actions, list) and actions else None
-    if _get(action, "action_id") != ACTION_ID:
+    action_id = _get(action, "action_id")
+    if action_id != ACTION_ID:
+        logger.warning("block action ignored, wrong action_id=%s", action_id)
         return _empty()
     note_id = _get(action, "value")
     trigger_id = payload.get("trigger_id")
     team_id = _get(payload, "team", "id")
-    if not isinstance(note_id, str) or not isinstance(trigger_id, str) or not note_id:
+    if not isinstance(note_id, str) or not note_id:
+        logger.warning("block action ignored, missing note_id")
+        return _empty()
+    if not isinstance(trigger_id, str):
+        logger.warning("block action ignored, missing trigger_id, note_id=%s", note_id)
         return _empty()
     note = get_note(table, note_id)
-    if note is None or team_id is None or note.team_id != team_id:
+    if note is None:
+        logger.warning("block action ignored, note not found, note_id=%s", note_id)
+        return _empty()
+    if team_id is None or note.team_id != team_id:
+        logger.warning(
+            "block action ignored, team mismatch, note_id=%s note_team_id=%s request_team_id=%s",
+            note_id,
+            note.team_id,
+            team_id,
+        )
         return _empty()
     try:
         slack.views_open(trigger_id, _view(note.note_id, note.severity))
     except SlackApiError as exc:
         logger.warning("views.open failed (%s), note_id=%s", exc, note.note_id)
+        return _empty()
+    logger.info("views.open sent, note_id=%s", note.note_id)
     return _empty()
 
 
 def _view_submission(payload: Mapping[str, Any], table: Any) -> dict[str, Any]:
     if _get(payload, "view", "callback_id") != CALLBACK_ID:
+        logger.warning("modal rejected, reason=wrong callback_id")
         return _response(400, "bad request")
     note_id = _get(payload, "view", "private_metadata")
     value = _get(
@@ -114,17 +132,30 @@ def _view_submission(payload: Mapping[str, Any], table: Any) -> dict[str, Any]:
     try:
         severity = Severity(value)
     except ValueError:
+        logger.warning("submission rejected, invalid severity")
         return _errors(BAD_SEVERITY_TEXT)
     if not isinstance(note_id, str) or not note_id:
+        logger.warning("submission rejected, missing note_id")
         return _errors(NOT_FOUND_TEXT)
     note = get_note(table, note_id)
     team_id = _get(payload, "team", "id")
-    if note is None or team_id is None or note.team_id != team_id:
+    if note is None:
+        logger.warning("submission rejected, note not found, note_id=%s", note_id)
+        return _errors(NOT_FOUND_TEXT)
+    if team_id is None or note.team_id != team_id:
+        logger.warning(
+            "submission rejected, team mismatch, note_id=%s note_team_id=%s request_team_id=%s",
+            note_id,
+            note.team_id,
+            team_id,
+        )
         return _errors(NOT_FOUND_TEXT)
     try:
         set_severity(table, note_id, severity)
     except NoteNotFoundError:
+        logger.warning("submission rejected, note vanished, note_id=%s", note_id)
         return _errors(NOT_FOUND_TEXT)
+    logger.info("severity set, note_id=%s severity=%s", note_id, severity.value)
     return _empty()
 
 
@@ -136,15 +167,24 @@ def handle(
     try:
         body = _raw_body(event)
         verify(headers, body, settings.signing_secret.get_secret_value(), now)
-    except (SignatureError, binascii.Error, UnicodeDecodeError):
+    except SignatureError as exc:
+        logger.warning("modal rejected, reason=%s", exc)
+        return _response(401, "unauthorized")
+    except (binascii.Error, UnicodeDecodeError):
+        logger.warning("modal rejected, reason=bad body encoding")
         return _response(401, "unauthorized")
 
     fields = dict(urllib.parse.parse_qsl(body, keep_blank_values=True))
     try:
         payload = json.loads(fields["payload"])
-    except (KeyError, ValueError):
+    except KeyError:
+        logger.warning("modal rejected, reason=no payload")
+        return _response(400, "bad request")
+    except ValueError:
+        logger.warning("modal rejected, reason=bad payload")
         return _response(400, "bad request")
     if not isinstance(payload, dict):
+        logger.warning("modal rejected, reason=bad payload")
         return _response(400, "bad request")
 
     kind = payload.get("type")
@@ -152,4 +192,5 @@ def handle(
         return _block_actions(payload, table, slack)
     if kind == "view_submission":
         return _view_submission(payload, table)
+    logger.warning("modal rejected, reason=unknown type")
     return _response(400, "bad request")
diff --git a/src/slackkb/okf_note.py b/src/slackkb/okf_note.py
index dc5955f..81576d0 100644
--- a/src/slackkb/okf_note.py
+++ b/src/slackkb/okf_note.py
@@ -66,7 +66,7 @@ def from_markdown(md: str) -> OkfNote:
         head, body = rest[: end + 1], rest[end + 1 + len(DELIMITER) :]
     try:
         data = yaml.safe_load(head)
-    except yaml.YAMLError:
+    except (yaml.YAMLError, ValueError, TypeError):
         raise OkfNoteError("frontmatter is not valid YAML") from None
     if not isinstance(data, dict):
         raise OkfNoteError("frontmatter is not a mapping")
diff --git a/src/slackkb/worker.py b/src/slackkb/worker.py
index 7415849..2b73e04 100644
--- a/src/slackkb/worker.py
+++ b/src/slackkb/worker.py
@@ -11,8 +11,8 @@ from typing import Any
 from botocore.exceptions import BotoCoreError, ClientError
 from pydantic import ValidationError
 
-from slackkb.blob import put_note
-from slackkb.models import CaptureJob, NoteStatus
+from slackkb.blob import delete_note, put_note
+from slackkb.models import CaptureJob, Note, NoteStatus
 from slackkb.store import NoteNotFoundError, get_note, transition_status
 
 logger = logging.getLogger(__name__)
@@ -31,6 +31,9 @@ def _process(record: Mapping[str, Any], table: Any, bucket: Any) -> bool:
         if note is None:
             raise NoteNotFoundError(job.note_id)
         if note.status is NoteStatus.FAILED:
+            logger.info(
+                "note failed, not written, note_id=%s message_id=%s", job.note_id, message_id
+            )
             return True
     except NoteNotFoundError:
         logger.warning("note not found, note_id=%s message_id=%s", job.note_id, message_id)
@@ -54,7 +57,7 @@ def _process(record: Mapping[str, Any], table: Any, bucket: Any) -> bool:
         )
         return False
     try:
-        transition_status(table, job.note_id, NoteStatus.ROUTED)
+        routed = transition_status(table, job.note_id, NoteStatus.ROUTED)
     except NoteNotFoundError:
         logger.warning("note not found, note_id=%s message_id=%s", job.note_id, message_id)
         return False
@@ -66,7 +69,63 @@ def _process(record: Mapping[str, Any], table: Any, bucket: Any) -> bool:
             message_id,
         )
         return False
-    return True
+    if routed:
+        logger.info("note routed, note_id=%s message_id=%s", job.note_id, message_id)
+        return True
+    if note.status is NoteStatus.ROUTED:
+        logger.info(
+            "note already routed, rewritten, note_id=%s message_id=%s", job.note_id, message_id
+        )
+        return True
+    return _resolve_lost_race(table, bucket, note, message_id)
+
+
+def _resolve_lost_race(table: Any, bucket: Any, note: Note, message_id: str) -> bool:
+    """The status changed while the object was being written: settle it from the stored status."""
+    try:
+        current = get_note(table, note.note_id)
+    except (ClientError, BotoCoreError) as exc:
+        logger.warning(
+            "store error %s on re-read, note_id=%s message_id=%s",
+            type(exc).__name__,
+            note.note_id,
+            message_id,
+        )
+        return False
+    if current is None:
+        logger.warning(
+            "note gone after write, note_id=%s message_id=%s", note.note_id, message_id
+        )
+        return False
+    if current.status is NoteStatus.ROUTED:
+        logger.info(
+            "note routed by another delivery, note_id=%s message_id=%s", note.note_id, message_id
+        )
+        return True
+    if current.status is NoteStatus.FAILED:
+        try:
+            delete_note(bucket, note.team_id, note.note_id)
+        except (ClientError, BotoCoreError) as exc:
+            logger.warning(
+                "blob delete error %s, note_id=%s message_id=%s",
+                type(exc).__name__,
+                note.note_id,
+                message_id,
+            )
+            return False
+        logger.warning(
+            "note failed while writing, object removed, note_id=%s message_id=%s",
+            note.note_id,
+            message_id,
+        )
+        return True
+    logger.warning(
+        "note status %s after lost race, note_id=%s message_id=%s",
+        current.status.value,
+        note.note_id,
+        message_id,
+    )
+    return False
 
 
 def handle(event: Mapping[str, Any], *, table: Any, bucket: Any) -> dict:
diff --git a/tests/test_blob.py b/tests/test_blob.py
index 295f30a..ae6c203 100644
--- a/tests/test_blob.py
+++ b/tests/test_blob.py
@@ -35,6 +35,34 @@ def test_get_other_s3_errors_propagate(aws):
         blob.get_note(missing_bucket, "T1", "a" * 32)
 
 
+def test_delete_removes_object(notes_bucket):
+    blob.put_note(notes_bucket, _note())
+    assert blob.delete_note(notes_bucket, "T1", "a" * 32) is None
+    assert blob.get_note(notes_bucket, "T1", "a" * 32) is None
+    assert list(notes_bucket.objects.all()) == []
+
+
+def test_delete_missing_key_is_fine(notes_bucket):
+    assert blob.delete_note(notes_bucket, "T1", "z" * 32) is None
+
+
+def test_delete_other_s3_errors_propagate(aws):
+    import boto3
+
+    missing_bucket = boto3.resource("s3").Bucket("no-such-bucket")
+    with pytest.raises(ClientError):
+        blob.delete_note(missing_bucket, "T1", "a" * 32)
+
+
+def test_put_get_delete_share_one_key_helper(notes_bucket, monkeypatch):
+    monkeypatch.setattr(blob, "_key", lambda team_id, note_id: "elsewhere/x.md")
+    blob.put_note(notes_bucket, _note())
+    assert [o.key for o in notes_bucket.objects.all()] == ["elsewhere/x.md"]
+    assert blob.get_note(notes_bucket, "T1", "a" * 32) is not None
+    blob.delete_note(notes_bucket, "T1", "a" * 32)
+    assert list(notes_bucket.objects.all()) == []
+
+
 def test_put_overwrites(notes_bucket):
     blob.put_note(notes_bucket, _note("first"))
     blob.put_note(notes_bucket, _note("second"))
diff --git a/tests/test_capture.py b/tests/test_capture.py
index 885c622..5d9677c 100644
--- a/tests/test_capture.py
+++ b/tests/test_capture.py
@@ -2,16 +2,19 @@ import ast
 import base64
 import hashlib
 import json
+import logging
 import time
+import urllib.parse
 from pathlib import Path
 
 import boto3
 import pytest
-from conftest import SIGNING_SECRET
+from conftest import BOT_TOKEN, SIGNING_SECRET, sign
 
+from slackkb import capture
 from slackkb.capture import handle
 from slackkb.config import Settings
-from slackkb.store import get_note
+from slackkb.store import StoreError, get_note
 
 CAPTURE_SRC = Path(__file__).parent.parent / "src" / "slackkb" / "capture.py"
 TEAM_ID = "T000TEST"
@@ -139,6 +142,164 @@ def test_ack_is_ephemeral_200(slack_request, notes_table, capture_queue):
     assert isinstance(body["text"], str) and body["text"]
 
 
+NOTE_TEXT = "db connection timeouts on /api/orders since 14:05"
+RESPONSE_URL = "https://hooks.slack.invalid/commands/T000TEST/1/abc"
+SHORT_TEXT = "short note"
+
+
+def _records(caplog, level):
+    return [r for r in caplog.records if r.name == "slackkb.capture" and r.levelno == level]
+
+
+def _only_message(caplog, level):
+    """The module's single log record, which must be at `level`."""
+    records = [r for r in caplog.records if r.name == "slackkb.capture"]
+    assert [r.levelno for r in records] == [level]
+    return records[0].getMessage()
+
+
+def _signed_body(fields):
+    body = urllib.parse.urlencode(fields)
+    ts = int(time.time())
+    return {
+        "headers": {"X-Slack-Request-Timestamp": str(ts), "X-Slack-Signature": sign(body, ts)},
+        "body": body,
+        "isBase64Encoded": False,
+    }
+
+
+def _run(event, table, caplog, sqs=None):
+    sqs = boto3.client("sqs") if sqs is None else sqs
+    # Only our loggers at DEBUG; botocore's DEBUG output echoes request params.
+    with caplog.at_level(logging.DEBUG, logger="slackkb"):
+        return handle(event, table=table, sqs=sqs, settings=Settings(), now=int(time.time()))
+
+
+def _bad_base64(slack_request):
+    event = slack_request()
+    event["body"] = "!!not base64!!"
+    event["isBase64Encoded"] = True
+    return event
+
+
+def _bad_utf8(slack_request):
+    event = slack_request()
+    event["body"] = base64.b64encode(b"\xff\xfe").decode()
+    event["isBase64Encoded"] = True
+    return event
+
+
+@pytest.mark.parametrize(
+    ("make", "reason"),
+    [
+        (lambda r: r(secret="wrong"), "signature mismatch"),
+        (lambda r: r(drop=("X-Slack-Signature",)), "missing signature header"),
+        (lambda r: r(drop=("X-Slack-Request-Timestamp",)), "missing timestamp header"),
+        (lambda r: r(ts=1), "timestamp outside allowed window"),
+        (_bad_base64, "bad body encoding"),
+        (_bad_utf8, "bad body encoding"),
+    ],
+)
+def test_logs_401_reason(slack_request, notes_table, capture_queue, caplog, make, reason):
+    resp = _run(make(slack_request), notes_table, caplog)
+    assert resp["statusCode"] == 401
+    msg = _only_message(caplog, logging.WARNING)
+    assert "capture rejected" in msg and reason in msg
+
+
+@pytest.mark.parametrize(
+    ("drop", "names"),
+    [(("team_id",), {"team_id"}), (("trigger_id", "user_id"), {"trigger_id", "user_id"})],
+)
+def test_logs_400_field_names_only(notes_table, capture_queue, caplog, drop, names):
+    fields = json.loads((Path(__file__).parent / "fixtures" / "slash_bnote.json").read_text())
+    for name in drop:
+        del fields[name]
+    resp = _run(_signed_body(fields), notes_table, caplog)
+    assert resp["statusCode"] == 400
+    msg = _only_message(caplog, logging.WARNING)
+    assert all(name in msg for name in names)
+    for value in (NOTE_TEXT, "C000TEST", "U000TEST", TEAM_ID, TRIGGER_ID):
+        assert value not in msg
+
+
+@pytest.mark.parametrize(
+    ("path", "expected"),
+    [
+        ("empty_text", ("usage", TEAM_ID, "U000TEST")),
+        ("captured", ("note captured", EXPECTED_NOTE_ID)),
+        ("duplicate", ("duplicate capture", EXPECTED_NOTE_ID)),
+    ],
+    ids=lambda v: v if isinstance(v, str) else "",
+)
+def test_logs_accepted_paths(slack_request, notes_table, capture_queue, caplog, path, expected):
+    if path == "duplicate":
+        _run(slack_request(), notes_table, caplog)
+        caplog.clear()
+    event = slack_request(text="  ") if path == "empty_text" else slack_request()
+    assert _run(event, notes_table, caplog)["statusCode"] == 200
+    msg = _only_message(caplog, logging.INFO)
+    assert all(value in msg for value in expected)
+
+
+def test_logs_note_not_deleted_after_failed_enqueue(
+    slack_request, notes_table, capture_queue, caplog, monkeypatch
+):
+    monkeypatch.setattr(capture, "delete_if_captured", lambda table, note_id: False)
+    sqs = boto3.client("sqs")
+    sqs.delete_queue(QueueUrl=capture_queue.url)
+    resp = _run(slack_request(), notes_table, caplog, sqs=sqs)
+    assert json.loads(resp["body"])["text"] == capture.RETRY_TEXT
+    msgs = [r.getMessage() for r in _records(caplog, logging.WARNING)]
+    matching = [m for m in msgs if "note not deleted, not captured or gone" in m]
+    assert len(matching) == 1 and EXPECTED_NOTE_ID in matching[0]
+
+
+def _with_trigger(slack_request, trigger_id):
+    event = slack_request()
+    event["body"] = event["body"].replace(TRIGGER_ID, trigger_id)
+    event["headers"]["X-Slack-Signature"] = sign(
+        event["body"], int(event["headers"]["X-Slack-Request-Timestamp"])
+    )
+    return event
+
+
+def test_logs_never_contain_secrets(slack_request, notes_table, capture_queue, caplog, monkeypatch):
+    events = [
+        slack_request(),
+        slack_request(retry=1),
+        slack_request(text=" "),
+        slack_request(secret="wrong"),
+        _bad_base64(slack_request),
+        # Short, because pydantic truncates long input values in its error messages.
+        _signed_body({"text": SHORT_TEXT}),
+    ]
+    for event in events:
+        _run(event, notes_table, caplog)
+    sqs = boto3.client("sqs")
+    sqs.delete_queue(QueueUrl=capture_queue.url)
+
+    def boom(table, note_id):
+        raise StoreError("ClientError")
+
+    failed_enqueues = [
+        (None, _with_trigger(slack_request, "9999.0001.a")),
+        (lambda table, note_id: False, _with_trigger(slack_request, "9999.0002.b")),
+        (boom, _with_trigger(slack_request, "9999.0003.c")),
+    ]
+    for delete, event in failed_enqueues:
+        if delete is not None:
+            monkeypatch.setattr(capture, "delete_if_captured", delete)
+        _run(event, notes_table, caplog, sqs=sqs)
+        events.append(event)
+    assert caplog.text
+    for value in (NOTE_TEXT, SHORT_TEXT, SIGNING_SECRET, BOT_TOKEN, RESPONSE_URL, "response_url"):
+        assert value not in caplog.text
+    for event in events:
+        assert event["body"] not in caplog.text
+        assert event["headers"]["X-Slack-Signature"] not in caplog.text
+
+
 def _imported_modules(tree):
     for node in ast.walk(tree):
         if isinstance(node, ast.Import):
diff --git a/tests/test_modal.py b/tests/test_modal.py
index 30238a5..c0d3974 100644
--- a/tests/test_modal.py
+++ b/tests/test_modal.py
@@ -1,19 +1,21 @@
 import ast
+import base64
 import json
 import logging
 import time
+import urllib.parse
 from pathlib import Path
 
 import boto3
 import pytest
-from conftest import BOT_TOKEN, SIGNING_SECRET
+from conftest import BOT_TOKEN, SIGNING_SECRET, sign
 from pydantic import SecretStr
 
 from slackkb import capture, modal
 from slackkb.config import Settings
 from slackkb.models import Note, NoteStatus, Severity, note_id
 from slackkb.slack_api import SlackApiError, SlackClient
-from slackkb.store import get_note, put_if_absent
+from slackkb.store import NoteNotFoundError, get_note, put_if_absent
 
 SRC = Path(__file__).parent.parent / "src" / "slackkb"
 NOTE_ID = note_id("T000TEST", "1111.2222.abcdef")
@@ -314,6 +316,263 @@ def test_slack_client_raises_on_failure():
     assert BOT_TOKEN not in repr(client)
 
 
+FIXTURES = Path(__file__).parent / "fixtures"
+RESPONSE_URL = "https://hooks.slack.invalid/actions/T000TEST/2/def"
+
+
+def _payload(kind, **over):
+    payload = json.loads((FIXTURES / f"{kind}.json").read_text())
+    payload.update(over)
+    return payload
+
+
+def _event(payload):
+    return _signed(urllib.parse.urlencode({"payload": json.dumps(payload)}))
+
+
+def _only_message(caplog, level):
+    """The module's single log record, which must be at `level`."""
+    records = [r for r in caplog.records if r.name == "slackkb.modal"]
+    assert [r.levelno for r in records] == [level]
+    return records[0].getMessage()
+
+
+def _run(event, table, caplog, transport=None):
+    # Only our loggers at DEBUG; botocore's DEBUG output echoes request params.
+    with caplog.at_level(logging.DEBUG, logger="slackkb"):
+        return _handle(event, table, transport)
+
+
+def _drop_action_key(key):
+    payload = _payload("block_actions")
+    del payload["actions"][0][key]
+    return payload
+
+
+def _drop_key(kind, key):
+    payload = _payload(kind)
+    del payload[key]
+    return payload
+
+
+def _other_action():
+    payload = _payload("block_actions")
+    payload["actions"][0]["action_id"] = "something_else"
+    return payload
+
+
+def _other_callback():
+    payload = _payload("view_submission")
+    payload["view"]["callback_id"] = "other_modal"
+    return payload
+
+
+def _severity(value):
+    payload = _payload("view_submission")
+    select = payload["view"]["state"]["values"]["severity"]["severity_select"]
+    select["selected_option"]["value"] = value
+    return payload
+
+
+def _no_metadata():
+    payload = _payload("view_submission")
+    del payload["view"]["private_metadata"]
+    return payload
+
+
+def _metadata(note_id):
+    payload = _payload("view_submission")
+    payload["view"]["private_metadata"] = note_id
+    return payload
+
+
+def _action_value(note_id):
+    payload = _payload("block_actions")
+    payload["actions"][0]["value"] = note_id
+    return payload
+
+
+def _team(kind, team_id):
+    payload = _payload(kind, team={"id": team_id})
+    return payload
+
+
+@pytest.mark.parametrize(
+    ("make", "reason"),
+    [
+        (lambda: _signed_with(secret="wrong"), "signature mismatch"),
+        (lambda: _signed_with(ts=1), "timestamp outside allowed window"),
+        (lambda: _signed_with(drop="X-Slack-Signature"), "missing signature header"),
+        (lambda: _signed_with(drop="X-Slack-Request-Timestamp"), "missing timestamp header"),
+        (lambda: _signed_with(b64="!!not base64!!"), "bad body encoding"),
+        (
+            lambda: _signed_with(b64=base64.b64encode(b"\xff\xfe").decode()),
+            "bad body encoding",
+        ),
+    ],
+)
+def test_logs_401_reason(notes_table, caplog, make, reason):
+    resp = _run(make(), notes_table, caplog)
+    assert resp["statusCode"] == 401
+    msg = _only_message(caplog, logging.WARNING)
+    assert "rejected" in msg and reason in msg
+
+
+def _signed_with(secret=SIGNING_SECRET, ts=None, drop=None, b64=None):
+    body = urllib.parse.urlencode({"payload": json.dumps(_payload("block_actions"))})
+    ts = int(time.time()) if ts is None else ts
+    headers = {"X-Slack-Request-Timestamp": str(ts), "X-Slack-Signature": sign(body, ts, secret)}
+    if drop:
+        headers.pop(drop)
+    if b64 is not None:
+        return {"headers": headers, "body": b64, "isBase64Encoded": True}
+    return {"headers": headers, "body": body, "isBase64Encoded": False}
+
+
+@pytest.mark.parametrize(
+    ("event", "reason"),
+    [
+        (lambda: _signed("foo=bar"), "no payload"),
+        (lambda: _signed("payload=not-json"), "bad payload"),
+        (lambda: _signed("payload=%5B1%5D"), "bad payload"),
+        (lambda: _event({"type": "shortcut"}), "unknown type"),
+        (lambda: _event({}), "unknown type"),
+        (lambda: _event(_other_callback()), "wrong callback_id"),
+    ],
+)
+def test_logs_400_reason(notes_table, caplog, event, reason):
+    resp = _run(event(), notes_table, caplog)
+    assert resp["statusCode"] == 400
+    assert reason in _only_message(caplog, logging.WARNING)
+
+
+MISSING_NOTE_ID = "c" * 32
+
+
+@pytest.mark.parametrize(
+    ("payload", "expected"),
+    [
+        (_other_action, ["action_id", "something_else"]),
+        (lambda: _drop_action_key("value"), ["missing note_id"]),
+        (lambda: _drop_key("block_actions", "trigger_id"), ["missing trigger_id", NOTE_ID]),
+        (lambda: _action_value(MISSING_NOTE_ID), ["not found", MISSING_NOTE_ID]),
+        (
+            lambda: _team("block_actions", "T999OTHER"),
+            ["mismatch", NOTE_ID, "T999OTHER", "T000TEST"],
+        ),
+    ],
+    ids=["action_id", "no_note_id", "no_trigger_id", "note_missing", "team_mismatch"],
+)
+def test_logs_block_actions_rejections(
+    slack_request, notes_table, capture_queue, caplog, payload, expected
+):
+    _capture(slack_request, notes_table)
+    transport = FakeTransport()
+    resp = _run(_event(payload()), notes_table, caplog, transport)
+    assert resp == {"statusCode": 200, "headers": {"Content-Type": "text/plain"}, "body": ""}
+    assert transport.calls == []
+    msg = _only_message(caplog, logging.WARNING)
+    assert all(e in msg for e in expected)
+
+
+@pytest.mark.parametrize(
+    ("payload", "expected"),
+    [
+        (lambda: _severity("URGENT"), ["invalid severity"]),
+        (lambda: _severity(""), ["invalid severity"]),
+        (_no_metadata, ["missing note_id"]),
+        (lambda: _metadata(MISSING_NOTE_ID), ["not found", MISSING_NOTE_ID]),
+        (lambda: _team("view_submission", "T999OTHER"), ["mismatch", NOTE_ID, "T999OTHER"]),
+    ],
+    ids=["bad_severity", "empty_severity", "no_note_id", "note_missing", "team_mismatch"],
+)
+def test_logs_view_submission_rejections(
+    slack_request, notes_table, capture_queue, caplog, payload, expected
+):
+    _capture(slack_request, notes_table)
+    resp = _run(_event(payload()), notes_table, caplog)
+    _errors(resp)
+    msg = _only_message(caplog, logging.WARNING)
+    assert all(e in msg for e in expected)
+    assert "URGENT" not in msg and "HIGH" not in msg
+    assert get_note(notes_table, NOTE_ID).severity is Severity.LOW
+
+
+def test_logs_view_submission_set_severity_not_found(
+    slack_request, notes_table, capture_queue, caplog, monkeypatch
+):
+    def gone(table, nid, severity):
+        raise NoteNotFoundError(nid)
+
+    _capture(slack_request, notes_table)
+    monkeypatch.setattr(modal, "set_severity", gone)
+    _errors(_run(_event(_payload("view_submission")), notes_table, caplog))
+    msg = _only_message(caplog, logging.WARNING)
+    assert NOTE_ID in msg and "HIGH" not in msg
+
+
+@pytest.mark.parametrize(
+    ("payload", "expected", "views_open_calls"),
+    [
+        (lambda: _payload("block_actions"), ["views.open sent", NOTE_ID], 1),
+        (lambda: _severity("CRITICAL"), ["severity set", NOTE_ID, "CRITICAL"], 0),
+    ],
+    ids=["views_open_sent", "severity_set"],
+)
+def test_logs_success(
+    slack_request, notes_table, capture_queue, caplog, payload, expected, views_open_calls
+):
+    _capture(slack_request, notes_table)
+    transport = FakeTransport()
+    _run(_event(payload()), notes_table, caplog, transport)
+    assert len(transport.calls) == views_open_calls
+    msg = _only_message(caplog, logging.INFO)
+    assert all(e in msg for e in expected)
+
+
+def test_logs_never_contain_secrets(
+    slack_request, notes_table, capture_queue, caplog, monkeypatch
+):
+    _capture(slack_request, notes_table)
+    nid = _put_other_team_note(notes_table)
+    events = [
+        _event(_payload("block_actions")),
+        _event(_other_action()),
+        _event(_drop_action_key("value")),
+        _event(_drop_key("block_actions", "trigger_id")),
+        _event(_action_value(MISSING_NOTE_ID)),
+        _event(_action_value(nid)),
+        _event(_severity("CRITICAL")),
+        _event(_severity("URGENT")),
+        _event(_no_metadata()),
+        _event(_metadata(MISSING_NOTE_ID)),
+        _event(_other_callback()),
+        _event(_team("view_submission", "T999OTHER")),
+        _event({"type": "shortcut"}),
+        _signed_with(secret="wrong"),
+        _signed_with(b64="!!not base64!!"),
+        _signed("foo=bar"),
+        _signed("payload=not-json"),
+    ]
+    for event in events:
+        _run(event, notes_table, caplog)
+        _run(event, notes_table, caplog, FakeTransport(reply={"ok": False, "error": "bad"}))
+
+    def gone(table, note_id, severity):
+        raise NoteNotFoundError(note_id)
+
+    monkeypatch.setattr(modal, "set_severity", gone)
+    _run(_event(_payload("view_submission")), notes_table, caplog)
+    assert caplog.text
+    for value in (NOTE_TEXT, SIGNING_SECRET, BOT_TOKEN, RESPONSE_URL, "response_url", "URGENT"):
+        assert value not in caplog.text
+    for event in events:
+        assert event["body"] not in caplog.text
+        assert event["headers"]["X-Slack-Signature"] not in caplog.text
+        for raw in urllib.parse.parse_qs(event["body"]).get("payload", []):
+            assert raw not in caplog.text
+
+
 def _imported_modules(tree):
     for node in ast.walk(tree):
         if isinstance(node, ast.Import):
diff --git a/tests/test_okf_note.py b/tests/test_okf_note.py
index 61eaaf9..29267f6 100644
--- a/tests/test_okf_note.py
+++ b/tests/test_okf_note.py
@@ -118,6 +118,19 @@ def test_malformed_markdown_raises(md, reason):
         from_markdown(md)
 
 
+@pytest.mark.parametrize(
+    "line",
+    ["created_at: 2026-13-45", "note_id: 0x_"],
+)
+def test_yaml_value_errors_become_okf_note_error(line):
+    key = line.split(":")[0]
+    head = "".join(
+        (line if row.startswith(key + ":") else row) + "\n" for row in VALID_HEAD.splitlines()
+    )
+    with pytest.raises(OkfNoteError):
+        from_markdown("---\n" + head + "---\nbody")
+
+
 def test_okf_note_error_is_value_error():
     assert issubclass(OkfNoteError, ValueError)
 
diff --git a/tests/test_worker.py b/tests/test_worker.py
index 837a397..393d411 100644
--- a/tests/test_worker.py
+++ b/tests/test_worker.py
@@ -8,7 +8,7 @@ from pathlib import Path
 import boto3
 import pytest
 from botocore.exceptions import ClientError, EndpointConnectionError
-from conftest import SIGNING_SECRET
+from conftest import BOT_TOKEN, SIGNING_SECRET, sign
 
 from slackkb import blob, capture, worker
 from slackkb.config import Settings
@@ -308,6 +308,251 @@ def test_worker_redelivery_rewrites_routed_note(notes_table, notes_bucket):
     assert get_note(notes_table, note_id).status is NoteStatus.ROUTED
 
 
+def _worker_records(caplog, level):
+    return [
+        r for r in caplog.records if r.name == "slackkb.worker" and r.levelno == level
+    ]
+
+
+def _run(notes_table, bucket, caplog, note_id="a" * 32, message_id="m1"):
+    with caplog.at_level(logging.DEBUG, logger="slackkb"):
+        return worker.handle(_event(note_id, message_id), table=notes_table, bucket=bucket)
+
+
+def test_worker_logs_failed_note_not_written(notes_table, notes_bucket, caplog):
+    _put(notes_table, "a" * 32, status=NoteStatus.FAILED)
+    assert _run(notes_table, notes_bucket, caplog) == {"batchItemFailures": []}
+    (rec,) = _worker_records(caplog, logging.INFO)
+    msg = rec.getMessage()
+    assert "note failed, not written" in msg and "a" * 32 in msg and "m1" in msg
+    assert _worker_records(caplog, logging.WARNING) == []
+    assert _keys(notes_bucket) == []
+
+
+def test_worker_logs_note_routed(notes_table, notes_bucket, caplog):
+    _put(notes_table, "a" * 32)
+    assert _run(notes_table, notes_bucket, caplog) == {"batchItemFailures": []}
+    (rec,) = _worker_records(caplog, logging.INFO)
+    msg = rec.getMessage()
+    assert "note routed" in msg and "a" * 32 in msg and "m1" in msg
+    assert _worker_records(caplog, logging.WARNING) == []
+
+
+def test_worker_logs_redelivery_rewritten(notes_table, notes_bucket, caplog):
+    _put(notes_table, "a" * 32, status=NoteStatus.ROUTED)
+    assert _run(notes_table, notes_bucket, caplog) == {"batchItemFailures": []}
+    (rec,) = _worker_records(caplog, logging.INFO)
+    msg = rec.getMessage()
+    assert "note already routed, rewritten" in msg and "a" * 32 in msg and "m1" in msg
+    assert _worker_records(caplog, logging.WARNING) == []
+    assert _keys(notes_bucket) == [f"notes/{TEAM_ID}/{'a' * 32}.md"]
+
+
+class _RaceTable:
+    """Passes through to a real table, but flips the status just before the first update."""
+
+    def __init__(self, table, new_status):
+        self.table = table
+        self.new_status = new_status
+
+    def update_item(self, **kwargs):
+        if self.new_status is not None:
+            self.table.update_item(
+                Key=kwargs["Key"],
+                UpdateExpression="SET #status = :s",
+                ExpressionAttributeNames={"#status": "status"},
+                ExpressionAttributeValues={":s": self.new_status.value},
+            )
+            self.new_status = None
+        return self.table.update_item(**kwargs)
+
+    def __getattr__(self, name):
+        return getattr(self.table, name)
+
+
+def test_worker_lost_race_to_routed_keeps_object(notes_table, notes_bucket, caplog):
+    note_id = "a" * 32
+    _put(notes_table, note_id)
+    table = _RaceTable(notes_table, NoteStatus.ROUTED)
+    assert _run(table, notes_bucket, caplog) == {"batchItemFailures": []}
+    assert _keys(notes_bucket) == [f"notes/{TEAM_ID}/{note_id}.md"]
+    (rec,) = _worker_records(caplog, logging.INFO)
+    assert note_id in rec.getMessage() and "m1" in rec.getMessage()
+    assert _worker_records(caplog, logging.WARNING) == []
+
+
+def test_worker_lost_race_to_failed_removes_object(notes_table, notes_bucket, caplog):
+    note_id = "a" * 32
+    _put(notes_table, note_id)
+    table = _RaceTable(notes_table, NoteStatus.FAILED)
+    assert _run(table, notes_bucket, caplog) == {"batchItemFailures": []}
+    assert _keys(notes_bucket) == []
+    assert get_note(notes_table, note_id).status is NoteStatus.FAILED
+    (rec,) = _worker_records(caplog, logging.WARNING)
+    msg = rec.getMessage()
+    assert note_id in msg and "m1" in msg and "removed" in msg
+
+
+class _DeleteFailingBucket:
+    def __init__(self, bucket, exc):
+        self.bucket = bucket
+        self.exc = exc
+
+    def Object(self, key):  # noqa: N802 - boto3 resource API
+        obj = self.bucket.Object(key)
+        exc = self.exc
+
+        class _Obj:
+            def put(self, **kwargs):
+                return obj.put(**kwargs)
+
+            def delete(self, **kwargs):
+                raise exc
+
+        return _Obj()
+
+
+@pytest.mark.parametrize("kind", ["client_error", "botocore_error"])
+def test_worker_lost_race_to_failed_delete_failure_retries(
+    notes_table, notes_bucket, caplog, kind
+):
+    note_id = "a" * 32
+    _put(notes_table, note_id)
+    if kind == "client_error":
+        exc = ClientError({"Error": {"Code": "AccessDenied"}}, "DeleteObject")
+    else:
+        exc = EndpointConnectionError(endpoint_url="https://s3.invalid")
+    table = _RaceTable(notes_table, NoteStatus.FAILED)
+    resp = _run(table, _DeleteFailingBucket(notes_bucket, exc), caplog, message_id="m-del")
+    assert _failures(resp) == ["m-del"]
+    assert _keys(notes_bucket) == [f"notes/{TEAM_ID}/{note_id}.md"]
+    (rec,) = _worker_records(caplog, logging.WARNING)
+    msg = rec.getMessage()
+    assert type(exc).__name__ in msg and note_id in msg and "m-del" in msg
+
+
+def _lost_race(monkeypatch, second):
+    """transition_status reports a lost race; the re-read returns `second` (or raises it)."""
+    real = worker.get_note
+    calls = []
+
+    def fake_get(table, note_id):
+        calls.append(note_id)
+        if len(calls) == 1:
+            return real(table, note_id)
+        if isinstance(second, Exception):
+            raise second
+        return second
+
+    monkeypatch.setattr(worker, "get_note", fake_get)
+    monkeypatch.setattr(worker, "transition_status", lambda table, note_id, to: False)
+
+
+@pytest.mark.parametrize(
+    "second",
+    [
+        None,
+        EndpointConnectionError(endpoint_url="https://dynamodb.invalid"),
+        ClientError({"Error": {"Code": "Throttled"}}, "GetItem"),
+    ],
+    ids=["gone", "botocore_error", "client_error"],
+)
+def test_worker_lost_race_reread_unusable_is_batch_failure(
+    notes_table, notes_bucket, caplog, monkeypatch, second
+):
+    note_id = "a" * 32
+    _put(notes_table, note_id)
+    _lost_race(monkeypatch, second)
+    resp = _run(notes_table, notes_bucket, caplog, message_id="m-re")
+    assert _failures(resp) == ["m-re"]
+    (rec,) = _worker_records(caplog, logging.WARNING)
+    assert note_id in rec.getMessage() and "m-re" in rec.getMessage()
+
+
+def test_worker_lost_race_still_captured_is_batch_failure(
+    notes_table, notes_bucket, caplog, monkeypatch
+):
+    note_id = "a" * 32
+    _put(notes_table, note_id)
+    still_captured = Note(note_id=note_id, team_id=TEAM_ID, channel_id="C1", user_id="U1", text="t")
+    _lost_race(monkeypatch, still_captured)
+    resp = _run(notes_table, notes_bucket, caplog, message_id="m-cap")
+    assert _failures(resp) == ["m-cap"]
+    (rec,) = _worker_records(caplog, logging.WARNING)
+    assert note_id in rec.getMessage()
+
+
+def test_worker_logs_never_contain_secrets(notes_table, notes_bucket, caplog, monkeypatch):
+    signature = sign(NOTE_TEXT, 1)
+    raw_body = json.dumps(
+        {
+            "text": NOTE_TEXT,
+            "signing_secret": SIGNING_SECRET,
+            "bot_token": BOT_TOKEN,
+            "signature": signature,
+            "response_url": RESPONSE_URL,
+        }
+    )
+    # str(ClientError) carries the service's message, so logging the exception would leak these.
+    leaky = ClientError(
+        {"Error": {"Code": "AccessDenied", "Message": f"{NOTE_TEXT} {RESPONSE_URL}"}}, "Op"
+    )
+
+    def raises(*args, **kwargs):
+        raise leaky
+
+    def put(fill, status=NoteStatus.CAPTURED):
+        note_id = fill * 32
+        note = Note(
+            note_id=note_id,
+            team_id=TEAM_ID,
+            channel_id="C1",
+            user_id="U1",
+            text=NOTE_TEXT,
+            status=status,
+        )
+        assert put_if_absent(notes_table, note)
+        return note_id
+
+    delete_fails = _DeleteFailingBucket(notes_bucket, leaky)
+    seen = []
+
+    def run(note_id, table=notes_table, bucket=notes_bucket):
+        seen.append(note_id)
+        _run(table, bucket, caplog, note_id=note_id, message_id=f"m-{note_id[0]}")
+
+    with caplog.at_level(logging.DEBUG, logger="slackkb"):
+        worker.handle(
+            {"Records": [_record("m-bad", raw_body)]}, table=notes_table, bucket=notes_bucket
+        )
+    run(put("0"))
+    run(put("1", NoteStatus.FAILED))
+    run(put("2", NoteStatus.ROUTED))
+    run("3" * 32)
+    run(put("4"), bucket=_RaisingBucket(leaky))
+    run(put("5"), table=_RaceTable(notes_table, NoteStatus.ROUTED))
+    run(put("6"), table=_RaceTable(notes_table, NoteStatus.FAILED))
+    run(put("7"), table=_RaceTable(notes_table, NoteStatus.FAILED), bucket=delete_fails)
+    with monkeypatch.context() as m:
+        m.setattr(worker, "get_note", raises)
+        run(put("8"))
+    with monkeypatch.context() as m:
+        m.setattr(worker, "transition_status", raises)
+        run(put("9"))
+    with monkeypatch.context() as m:
+        _lost_race(m, None)
+        run(put("a"))
+    with monkeypatch.context() as m:
+        _lost_race(m, leaky)
+        run(put("b"))
+
+    assert "m-bad" in caplog.text
+    assert all(note_id in caplog.text for note_id in seen)
+    for value in (NOTE_TEXT, SIGNING_SECRET, BOT_TOKEN, signature, RESPONSE_URL, raw_body):
+        assert value not in caplog.text
+    assert "response_url" not in caplog.text
+
+
 def _imported_modules(tree):
     for node in ast.walk(tree):
         if isinstance(node, ast.Import):

review FLAG: The source follows the spec on every path I traced, and the checks are green. One major gap: no test can fail for the TypeError half of requirement 1. Minor notes: an unspecified return value on the still-CAPTURED re-read, a duplicated key format, and two spec-level issues for a human, including that the 3d delete retry never actually retries the delete.
  [major] tests/test_okf_note.py: Requirement 1 says any ValueError or TypeError raised while loading the frontmatter becomes OkfNoteError, and the spec says every requirement has a test that fails if it is broken. test_yaml_value_errors_become_okf_note_error only drives the two ValueError inputs (`created_at: 2026-13-45`, `note_id: 0x_`). Removing TypeError from `except (yaml.YAMLError, ValueError, TypeError)` in from_markdown would leave every test green. Add a case that monkeypatches yaml.safe_load (as seen by okf_note) to raise TypeError and asserts pytest.raises(OkfNoteError).
  [minor] src/slackkb/worker.py: spec: 3d makes a failed delete a batch failure 'so SQS retries', but 3a makes the retry a no-op. On redelivery the note is FAILED at read, so _process logs INFO 'note failed, not written' and returns True without calling delete_note. The object stays in S3 for a FAILED note, the D-014 rule the spec cites (FAILED -> no S3 object), and the log line implies no object exists. The same orphan occurs if the note goes FAILED after the put and transition_status then raises a store error. The code does what 3a and 3d each require, and no test covers the redelivery after a failed delete. A human should decide whether the FAILED-at-read path should also delete the object idempotently.
  [minor] src/slackkb/worker.py: In _resolve_lost_race, a re-read that still shows CAPTURED logs a WARNING and returns False. 3d does not list this state, and requirements 3 and 7 say return values stay as now unless stated; previously a False transition returned True. Retrying is the safer choice, for example if the re-read is stale, and c1 and a test both state the behaviour openly, so this is not a defect to block on. It is still an unspecified change to a worker return value and should be confirmed.
  [minor] src/slackkb/blob.py: blob._key now hardcodes `notes/{team_id}/{note_id}.md` and blob no longer imports okf_note.object_key, so the D-014 key format is written in two modules. The spec's requirement that object_key keeps its signature and result is met, but nothing in this diff ties the two together, so they could drift apart. A one-line test asserting blob._key(n.team_id, n.note_id) == object_key(n) would pin them.
  [minor] src/slackkb/okf_note.py: spec: requirement 1 names only ValueError and TypeError, so the change meets it, but from reading PyYAML's constructors, explicitly tagged scalars raise other exception types from safe_load. `note_id: !!int ""` should raise IndexError, `x: !!bool foo` KeyError and `created_at: !!timestamp foo` AttributeError. These would escape from_markdown as non-OkfNoteError exceptions, despite the goal of treating them 'like other bad YAML'. I did not run these inputs. A human may want to widen the requirement.
merge prama/personal_45be297d into the current branch of /home/vajrasarpa/Projects/slack-kb? [y/N]: merged as 010c68b2db3c. Nothing was pushed.
