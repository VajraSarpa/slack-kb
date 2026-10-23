GOAL
Slice 3 of SlackKB: the /bnote ack carries a "Set severity" button; clicking
it opens a modal (views.open), and submitting the modal sets the note's
severity.

SCOPE (only these paths may change)
- src/slackkb/modal.py         new; block_actions + view_submission handler
- src/slackkb/slack_api.py     new; the only module that calls the Slack Web API
- src/slackkb/capture.py       only the ack: add the button; nothing else
- src/slackkb/store.py         add the severity update
- src/slackkb/config.py        add slack_bot_token
- tests/test_modal.py          new
- tests/test_store.py          new tests for the severity update only
- tests/test_config.py         only if the new setting requires it
- tests/test_worker.py         only the ack-body equality assertion in
                               test_ack_before_processing, so it allows the
                               button; nothing else in the file may change

CONTEXT
- Slices 1 and 2 are merged; all 58 existing tests must stay green.
- tests/conftest.py and tests/fixtures/ are read-only. Use its fixtures:
  aws, notes_table, capture_queue, slack_request, the autouse offline_env
  (now also sets SLACKKB_SLACK_BOT_TOKEN), and slack_interaction(kind,
  severity=None, note_id=None, ts=None, secret=...) where kind is
  "block_actions" or "view_submission". It returns a signed API Gateway
  event whose body is form-encoded payload=<json>.
- Both fixtures carry note_id fc38664126ae9d90a01ded694dc82aa0, which is
  models.note_id() of the slash_bnote.json request, so a note written by
  capture.handle (or put_if_absent) is the one the fixtures point at.
- Ids the fixtures use, which the code must use too: ack actions block
  "note_actions", button action_id "set_severity" (value = note_id); modal
  callback_id "severity_modal", private_metadata = note_id; input block
  "severity", static_select action_id "severity_select".
- docs/SLICES.md row 3 and docs/DECISIONS.md (D-006, D-007, D-009, D-013) and
  okf/slackkb/ are authoritative. Severity values are the models.Severity
  enum (okf/slackkb/glossary.md). reference/ is testimony only.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.

REQUIREMENTS
1. capture's ack (new note and duplicate alike) keeps response_type
   "ephemeral" and the same "text", and adds blocks: a section with the ack
   text and an actions block "note_actions" with one button, action_id
   "set_severity", value = note_id. The retry message (enqueue failure) has
   no button. capture.py still makes no Slack Web API calls.
2. slack_api.SlackClient(token: SecretStr, transport) with
   views_open(trigger_id, view) -> None. transport is a callable
   (url, headers, json_body) -> dict; tests pass a fake that records calls.
   It posts to https://slack.com/api/views.open with
   "Authorization: Bearer <token>" and raises SlackApiError when the reply's
   "ok" is false or the transport raises. A default transport using
   urllib.request is allowed in slack_api.py only. Never log the token.
3. modal.handle(event, *, table, slack, settings, now) -> dict. Verify the
   signature (slack_verify) on the raw body; bad or stale -> 401. Parse the
   payload field; missing or not JSON -> 400. Dispatch on payload "type";
   anything else -> 400.
4. block_actions with action_id "set_severity": load the note named by the
   button value. If it exists and its team_id equals payload team.id, call
   slack.views_open with the payload's trigger_id and a modal: callback_id
   "severity_modal", private_metadata = note_id, one input block "severity"
   holding a static_select "severity_select" with one option per Severity
   value, initial_option = the note's current severity. Always return 200
   with an empty body. A missing note, a team mismatch, another action_id,
   or SlackApiError opens nothing; SlackApiError logs a warning naming the
   note_id.
5. view_submission with callback_id "severity_modal": note_id from
   private_metadata, severity from view.state.values.severity.severity_select.
   On success, update the note's severity and return 200 with an empty body.
   Return 200 {"response_action": "errors", "errors": {"severity": "<msg>"}}
   and change nothing when: the value is not a Severity; the note does not
   exist; or the note's team_id differs from payload team.id (same message
   as a missing note, so another team can't probe note ids).
6. store gains set_severity(table, note_id, severity) -> None: a conditional
   update (attribute_exists(note_id)) that sets severity only; it never
   touches status or any other attribute (D-009). Missing note ->
   NoteNotFoundError.
7. Settings gains a required slack_bot_token: SecretStr
   (SLACKKB_SLACK_BOT_TOKEN), no default (D-007, D-013).
8. All DynamoDB access goes through store.py; all Slack Web API calls through
   slack_api.py. modal.py and capture.py never import boto3, urllib.request,
   or any HTTP client. Never log note text, the signing secret, the bot token,
   or response_url.

TESTS (write first; run them and see them fail before writing src)
In tests/test_modal.py:
- test_modal_submission_updates_severity: capture a note, submit HIGH; the
  note's severity is HIGH, status and text unchanged, response 200 empty.
- test_ack_has_set_severity_button
- test_button_opens_modal_with_note_id (fake transport: one views.open call,
  trigger_id from the fixture, private_metadata = note_id, bearer token)
- test_button_for_missing_note_opens_nothing
- test_unknown_severity_returns_errors
- test_submission_for_missing_note_returns_errors
- test_other_team_cannot_set_severity (both the button and the submission)
- test_bad_signature_rejected (both payload types)
- test_unknown_payload_type_rejected
- test_views_open_failure_is_logged_not_raised
- test_handlers_import_no_http_client
In tests/test_store.py: test_set_severity_leaves_status,
test_set_severity_missing_note_raises.
Every requirement above has a test that fails if the requirement is broken.

NON-GOALS
No Lambda entry points, no worker changes, no status changes, no S3, no
Bedrock, no IaC, no deploy, no real Slack calls. Do not touch reference/,
tests/conftest.py, tests/fixtures/, infra/, or any src/ module not in SCOPE.

DONE WHEN
All checks exit 0 in the sandbox with no network, and the diff touches only
SCOPE paths.
