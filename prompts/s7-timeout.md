GOAL
Slice 7 follow-up (D-017 amendment): the question worker's Slack calls
use a 10 s timeout, while views.open keeps 2.5 s. Add a transport
factory to slack_api.py and a client factory to thread.py.

SCOPE (only these paths may change)
- src/slackkb/slack_api.py     add make_urllib_transport; urllib_transport
                               becomes make_urllib_transport(2.5)
- src/slackkb/thread.py        add SLACK_TIMEOUT_SECONDS and slack_client
- tests/test_slack_api.py      new tests only
- tests/test_thread.py         new tests only

CONTEXT
- Slices 1-7b are merged; all 387 existing tests must stay green.
- tests/conftest.py and tests/fixtures/ are read-only. offline_env sets
  SLACKKB_SLACK_BOT_TOKEN; SLACKKB_CAPTURE_QUEUE_URL is not set by it,
  so a test that builds Settings() sets it, as tests/test_config.py does.
- docs/DECISIONS.md D-017 (its 2026-11-08 amendment) is the spec; D-013
  (bot token) also applies.
- No network: pytest runs with --disable-socket. Test the timeout by
  monkeypatching urllib.request.urlopen in slackkb.slack_api with a fake
  that records its timeout argument and returns an object usable as a
  context manager whose read() gives b'{"ok": true}'.
- modal.py builds no SlackClient itself (it is injected), so nothing
  outside SCOPE needs to change.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS
1. slack_api.make_urllib_transport(timeout: float) -> Transport returns
   a transport that does what urllib_transport does today (https only,
   else ValueError; POST json_body as JSON with Content-Type
   "application/json; charset=utf-8" plus the given headers; returns the
   decoded JSON reply) and passes exactly that timeout to urlopen.
2. slack_api.urllib_transport stays a module-level Transport and uses
   DEFAULT_TIMEOUT_SECONDS (2.5); SlackClient's default transport is
   still urllib_transport.
3. thread.SLACK_TIMEOUT_SECONDS = 10.0.
4. thread.slack_client(settings) -> SlackClient built from
   settings.slack_bot_token with make_urllib_transport(
   SLACK_TIMEOUT_SECONDS); a chat_post_message through it reaches
   urlopen with timeout 10.0. Its repr still hides the token.

TESTS (write first; run them and see them fail before writing src)
In tests/test_slack_api.py:
- test_make_transport_passes_timeout (exact timeout value reaches
  urlopen)
- test_default_transport_timeout_is_2_5 (urllib_transport and a
  SlackClient with no transport argument both reach urlopen with 2.5)
- test_make_transport_request_shape (exact URL, method POST, exact
  JSON body bytes, Content-Type and Authorization headers)
- test_make_transport_rejects_non_https
In tests/test_thread.py:
- test_slack_client_uses_10s_timeout (post through slack_client(
  Settings()); urlopen saw timeout 10.0 and the bearer token from
  SLACKKB_SLACK_BOT_TOKEN)
- test_slack_client_repr_hides_token
Every requirement above has a test that fails if the requirement is
broken; each "exactly" value is compared to a fixed expected value.

NON-GOALS
No worker-side dedup ("answered" marker), no retries, no Lambda entry
points, no IaC. Do not change events.py, dedup.py, queue.py, models.py,
config.py, capture.py, modal.py, worker.py, store.py, blob.py,
okf_note.py, llm.py, qa.py, embed.py, vectors.py, retrieve.py,
slack_verify.py, reference/, tests/conftest.py, tests/fixtures/, infra/.

DONE WHEN
All checks exit 0 in the sandbox with no network, and the diff touches only
SCOPE paths.
