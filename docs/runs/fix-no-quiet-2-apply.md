diff --git a/src/slackkb/blob.py b/src/slackkb/blob.py
index 4c956d3..313cd0f 100644
--- a/src/slackkb/blob.py
+++ b/src/slackkb/blob.py
@@ -6,15 +6,12 @@ from botocore.exceptions import ClientError
 
 from slackkb.models import Note
 from slackkb.okf_note import OkfNote, from_markdown, to_markdown
+from slackkb.okf_note import key_for as _key
 
 CONTENT_TYPE = "text/markdown; charset=utf-8"
 _MISSING = {"NoSuchKey", "404", "NotFound"}
 
 
-def _key(team_id: str, note_id: str) -> str:
-    return f"notes/{team_id}/{note_id}.md"
-
-
 def put_note(bucket: Any, note: Note) -> None:
     """Write the note as an OKF Markdown object; an overwrite is fine."""
     bucket.Object(_key(note.team_id, note.note_id)).put(
diff --git a/src/slackkb/okf_note.py b/src/slackkb/okf_note.py
index 81576d0..f805bb2 100644
--- a/src/slackkb/okf_note.py
+++ b/src/slackkb/okf_note.py
@@ -29,7 +29,7 @@ class OkfNote(BaseModel):
 
 
 class _Frontmatter(BaseModel):
-    model_config = ConfigDict(extra="forbid")
+    model_config = ConfigDict(extra="forbid", strict=True)
 
     note_id: str
     team_id: str
@@ -38,8 +38,12 @@ class _Frontmatter(BaseModel):
     created_at: str
 
 
+def key_for(team_id: str, note_id: str) -> str:
+    return f"notes/{team_id}/{note_id}.md"
+
+
 def object_key(note: Note | OkfNote) -> str:
-    return f"notes/{note.team_id}/{note.note_id}.md"
+    return key_for(note.team_id, note.note_id)
 
 
 def to_markdown(note: Note) -> str:
@@ -66,7 +70,7 @@ def from_markdown(md: str) -> OkfNote:
         head, body = rest[: end + 1], rest[end + 1 + len(DELIMITER) :]
     try:
         data = yaml.safe_load(head)
-    except (yaml.YAMLError, ValueError, TypeError):
+    except Exception:
         raise OkfNoteError("frontmatter is not valid YAML") from None
     if not isinstance(data, dict):
         raise OkfNoteError("frontmatter is not a mapping")
diff --git a/src/slackkb/worker.py b/src/slackkb/worker.py
index 2b73e04..8308c7b 100644
--- a/src/slackkb/worker.py
+++ b/src/slackkb/worker.py
@@ -18,6 +18,21 @@ from slackkb.store import NoteNotFoundError, get_note, transition_status
 logger = logging.getLogger(__name__)
 
 
+def _remove_object(bucket: Any, note: Note, message_id: str) -> bool:
+    """A FAILED note has no S3 object (D-014). False if the delete failed, so SQS retries."""
+    try:
+        delete_note(bucket, note.team_id, note.note_id)
+    except (ClientError, BotoCoreError) as exc:
+        logger.warning(
+            "blob delete error %s, note_id=%s message_id=%s",
+            type(exc).__name__,
+            note.note_id,
+            message_id,
+        )
+        return False
+    return True
+
+
 def _process(record: Mapping[str, Any], table: Any, bucket: Any) -> bool:
     """Write one record's note to S3, then route it. True on success, including a FAILED note."""
     message_id = record["messageId"]
@@ -30,11 +45,6 @@ def _process(record: Mapping[str, Any], table: Any, bucket: Any) -> bool:
         note = get_note(table, job.note_id)
         if note is None:
             raise NoteNotFoundError(job.note_id)
-        if note.status is NoteStatus.FAILED:
-            logger.info(
-                "note failed, not written, note_id=%s message_id=%s", job.note_id, message_id
-            )
-            return True
     except NoteNotFoundError:
         logger.warning("note not found, note_id=%s message_id=%s", job.note_id, message_id)
         return False
@@ -46,6 +56,11 @@ def _process(record: Mapping[str, Any], table: Any, bucket: Any) -> bool:
             message_id,
         )
         return False
+    if note.status is NoteStatus.FAILED:
+        if not _remove_object(bucket, note, message_id):
+            return False
+        logger.info("note failed, no object, note_id=%s message_id=%s", note.note_id, message_id)
+        return True
     try:
         put_note(bucket, note)
     except (ClientError, BotoCoreError) as exc:
