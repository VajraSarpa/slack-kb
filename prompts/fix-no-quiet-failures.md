GOAL
Nothing in SlackKB fails quietly: every rejection, failure and no-op in the
three handlers is logged, every success is logged, and the two gaps found in
the Slice 4 review are closed. Responses, status codes and return values do
not change.

SCOPE (only these paths may change)
- src/slackkb/capture.py
- src/slackkb/modal.py
- src/slackkb/worker.py
- src/slackkb/okf_note.py
- src/slackkb/blob.py
- tests/test_capture.py, tests/test_modal.py, tests/test_worker.py,
  tests/test_okf_note.py, tests/test_blob.py
  Existing tests may only gain fixtures (e.g. caplog) and new assertions;
  no existing assertion may change or be removed. New tests may be added.

CONTEXT
- Slices 1-4 are merged; all 142 existing tests must stay green.
- tests/conftest.py and tests/fixtures/ are read-only. Use their fixtures
  (aws, notes_table, notes_bucket, capture_queue, slack_request,
  slack_interaction, the autouse offline_env) and constants (SIGNING_SECRET,
  BOT_TOKEN, NOTES_TABLE, NOTES_BUCKET).
- docs/DECISIONS.md is the spec: D-009 (status moves), D-014 (FAILED -> no
  S3 object), D-015 (enqueue cleanup), D-013 (modal). okf/slackkb/ is
  authoritative; reference/ is testimony only.
- Log style is the existing one: module logger `logging.getLogger(__name__)`,
  a short lowercase message, then `key=value` pairs, e.g.
  "note not found, note_id=%s message_id=%s". Use %-style arguments.
  WARNING for every rejection, failure or unexpected state; INFO for every
  success and for expected no-ops.
- Exception messages that are safe to log: SignatureError (fixed strings),
  EnqueueError and StoreError (botocore class name), SlackApiError (as now).
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS
1. okf_note.from_markdown: any ValueError or TypeError raised while loading
   the frontmatter YAML (e.g. `created_at: 2026-13-45`, `note_id: 0x_`)
   becomes OkfNoteError, like other bad YAML.
2. blob: one private key helper used by put_note, get_note and a new
   delete_note(bucket, team_id, note_id) -> None (deleting a missing key is
   not an error; other S3 errors propagate). object_key(note) keeps its
   signature and result.
3. worker, per record (return values as now unless stated):
   a. FAILED note at read -> INFO "note failed, not written" (note_id,
      message_id); nothing written; handled.
   b. CAPTURED note, put, transition True -> INFO "note routed".
   c. ROUTED note at read (redelivery) -> rewritten, transition returns
      False -> INFO "note already routed, rewritten"; handled.
   d. CAPTURED at read but transition returns False (status changed while
      writing): re-read the note with store.get_note.
      - now ROUTED (another delivery routed it) -> INFO, keep the S3
        object, handled.
      - now FAILED -> blob.delete_note, then WARNING naming note_id,
        message_id and that the object was removed (D-014); handled. If the
        delete fails (ClientError/BotoCoreError) -> WARNING naming the error
        class, and the record is a batch failure so SQS retries.
      - gone, or the re-read fails -> WARNING; batch failure.
   e. Existing warnings (unparsable job, not found, store error, blob
      error) stay as they are.
4. capture.handle:
   - 401 -> WARNING "capture rejected" with reason = the SignatureError
     message, or "bad body encoding" for base64/UTF-8 errors.
   - 400 -> WARNING with the names of the invalid fields only (pydantic
     error locs), never their values.
   - empty text -> INFO (usage reply sent), with team_id and user_id.
   - duplicate (put_if_absent False) -> INFO "duplicate capture" note_id.
   - stored and enqueued -> INFO "note captured" note_id.
   - delete_if_captured returns False after a failed enqueue -> WARNING
     "note not deleted, not captured or gone" note_id.
5. modal.handle:
   - 401 -> WARNING with reason as in 4; each 400 -> WARNING with the reason
     (no payload, bad payload, unknown type, wrong callback_id).
   - block_actions: wrong action_id (log the action_id), missing
     note_id/trigger_id, note missing, team mismatch (log both team ids) ->
     WARNING; views.open sent -> INFO note_id. views.open failure stays as
     now.
   - view_submission: invalid severity, missing note_id, note missing, team
     mismatch, NoteNotFoundError from set_severity -> WARNING (never log the
     submitted severity value); severity set -> INFO note_id severity.
6. Never in any log record: note text, the signing secret, the bot token,
   the request body, the X-Slack-Signature value, a response_url, or the raw
   payload. Ids (note_id, team_id, channel_id, user_id, message_id,
   action_id), status names and error class names are fine.
7. HTTP responses, status codes, Slack bodies and worker return values are
   unchanged on every path except 3d's delete-failure, which is new.

TESTS (write first; run them and see them fail before writing src)
- tests/test_okf_note.py: the two ValueError inputs above -> OkfNoteError.
- tests/test_blob.py: delete then get -> None; delete missing key is fine;
  other delete errors propagate.
- tests/test_worker.py: one test per path in 3a-3d (3d: simulate the status
  change by a table wrapper whose update fails the condition after you set
  the status to ROUTED or FAILED; check the S3 object is kept or removed,
  the level, the ids, and the return value), including the delete-failure
  case.
- tests/test_capture.py and tests/test_modal.py: parametrized tests that
  drive every path in 4 and 5 and assert exactly one record at the stated
  level from that module's logger naming the stated ids/reason.
- One test per handler that runs its paths with caplog at DEBUG and asserts
  none of the values in requirement 6 appear in caplog.text.
Every requirement above has a test that fails if the requirement is broken.

NON-GOALS
No logging configuration, no Lambda entry points, no structured/JSON logs or
correlation ids (Slice 9), no new user-facing messages, no changes to
store.py, queue.py, slack_api.py, slack_verify.py, models.py, config.py,
reference/, tests/conftest.py, tests/fixtures/, infra/, docs/.

DONE WHEN
All checks exit 0 in the sandbox with no network, and the diff touches only
SCOPE paths.
