GOAL
Slice 4 of SlackKB: the worker writes each note to S3 as an OKF Markdown
file (YAML frontmatter + text body), then moves the note CAPTURED -> ROUTED.

SCOPE (only these paths may change)
- src/slackkb/okf_note.py      new; Note <-> OKF Markdown, pure (no I/O)
- src/slackkb/blob.py          new; the only module that touches S3
- src/slackkb/worker.py        load the note, write it via blob, then route
- src/slackkb/config.py        add notes_bucket
- tests/test_okf_note.py       new
- tests/test_blob.py           new
- tests/test_worker.py         existing tests may only gain the bucket
                               argument/fixture and "slackkb.blob" in the
                               worker boundaries set; no existing assertion
                               may change. New S3 tests may be added.
- tests/test_config.py         only if the new setting requires it

CONTEXT
- Slices 1-3 are merged; all 84 existing tests must stay green.
- tests/conftest.py and tests/fixtures/ are read-only. Use its fixtures:
  aws, notes_table, capture_queue, slack_request, slack_interaction, the
  autouse offline_env (now also sets SLACKKB_NOTES_BUCKET), and the new
  notes_bucket: a boto3 s3.Bucket resource, created in the same moto
  context as notes_table, named by SLACKKB_NOTES_BUCKET.
- docs/DECISIONS.md D-014 is the spec for this slice; D-004, D-007 and
  D-009 also apply. docs/SLICES.md row 4 and okf/slackkb/ are
  authoritative. reference/ is testimony only.
- pyyaml is a direct dependency (pyproject.toml); use yaml.safe_dump and
  yaml.safe_load only.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS
1. okf_note.to_markdown(note: Note) -> str returns exactly
   "---\n" + yaml.safe_dump(frontmatter, sort_keys=True) + "---\n" + note.text
   where frontmatter = {note_id, team_id, channel_id, user_id, created_at}
   (D-014). severity, status and text never appear in the frontmatter.
2. okf_note.from_markdown(md: str) -> OkfNote, a pydantic model with those
   five frontmatter fields plus text. It splits on the first "---\n" line
   after the opening one, so a body containing "---" lines or YAML-like
   text round-trips unchanged. Missing opening delimiter, missing closing
   delimiter, non-mapping frontmatter, or a missing field -> OkfNoteError
   (a ValueError). Unknown frontmatter keys are rejected.
3. Round-trip: from_markdown(to_markdown(note)) equals the note's five
   fields and text exactly, including values YAML would otherwise retype
   (an ISO created_at, a note_id like "1e10" or "0123", empty text, text
   with a trailing newline, unicode).
4. okf_note.object_key(note) -> "notes/<team_id>/<note_id>.md".
5. blob.put_note(bucket, note) -> None writes to_markdown(note) as UTF-8 at
   object_key(note) with ContentType "text/markdown; charset=utf-8". An
   overwrite is fine (idempotent). blob.get_note(bucket, team_id, note_id)
   -> OkfNote | None (None when the key does not exist; other S3 errors
   propagate). bucket is a boto3 s3.Bucket resource passed in by the caller.
6. Settings gains a required notes_bucket: str (SLACKKB_NOTES_BUCKET), no
   default (D-007).
7. worker.handle(event, *, table, bucket) -> dict. Per record: parse the
   job (unchanged); load the note with store.get_note; missing note ->
   failure (unchanged warning). If the note is FAILED, write nothing and
   count the record as handled (D-009, unchanged behavior). Otherwise
   blob.put_note first, then transition_status to ROUTED. An S3 error
   (ClientError or BotoCoreError) -> that record is a batch failure, the
   note stays CAPTURED, and a warning names note_id and message_id. A
   redelivered ROUTED note is rewritten (idempotent) and still succeeds.
8. worker.py never imports boto3 (botocore.exceptions is allowed, as now);
   all S3 access goes through blob.py, all DynamoDB through store.py.
   Never log note text.

TESTS (write first; run them and see them fail before writing src)
In tests/test_okf_note.py:
- test_note_round_trips_as_okf (the acceptance test)
- test_frontmatter_excludes_severity_status_and_text
- test_body_with_delimiter_and_yaml_round_trips
- test_yaml_lookalike_values_stay_strings
- test_malformed_markdown_raises (one case per rule in requirement 2)
- test_object_key
In tests/test_blob.py: test_put_then_get_round_trips (content type checked),
test_get_missing_returns_none, test_put_overwrites.
In tests/test_worker.py:
- test_worker_writes_okf_then_routes (the S3 object exists and parses; the
  note is ROUTED)
- test_worker_s3_failure_keeps_captured (bucket that raises; record is a
  failure; status CAPTURED; warning names note_id; note text not logged)
- test_worker_failed_note_writes_nothing
- test_worker_redelivery_rewrites_routed_note
Every requirement above has a test that fails if the requirement is broken.

NON-GOALS
No Bedrock structuring, no retrieval, no Slack calls, no Lambda entry
points, no DLQ consumer, no IaC, no deploy. Do not change capture.py,
modal.py, store.py, slack_api.py, models.py, reference/, tests/conftest.py,
tests/fixtures/, infra/.

DONE WHEN
All checks exit 0 in the sandbox with no network, and the diff touches only
SCOPE paths.
