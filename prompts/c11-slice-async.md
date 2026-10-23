GOAL
Rung C11, Slice 2 of SlackKB: /bnote is acked immediately and processing
happens in a worker that consumes an SQS queue.

SCOPE (only these paths may change)
- src/slackkb/capture.py       verify -> write CAPTURED -> enqueue -> ack
- src/slackkb/queue.py         new; the only module that talks to SQS
- src/slackkb/worker.py        new; SQS batch handler
- src/slackkb/models.py        add CaptureJob; NoteStatus gains ROUTED, FAILED
- src/slackkb/store.py         add the conditional status update
- src/slackkb/config.py        add capture_queue_url
- tests/test_worker.py         new
- tests/test_capture.py        only the _handle helper and test fixture
                               parameters; no assertion may change
- tests/test_config.py         only if the new setting requires it

CONTEXT
- Slice 1 is merged; all 45 existing tests must stay green.
- tests/conftest.py and tests/fixtures/ are read-only. Use its fixtures:
  aws (shared moto context), notes_table, capture_queue (creates the queue
  and a DLQ with maxReceiveCount 3, sets SLACKKB_CAPTURE_QUEUE_URL, returns
  Queues(url, dlq_url)), slack_request, and the autouse offline_env.
- docs/SLICES.md row 2 and docs/DECISIONS.md (D-004, D-006, D-009) and
  okf/slackkb/ are authoritative. reference/ is testimony: use it to
  understand intent, not as code to copy.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.

REQUIREMENTS
1. capture.handle(event, *, table, sqs, settings, now) -> dict. sqs is a
   boto3 SQS client passed in, like table. Verify, write the note as
   CAPTURED (store.put_if_absent), send CaptureJob(note_id) to
   settings.capture_queue_url, return the ephemeral ack. No Bedrock or Slack
   Web API calls; it never calls response_url.
2. A duplicate request (put_if_absent returns False) returns the same ack and
   sends nothing to the queue.
3. If the note is written but the send fails (botocore ClientError or
   BotoCoreError), return HTTP 200 with an ephemeral "couldn't process your
   report, please try again" message, and log a warning that names the
   note_id. Never log the note text, the signing secret, or response_url.
   The note stays CAPTURED.
4. worker.handle(event, *, table) -> dict, where event is an SQS Lambda
   event ({"Records": [{"messageId", "body", ...}]}). For each record, parse
   a CaptureJob and set the note to ROUTED. Return
   {"batchItemFailures": [{"itemIdentifier": messageId}, ...]} listing only
   the records that failed: an unparsable body, a missing note, or a store
   error.
5. D-009: the status update is a conditional update that applies only when
   the current status is CAPTURED. A note already ROUTED or FAILED is left
   unchanged and its record counts as a success, so processing the same
   message twice leaves one note with status ROUTED.
6. All SQS access goes through queue.py; all DynamoDB access through
   store.py. capture.py and worker.py never import boto3, botocore clients,
   or any HTTP client (importing botocore.exceptions is allowed).
7. Settings gains a required capture_queue_url: str (SLACKKB_CAPTURE_QUEUE_URL),
   no default.

TESTS (write first; they must fail before implementation)
In tests/test_worker.py:
- test_ack_before_processing: after capture.handle, the response is the 200
  ack, the note is CAPTURED, one CaptureJob is on the queue, and no worker
  has run.
- test_duplicate_capture_enqueues_once
- test_enqueue_failure_returns_retry_message
- test_worker_marks_routed
- test_worker_reports_partial_failure
- test_worker_is_idempotent
- test_worker_leaves_failed_note_alone
- test_handlers_import_no_boto3
Every requirement above has a test that fails if the requirement is broken.

NON-GOALS
No FAILED handling and no response_url (Slice 2b), no Lambda entry points,
no Bedrock, no S3, no IaC, no deploy. Do not touch reference/,
tests/conftest.py, tests/fixtures/, or any src/ module not listed in SCOPE.

DONE WHEN
All checks exit 0 in the sandbox with no network, and the diff touches only
SCOPE paths.
