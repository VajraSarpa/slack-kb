GOAL
D-015: a failed enqueue leaves no note behind. When capture has written a
CAPTURED note and the SQS send fails, capture deletes that note (only while it
is still CAPTURED), logs the note_id, and returns the retry message.

SCOPE (only these paths may change)
- src/slackkb/store.py
- src/slackkb/capture.py
- tests/test_store.py
- tests/test_worker.py

CONTEXT
- docs/DECISIONS.md and okf/slackkb/ are authoritative; read D-015, D-011,
  D-009 and D-006. reference/ is testimony.
- Today the note stays CAPTURED forever after a failed send: Slack never
  retries a slash command (D-006), and the user's own retry has a new
  trigger_id, so a new note_id; nothing processes the old note.
- capture.py may not import boto3 or botocore
  (tests/test_capture.py::test_capture_imports_no_boto3_or_http_client).
  queue.py already wraps botocore errors in EnqueueError; store.py does the
  same for the delete.
- tests/conftest.py and tests/fixtures/ are read-only.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.

REQUIREMENTS
1. store.py: `delete_if_captured(table, note_id) -> bool` deletes the item
   only if it exists and its status is CAPTURED (one conditional delete).
   True if deleted; False if there is no item or its status is anything
   else (item left unchanged).
2. store.py: `StoreError(Exception)`. `delete_if_captured` raises it on any
   other botocore ClientError or BotoCoreError; its message names only the
   botocore error class (no note text, no ids beyond what the caller logs).
3. capture.py: on EnqueueError, call delete_if_captured, log a WARNING with
   the note_id (as now), and return the retry message. If the delete raises
   StoreError, log a WARNING with the note_id and still return the retry
   message. No log line contains the note text, the signing secret or
   response_url.
4. The duplicate path is unchanged: a duplicate note_id sends nothing and
   returns the ack (Slice 2 req 2). The success path is unchanged.
5. Every existing test keeps passing unchanged, with one exception:
   in tests/test_worker.py::test_enqueue_failure_returns_retry_message the
   assertion that the note is still CAPTURED becomes an assertion that there
   is no item (get_note returns None). Nothing else in that test changes.

TESTS (write first; they must fail before the change)
- tests/test_store.py: delete_if_captured deletes a CAPTURED note; returns
  False and leaves a ROUTED note unchanged; returns False for a missing
  note_id; raises StoreError on another ClientError.
- tests/test_worker.py: the changed assertion above (both parametrized
  kinds); a failed delete after a failed enqueue still returns the retry
  message and logs a WARNING with the note_id.

NON-GOALS
No sweeper, no re-send on a duplicate, no change to worker.py, queue.py,
models.py or the ack. Do not touch reference/, infra/ or docs/.

DONE WHEN
All checks exit 0 in the sandbox with no network, and the diff touches only
the SCOPE paths.
