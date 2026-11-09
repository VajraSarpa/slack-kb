GOAL
Slice 8a, part 2 (D-020): src/slackkb/entry.py, one Lambda handler per
function, so the SAM template (Slice 8b) has handlers to point at. Each
handler builds what its handle() needs once per container, reads only the
secrets that Lambda uses from Secrets Manager, and calls handle().

SCOPE (only these paths may change)
- src/slackkb/entry.py         new module
- tests/test_entry.py          new tests

CONTEXT
- Slices 1-7b, 2b, 9a, 9b and 8a part 1 are merged; all 462 existing tests
  must stay green and no existing test line or other src file changes.
- docs/DECISIONS.md D-020 is the spec (everything before "Amendment to
  D-007"; part 1 already did the amendment: Settings secrets are optional
  and Settings.require raises config.MissingSecret). D-017, D-018 and
  D-019 also apply (timeouts, obs.configure).
- The handle() signatures, all keyword-only after event:
  capture.handle(event, *, table, sqs, settings, now)
  modal.handle(event, *, table, slack, settings, now)
  events.handle(event, *, events_table, sqs, settings, now)
  worker.handle(event, *, table, bucket, vectors_table, embed)
  notify.handle(event, *, table, bucket, vectors_table, post)
  thread.handle(event, *, retrieve, answer, slack), with
  thread.bind(settings, *, bedrock, vectors_table, bucket) -> (retrieve, answer)
  and thread.slack_client(settings). table = the DynamoDB Table named
  settings.notes_table; vectors_table / events_table likewise; bucket = the
  S3 Bucket named settings.notes_bucket; sqs = an SQS client; bedrock = a
  bedrock-runtime client. embed.embed_text(client, *, model_id, text);
  slack_api.post_response_url(url, text, transport) and
  slack_api.make_response_url_transport(timeout); slack_api.SlackClient(token)
  uses the 2.5 s views.open transport by default.
- tests/conftest.py's autouse fixture sets every SLACKKB_ variable except
  SLACKKB_CAPTURE_QUEUE_URL, including both secrets. A test about which
  secrets a Lambda reads must delenv SLACKKB_SIGNING_SECRET and
  SLACKKB_SLACK_BOT_TOKEN first, and setenv SLACKKB_CAPTURE_QUEUE_URL.
- Tests run with --disable-socket. No test may build a real boto3 session:
  patch entry._session (requirement 2) with a fake.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS
1. entry.py defines capture_handler, modal_handler, events_handler,
   worker_handler, notify_handler, thread_handler, each (event, context)
   and returning exactly what that module's handle() returns. The event is
   passed to handle() unchanged; context is not used.
2. Importing entry.py makes no AWS or network call and builds no client.
   Every boto3 object comes from one module-level function
   `_session()` (returning boto3.session.Session()), called only on a
   container's first call.
3. On a Lambda's first call, and cached at module level for later calls
   of that Lambda: obs.configure() once per process; the Lambda's secrets
   fetched with secretsmanager get_secret_value(SecretId=<arn>) and the
   whole "SecretString" used; Settings built from the SLACKKB_ environment
   with those values passed as signing_secret / slack_bot_token; the
   clients it needs built. A function `reset()` clears every cache (for
   tests).
4. Which secret each Lambda fetches, and from which env var: capture and
   events: signing secret from SIGNING_SECRET_ARN; modal: signing secret
   and bot token (SLACK_BOT_TOKEN_ARN); thread: bot token; worker and
   notify: none. A Lambda never fetches a secret it doesn't use. If the
   env var is unset, that secret is not fetched and stays None, so the
   handler fails with MissingSecret where it is used (part 1).
5. A failed get_secret_value raises out of the handler and caches nothing:
   the next call fetches again.
6. Each call passes now = int(time.time()) where handle() takes now.
7. Bindings: worker embed(text) = embed_text(bedrock, model_id =
   settings.embed_model_id, text=text); notify post(url, text) =
   post_response_url(url, text, make_response_url_transport(10.0)); thread
   gets retrieve and answer from thread.bind(settings, bedrock=...,
   vectors_table=..., bucket=...) and slack = thread.slack_client(settings);
   modal gets SlackClient(settings.require("slack_bot_token")).
8. No log line contains a secret value or an ARN's SecretString.

TESTS (write first; run them and see them fail before writing src)
All in tests/test_entry.py. Use a fake session whose resource("dynamodb").
Table(name), resource("s3").Bucket(name) and client(<service>) return
recording fakes; the secretsmanager fake returns {"SecretString": <value>}
per SecretId and records each call. Patch each module's handle (e.g.
monkeypatch.setattr(entry.capture, "handle", recorder)) to capture the
kwargs, and patch entry.obs.configure to count calls. Call entry.reset()
before each test.
- test_import_makes_no_aws_call: reload entry with _session patched to
  raise: the import succeeds. (req 2)
- test_capture_handler_loads_only_its_secret: both ARN env vars set:
  capture_handler fetches only the signing ARN; handle gets table =
  Table(notes_table), the sqs client, settings with the fetched signing
  secret and slack_bot_token None, now = the patched time.time. (req 1, 3,
  4, 6)
- test_each_handler_fetches_only_its_secrets: for events, modal, thread,
  worker, notify: the SecretIds fetched match requirement 4. (req 4)
- test_handler_returns_what_handle_returns: each of the six returns the
  recorder's return value, and handle got the same event object. (req 1)
- test_cold_start_runs_once: two capture_handler calls: one
  get_secret_value, one Settings, one _session call; obs.configure once.
  (req 3)
- test_failed_secret_fetch_raises_and_caches_nothing: first fetch raises:
  the handler raises; the second call fetches again and succeeds. (req 5)
- test_missing_arn_env_fails_at_use: SIGNING_SECRET_ARN unset, the real
  capture.handle: capture_handler raises MissingSecret and nothing is
  fetched. (req 4)
- test_worker_and_notify_bindings: worker's embed calls embed_text with the
  bedrock client and embed_model_id; notify's post calls post_response_url
  with a transport made by make_response_url_transport(10.0) (patch both to
  record). (req 7)
- test_thread_and_modal_bindings: thread.bind gets settings, the bedrock
  client, Table(vectors_table) and Bucket(notes_bucket), and handle gets
  its retrieve/answer and thread.slack_client(settings); modal's slack is a
  SlackClient built from the fetched bot token. (req 7)
- test_no_secret_in_logs: with caplog at DEBUG over a cold start of modal,
  no record contains either secret value. (req 8)

NON-GOALS
- infra/ and the template (8b), deploying, real AWS calls.
- Changing any other src file or any existing test.

DONE WHEN
- `python -m pytest` and `python -m ruff check src tests` pass.
- The diff touches only the SCOPE paths.
