GOAL
Rung C1 of Slice 1: Pydantic models for a captured note.

SCOPE (only these paths may change)
- src/slackkb/models.py
- tests/test_models.py

CONTEXT
- tests/conftest.py and tests/fixtures/ are read-only. tests/fixtures/slash_bnote.json
  shows the form fields Slack sends for /bnote.
- docs/DECISIONS.md and okf/slackkb/ are authoritative (okf/slackkb/glossary.md
  defines note and severity). reference/ is testimony.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.

REQUIREMENTS
1. Severity: a str Enum with exactly LOW, MEDIUM, HIGH, CRITICAL.
2. NoteStatus: a str Enum with CAPTURED. Other statuses come in Slice 2.
3. Note fields: note_id, team_id, channel_id, user_id, text, severity
   (default LOW), created_at, status (default CAPTURED).
   - created_at is a str: UTC ISO-8601 with a +00:00 offset, defaulting to now.
   - An unknown severity (e.g. "URGENT") raises pydantic.ValidationError.
4. CaptureRequest: the slash-command fields capture needs: team_id, channel_id,
   user_id, command, text, trigger_id, response_url. Extra form fields are ignored.
5. note_id is a plain str here. Do not derive it; that is rung C6 (D-006).

TESTS (write first; they must fail before implementation)
- test_note_defaults_low_and_captured
- test_note_model_rejects_unknown_severity
- test_created_at_is_utc_iso

NON-GOALS
No handler, no DynamoDB, no note_id derivation, no config. Do not touch
reference/, tests/conftest.py, or tests/fixtures/.

DONE WHEN
All checks exit 0 in the sandbox with no network.