@@ -103,15 +118,7 @@ def _resolve_lost_race(table: Any, bucket: Any, note: Note, message_id: str) ->
         )
         return True
     if current.status is NoteStatus.FAILED:
-        try:
-            delete_note(bucket, note.team_id, note.note_id)
-        except (ClientError, BotoCoreError) as exc:
-            logger.warning(
-                "blob delete error %s, note_id=%s message_id=%s",
-                type(exc).__name__,
-                note.note_id,
-                message_id,
-            )
+        if not _remove_object(bucket, note, message_id):
             return False
         logger.warning(
             "note failed while writing, object removed, note_id=%s message_id=%s",
diff --git a/tests/test_blob.py b/tests/test_blob.py
index ae6c203..4c1f3a2 100644
--- a/tests/test_blob.py
+++ b/tests/test_blob.py
@@ -63,6 +63,12 @@ def test_put_get_delete_share_one_key_helper(notes_bucket, monkeypatch):
     assert list(notes_bucket.objects.all()) == []
 
 
+def test_blob_keys_come_from_okf_note_key_for(notes_bucket):
+    n = _note()
+    blob.put_note(notes_bucket, n)
+    assert [o.key for o in notes_bucket.objects.all()] == [object_key(n)]
+
+
 def test_put_overwrites(notes_bucket):
     blob.put_note(notes_bucket, _note("first"))
     blob.put_note(notes_bucket, _note("second"))
diff --git a/tests/test_okf_note.py b/tests/test_okf_note.py
index 29267f6..2e225cc 100644
--- a/tests/test_okf_note.py
+++ b/tests/test_okf_note.py
@@ -2,7 +2,7 @@ import pytest
 import yaml
 
 from slackkb.models import Note, NoteStatus, Severity
-from slackkb.okf_note import OkfNote, OkfNoteError, from_markdown, object_key, to_markdown
+from slackkb.okf_note import OkfNote, OkfNoteError, from_markdown, key_for, object_key, to_markdown
 
 FIELDS = ("note_id", "team_id", "channel_id", "user_id", "created_at")
 
@@ -131,6 +131,44 @@ def test_yaml_value_errors_become_okf_note_error(line):
         from_markdown("---\n" + head + "---\nbody")
 
 
+@pytest.mark.parametrize(
+    "line",
+    [
+        'note_id: !!int ""',
+        "note_id: !!bool foo",
+        "created_at: !!timestamp foo",
+        'note_id: !!binary "@@"',
+        "note_id: !!binary aGVsbG8=",
+        "note_id: 123",
+        "note_id:",
+        "created_at: 2026-01-02",
+    ],
+)
+def test_bad_frontmatter_values_become_okf_note_error(line):
+    key = line.split(":")[0]
+    head = "".join(
+        (line if row.startswith(key + ":") else row) + "\n" for row in VALID_HEAD.splitlines()
+    )
+    with pytest.raises(OkfNoteError):
+        from_markdown("---\n" + head + "---\nbody")
+
+
+def test_any_safe_load_exception_becomes_okf_note_error(monkeypatch):
+    def boom(_):
+        raise TypeError("boom")
+
+    monkeypatch.setattr(yaml, "safe_load", boom)
+    with pytest.raises(OkfNoteError) as info:
+        from_markdown("---\n" + VALID_HEAD + "---\nbody")
+    assert info.value.__cause__ is None and info.value.__suppress_context__
+
+
+def test_key_for_matches_object_key():
+    n = _note()
+    assert key_for(n.team_id, n.note_id) == object_key(n)
+    assert key_for("T9", "x") == "notes/T9/x.md"
+
+
 def test_okf_note_error_is_value_error():
     assert issubclass(OkfNoteError, ValueError)
 
diff --git a/tests/test_worker.py b/tests/test_worker.py
index 393d411..93e63b6 100644
--- a/tests/test_worker.py
+++ b/tests/test_worker.py
@@ -324,7 +324,7 @@ def test_worker_logs_failed_note_not_written(notes_table, notes_bucket, caplog):
     assert _run(notes_table, notes_bucket, caplog) == {"batchItemFailures": []}
     (rec,) = _worker_records(caplog, logging.INFO)
     msg = rec.getMessage()
-    assert "note failed, not written" in msg and "a" * 32 in msg and "m1" in msg
+    assert "note failed, no object" in msg and "a" * 32 in msg and "m1" in msg
     assert _worker_records(caplog, logging.WARNING) == []
     assert _keys(notes_bucket) == []
 
@@ -482,6 +482,62 @@ def test_worker_lost_race_still_captured_is_batch_failure(
     assert note_id in rec.getMessage()
 
 
+def test_worker_failed_note_deletes_object(notes_table, notes_bucket, monkeypatch):
+    note_id = "a" * 32
+    _put(notes_table, note_id, status=NoteStatus.FAILED)
+    calls = []
+    real = worker.delete_note
+    monkeypatch.setattr(worker, "delete_note", lambda *a: (calls.append(a), real(*a))[1])
+    assert worker.handle(_event(note_id), table=notes_table, bucket=notes_bucket) == {
+        "batchItemFailures": []
+    }
+    assert calls == [(notes_bucket, TEAM_ID, note_id)]
+
+
+@pytest.mark.parametrize("kind", ["client_error", "botocore_error"])
+def test_worker_failed_note_delete_failure_retries_then_removes(
+    notes_table, notes_bucket, caplog, kind
+):
+    note_id = "a" * 32
+    _put(notes_table, note_id, status=NoteStatus.FAILED)
+    blob.put_note(
+        notes_bucket,
+        Note(note_id=note_id, team_id=TEAM_ID, channel_id="C1", user_id="U1", text="t"),
+    )
+    if kind == "client_error":
+        exc = ClientError({"Error": {"Code": "AccessDenied"}}, "DeleteObject")
+    else:
+        exc = EndpointConnectionError(endpoint_url="https://s3.invalid")
+    first = _run(notes_table, _DeleteFailingBucket(notes_bucket, exc), caplog, message_id="m-d1")
+    assert _failures(first) == ["m-d1"]
+    assert _keys(notes_bucket) == [f"notes/{TEAM_ID}/{note_id}.md"]
+    (rec,) = _worker_records(caplog, logging.WARNING)
+    msg = rec.getMessage()
+    assert type(exc).__name__ in msg and note_id in msg and "m-d1" in msg
+    caplog.clear()
+    second = _run(notes_table, notes_bucket, caplog, message_id="m-d2")
+    assert second == {"batchItemFailures": []}
+    assert _keys(notes_bucket) == []
+    assert get_note(notes_table, note_id).status is NoteStatus.FAILED
+    (info,) = _worker_records(caplog, logging.INFO)
+    assert "note failed, no object" in info.getMessage()
+
+
+def test_worker_lost_race_still_captured_warns_and_retries(
+    notes_table, notes_bucket, caplog, monkeypatch
+):
+    note_id = "a" * 32
+    _put(notes_table, note_id)
+    still_captured = Note(note_id=note_id, team_id=TEAM_ID, channel_id="C1", user_id="U1", text="t")
+    _lost_race(monkeypatch, still_captured)
+    resp = _run(notes_table, notes_bucket, caplog, message_id="m-cap2")
+    assert _failures(resp) == ["m-cap2"]
+    (rec,) = _worker_records(caplog, logging.WARNING)
+    msg = rec.getMessage()
+    assert "after lost race" in msg and "CAPTURED" in msg and note_id in msg and "m-cap2" in msg
+    assert _worker_records(caplog, logging.INFO) == []
+
+
 def test_worker_logs_never_contain_secrets(notes_table, notes_bucket, caplog, monkeypatch):
     signature = sign(NOTE_TEXT, 1)
     raw_body = json.dumps(

review PASS: All five requirements are met in the diff, and each behavior has a test that would fail if it broke. FAILED-at-read now deletes through the shared helper, logs the required INFO message, and returns a batch failure on ClientError or BotoCoreError. The status check moved out of the get_note try, so a delete error can't be logged as a read error. The redelivery test covers both error types end to end. The CAPTURED lost-race test pins both the WARNING and the batch failure. `except Exception ... from None` and strict=True cover the named YAML inputs, including `!!binary`, ints, dates and None. The rest of from_markdown is outside the diff, so I judged its validation from the tests. c1 is supported: 214 passed (199 existing + 15 new) and ruff is clean. c2 matches the diff. The change agrees with D-009 and D-014: status is untouched, a FAILED note ends with no object, and S3 access stays in blob.py. The diff touches only SCOPE paths. One minor test-naming note is below.
  [minor] tests/test_blob.py: test_blob_keys_come_from_okf_note_key_for claims more than it proves. It compares the stored key with object_key(n), so it would still pass if blob.py had its own f-string with the same format. It does fail if the two formats diverge, which is the behavior that matters. The structural rule (blob uses key_for, no second f-string) is met in the diff. To pin the structure too, add `assert blob._key is key_for`; otherwise rename the test to say the keys match.
merge prama/personal_1c127c83 into the current branch of /home/vajrasarpa/Projects/slack-kb? [y/N]: <answered y>merged as 73b71e7fd562. Nothing was pushed.
