GOAL
An exception that a queue handler's per-record processing doesn't
already handle escapes handle(), so SQS retries the whole batch,
records that already succeeded included (a question already answered
gets a second Slack reply). Per D-023 (2026-11-12), such an error fails
only its own record: it is logged, the record goes in
batchItemFailures, and the rest of the batch is processed as usual.

SCOPE (only these paths may change)
- src/slackkb/worker.py
- src/slackkb/thread.py
- src/slackkb/notify.py
- tests/test_worker.py
- tests/test_thread.py
- tests/test_notify.py

CONTEXT
- 552 tests pass on main. docs/DECISIONS.md D-023 is the spec.
- Each module has handle(event, ...) that loops over event["Records"],
  runs _process(record, ...) inside `with obs.trace():`, and appends
  {"itemIdentifier": record["messageId"]} when _process returns False.
  _process catches the errors it expects (ValidationError, ClientError,
  BotoCoreError and module-specific ones); anything else propagates.
  Loggers: slackkb.worker, slackkb.thread, slackkb.notify. Existing log
  lines name exception classes only (type(exc).__name__), never their
  text, because exception text can hold note text.
- infra/template.yaml sets ReportBatchItemFailures on all three event
  sources; the capture and question queues redrive to a DLQ after 3
  receives.
- Test helpers: tests/test_worker.py _record(message_id, body),
  _job(note_id), _failures(resp); tests/test_thread.py
  record(job, message_id), make_job(), run(records, ...),
  warnings(caplog); tests/test_notify.py _record(message_id, ...),
  _event(*records), _run(event, table, bucket, vectors, post),
  _records(caplog). Fixtures in tests/conftest.py (notes_table,
  notes_bucket, vectors_table).
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS
1. In each of worker.handle, thread.handle and notify.handle: when
   _process raises an Exception for one record, that record's messageId
   is in batchItemFailures and every later record in the event is still
   processed with its normal outcome. Example: records m1, m2; m1's
   processing raises RuntimeError; m2 succeeds -> batchItemFailures ==
   [{"itemIdentifier": "m1"}] and m2's effect happened.
2. Each such error logs exactly one WARNING from that module's logger,
   inside the record's obs.trace(): "record failed, <ExceptionClass>,
   message_id=<id>" (the class name from type(exc).__name__).
3. The exception's own text is never logged: an error raised as
   RuntimeError("SECRET note text") leaves no "SECRET" in any log record.
4. Only Exception is caught; BaseException subclasses that aren't
   Exception (KeyboardInterrupt, SystemExit) still propagate.
5. A record with no "messageId" still raises KeyError, as today (SQS
   always sends one).
6. Records whose _process returns True or False keep their current
   outcome and log lines; every existing test passes unchanged.

TESTS
In each of tests/test_worker.py, tests/test_thread.py, tests/test_notify.py
(monkeypatch the module's _process with a wrapper that raises for m1 and
delegates otherwise, so the real m2 path runs):
- test_unexpected_error_fails_only_that_record (req 1, 2): failures ==
  [m1], m2's normal effect checked (worker: note ROUTED; thread: its
  reply posted; notify: its note FAILED and the user told), and exactly
  one WARNING "record failed, RuntimeError, message_id=m1".
- test_unexpected_error_text_not_logged (req 3).
One test (any module) for req 4: KeyboardInterrupt from _process
propagates out of handle().

NON-GOALS
- Changing what _process does for any error it already handles, any
  existing log line, the queues or infra/, or adding an "answered"
  marker for thread replies (Slice 9).

DONE WHEN
- `python -m pytest` and `python -m ruff check src tests` pass.
- The diff touches only the SCOPE paths.
