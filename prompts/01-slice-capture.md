GOAL
Rung C5 of Slice 1: a /bnote slash command is received, its Slack signature
is verified, the note is persisted to DynamoDB, and the request is acked.

SCOPE (only these paths may change)
- src/slackkb/capture.py       handler: verify -> parse -> write -> ack
- tests/test_capture.py

CONTEXT
- Already on main and out of scope: models.py (Note, Severity,
  CaptureRequest), slack_verify.py (verify, SignatureError), store.py
  (put_if_absent, get_note), config.py (Settings). Use them; do not edit them.
- tests/conftest.py and tests/fixtures/ are read-only. Use its fixtures:
  slack_request (signed API Gateway event; options text, ts, secret, retry,
  lowercase_headers, drop), notes_table (moto table), and the autouse
  offline_env.
- docs/SLICES.md, docs/DECISIONS.md (D-006, D-007) and okf/slackkb/ are
  authoritative. reference/ is testimony: use it to understand intent, not as
  code to copy.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.

REQUIREMENTS
1. Entry point: handle(event, *, table, settings, now) -> dict. event is an
   API Gateway proxy event; table is a boto3 Table passed in; settings is a
   Settings; now is epoch seconds. Return an API Gateway proxy response
   (statusCode, headers, body). No Lambda entry point in this rung.
2. Verify the signature on the raw body before parsing it (slack_verify.verify).
   Missing headers, a bad signature or a timestamp older than 300s return 401,
   write nothing, and the body carries no secret.
3. If isBase64Encoded is true, decode the body before verifying.
4. note_id = sha256(f"{team_id}:{trigger_id}") hex digest, first 32 chars
   (D-006). Slash commands are not retried by Slack; the conditional put
   (store.put_if_absent) still blocks duplicates. A duplicate request returns
   the same 200 ack and leaves exactly one item.
5. Note fields come from the form: team_id, channel_id, user_id, text.
   severity stays the default LOW and status CAPTURED (severity is Slice 3).
6. Empty or whitespace-only text returns 200 with an ephemeral usage hint and
   writes nothing.
7. Success returns HTTP 200, JSON body {"response_type": "ephemeral",
   "text": ...}. No Bedrock call in this slice.
8. The handler returns the ack response; it never calls Slack's response_url.
9. All DynamoDB access goes through store.py. capture.py never imports boto3
   or any HTTP client.

TESTS (write first; they must fail before implementation)
- test_valid_request_writes_note
- test_bad_signature_returns_401_and_writes_nothing
- test_missing_headers_rejected
- test_stale_timestamp_rejected
- test_lowercase_headers_accepted
- test_base64_body_accepted
- test_retry_does_not_duplicate
- test_note_id_is_sha256_of_team_and_trigger
- test_empty_text_returns_usage_hint
- test_ack_is_ephemeral_200
- test_capture_imports_no_boto3_or_http_client
test_note_model_rejects_unknown_severity already exists in
tests/test_models.py; do not duplicate it.
Every requirement above has a test that fails if the requirement is broken.

NON-GOALS
No IaC, no deploy, no Bedrock, no embeddings, no modals, no thread replies,
no SQS (Slice 2), no Lambda entry point. Do not touch reference/,
tests/conftest.py, tests/fixtures/, or any other src/ module.

DONE WHEN
All checks exit 0 in the sandbox with no network.
