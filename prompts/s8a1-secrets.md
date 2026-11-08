GOAL
Slice 8a, part 1 (D-020, amends D-007): both Slack secrets become optional
in Settings, so a Lambda gets only the secrets its IAM role can read, and a
handler that needs a missing secret fails with config.MissingSecret before
it reads the request.

SCOPE (only these paths may change)
- src/slackkb/config.py        optional secrets, MissingSecret, Settings.require
- src/slackkb/capture.py       read the signing secret through require
- src/slackkb/modal.py         read the signing secret through require
- src/slackkb/events.py        read the signing secret through require
- src/slackkb/thread.py        slack_client reads the bot token through require
- tests/test_config.py         new tests, plus the two replacements named below

CONTEXT
- Slices 1-7b, 2b, 9a and 9b are merged; all 456 existing tests must stay
  green. No existing test line changes except the two tests in
  tests/test_config.py that requirement 1 replaces:
  test_missing_signing_secret_fails and test_missing_slack_bot_token_fails.
- docs/DECISIONS.md D-020 is the spec (the "Amendment to D-007" sentences).
  D-007 (pydantic-settings, SLACKKB_ prefix, no .env), D-019 (each handler
  call runs in its own obs.trace()) and D-017 (thread's 10 s Slack client)
  also apply. entry.py is part 2, not this task.
- tests/conftest.py sets every SLACKKB_ variable, secrets included, so
  existing tests that build Settings() still see both secrets.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS
1. config.py: signing_secret and slack_bot_token are `SecretStr | None`,
   default None. Every other field stays required. Unknown kwargs still
   raise, no .env file is read, and a secret never appears in repr/str.
2. config.py: a new exception `class MissingSecret(RuntimeError)`, and a
   method `Settings.require(name)` for name "signing_secret" or
   "slack_bot_token": it returns that field's SecretStr when set, and
   otherwise raises MissingSecret whose message is exactly
   "<name> is not configured". Any other name raises ValueError.
3. capture, modal and events: the first thing their request handling does
   (inside the obs.trace() the handler already opens, before reading
   headers or body, before verify, and before any table, queue or Slack
   call) is `settings.require("signing_secret")`; the value it returns is
   what verify gets. MissingSecret is not caught: it propagates out of
   handle(). With the secret set, behaviour is unchanged.
4. thread.slack_client(settings) builds its client from
   settings.require("slack_bot_token"), so it raises MissingSecret when
   the token is unset; otherwise unchanged (10 s transport).

TESTS (write first; run them and see them fail before writing src)
All in tests/test_config.py. Use monkeypatch.delenv for a missing secret.
- test_missing_signing_secret_is_none (replaces
  test_missing_signing_secret_fails): with SLACKKB_SIGNING_SECRET unset,
  Settings() builds, signing_secret is None, and require("signing_secret")
  raises MissingSecret with str(exc) == "signing_secret is not configured".
  (req 1, 2)
- test_missing_slack_bot_token_is_none (replaces
  test_missing_slack_bot_token_fails): the same for SLACKKB_SLACK_BOT_TOKEN
  and "slack_bot_token is not configured". (req 1, 2)
- test_require_returns_the_secret: with both set, require returns a
  SecretStr whose value is the env value, for each name; require("other")
  raises ValueError. (req 2)
- test_capture_without_signing_secret_raises,
  test_modal_without_signing_secret_raises,
  test_events_without_signing_secret_raises: with the signing secret unset,
  a request signed with the conftest secret makes handle() raise
  MissingSecret, and recording fakes passed as table / sqs / events_table /
  slack record no call at all. (req 3)
- test_handlers_with_signing_secret_still_verify: with the secret set, a
  bad signature still gets 401 from capture, modal and events. (req 3)
- test_thread_slack_client_without_bot_token_raises: with the bot token
  unset, thread.slack_client(Settings()) raises MissingSecret; with it set,
  it returns a SlackClient. (req 4)

NON-GOALS
- entry.py, Secrets Manager calls, boto3 clients: part 2.
- Changing verify, SlackClient, the other Settings fields, or any test
  file other than tests/test_config.py.

DONE WHEN
- `python -m pytest` and `python -m ruff check src tests` pass.
- The diff touches only the SCOPE paths.
