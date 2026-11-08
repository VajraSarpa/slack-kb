GOAL
Slice 9a (D-019): every log line from the six handlers carries a trace_id
(the note_id on the capture path, the event_id on the question path), and
obs.configure() writes the logs as one JSON object per line.

SCOPE (only these paths may change)
- src/slackkb/obs.py           new: trace contextvar, JSON formatter, configure
- src/slackkb/capture.py       trace calls only
- src/slackkb/modal.py         trace calls only
- src/slackkb/events.py        trace calls only
- src/slackkb/worker.py        trace calls only
- src/slackkb/thread.py        trace calls only
- src/slackkb/notify.py        trace calls only
- tests/test_obs.py            new

CONTEXT
- Slices 1-7b and 2b are merged; all 427 existing tests must stay green and
  no existing test file changes.
- docs/DECISIONS.md D-019 is the spec. D-006 (note_id), D-017 (event_id),
  D-018 (never log response_url) also apply.
- tests/conftest.py and tests/fixtures/ are read-only. Fixtures to use:
  slack_request, slack_interaction, slack_event, notes_table, notes_bucket,
  vectors_table, capture_queue, events_table, question_queue. The existing
  tests in test_capture/test_modal/test_events/test_worker/test_thread/
  test_notify show how each handler is called; copy their setup.
- "Trace calls only": in the six handler modules, the only changes are
  importing obs, opening a trace, and binding the id. No log message text
  changes, no other behaviour changes.
- stdlib only (logging, contextvars, json, secrets, datetime). No new
  dependency.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS
1. obs.trace_id() -> str | None returns the current trace id; None outside
   a trace.
2. obs.trace() is a context manager. On entry the trace id is a fresh
   random id matching ^r-[0-9a-f]{16}$ (two traces get different ids); on
   exit the previous value is restored (None at top level), also when the
   body raises.
3. obs.bind(trace_id: object) sets the current trace id when it is a str
   matching ^[A-Za-z0-9_-]{1,64}$; any other value (wrong type, empty, 65
   chars, a space, a newline, a slash) leaves the id unchanged. It returns
   None and never raises.
4. obs.configure(stream=None) -> logging.Handler adds one StreamHandler on
   the root logger (stream defaults to sys.stdout) with obs's JSON
   formatter, sets the root level to INFO and the botocore, boto3 and
   urllib3 loggers to WARNING, and returns the handler. Called again, it
   removes the handler it added before, so the root logger holds exactly
   one obs handler.
5. Each record becomes exactly one line: a JSON object with exactly the
   keys ts, level, logger, msg, trace_id. ts is UTC, format
   YYYY-MM-DDTHH:MM:SS.mmmZ from the record's created time. level is the
   level name, logger the logger name, msg record.getMessage(), trace_id
   the trace id when the record was made (null outside a trace). When the
   record has exc_info, one more key exc holds the exception class name
   only (not its message, no traceback).
6. capture.handle, modal.handle and events.handle each run the whole call
   inside obs.trace(). capture binds the note_id once computed; modal
   binds the note_id it reads (action value for block_actions,
   view.private_metadata for view_submission) right after reading it;
   events binds the event_id right after reading it.
7. worker.handle, notify.handle and thread.handle run each record inside
   its own obs.trace(), and bind the job's note_id (worker, notify) or
   event_id (thread) right after the job parses. A record whose body
   doesn't parse keeps its random id.
8. After any handler returns or raises, obs.trace_id() is None.
9. No line written through obs contains the note text, the question text
   or the response_url (D-018, D-019).

TESTS (write first; run them and see them fail before writing src)
All in tests/test_obs.py. A fixture calls obs.configure(io.StringIO()),
yields the stream, then removes the returned handler and restores the root,
botocore, boto3 and urllib3 levels it changed. Parse the stream's lines with
json.loads.
- test_log_has_trace_id: one /bnote through capture.handle (slack_request,
  notes_table, capture_queue); every slackkb.capture line has trace_id equal
  to the stored note's note_id, and there is at least one such line. (req 6)
- test_trace_id_none_outside_trace (req 1) and
  test_trace_random_restores_on_exit: id matches ^r-[0-9a-f]{16}$, two
  traces differ, nested trace restores the outer id, exit restores None,
  also when the body raises. (req 2)
- test_bind_accepts_valid_and_ignores_invalid: binds "Ev123_ab-C" and a
  64-char id; ignores 123, None, "", 65 chars, "a b", "a\nb", "a/b"; never
  raises. (req 3)
- test_configure_levels_and_single_handler: after two configure calls the
  root holds exactly one handler whose formatter is obs's (the second
  returned handler); root INFO; botocore, boto3, urllib3 WARNING. (req 4)
- test_json_line_exact_shape: one logger.info("x %s", "y") inside a trace
  bound to "abc": exactly one line, keys exactly {ts, level, logger, msg,
  trace_id}, msg "x y", level "INFO", logger the name used, trace_id "abc",
  ts matches ^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$ and parses back to
  the record's created time within 1 ms; outside a trace trace_id is null.
  (req 5)
- test_exc_is_class_name_only: logger.warning("w", exc_info=ValueError(
  "hidden-detail")) gives exc "ValueError" and the line doesn't contain
  "hidden-detail" or "Traceback". (req 5)
- test_rejected_request_has_random_trace: capture.handle with a bad
  signature: its warning line has a trace_id matching ^r-[0-9a-f]{16}$.
  (req 6)
- test_modal_lines_carry_note_id: a block_actions call and a
  view_submission call (slack_interaction) for a stored note: each call's
  modal lines carry that note_id; a block action whose value is "../x y"
  logs with an r- id. (req 3, 6)
- test_events_lines_carry_event_id: an app_mention through events.handle
  (slack_event, events_table, question_queue): its lines carry the
  payload's event_id. (req 6)
- test_worker_records_get_their_own_trace: one worker batch with two jobs
  for two stored notes plus one unparsable body: each job's lines carry its
  own note_id, the unparsable record's line carries an r- id. (req 7)
- test_notify_lines_carry_note_id: one DLQ job for a stored note through
  notify.handle (post = a recording fake): its lines carry the note_id.
  (req 7)
- test_thread_lines_carry_event_id: two QuestionJobs with different
  event_ids in one thread batch (fake retrieve, answer, slack): each
  record's lines carry its own event_id. (req 7)
- test_trace_cleared_after_handlers: obs.trace_id() is None after each of
  the six handlers returns, and after one that raises: worker.handle with
  a record that has no "messageId" raises KeyError (checked 2026-11-08;
  keep that behaviour), so call it inside pytest.raises(KeyError), then
  check trace_id() is None. (req 8)
- test_json_lines_never_carry_text_or_url: run capture, worker, notify,
  events and thread as above; the whole stream contains neither the /bnote
  text, nor the question text, nor the slack_request response_url. (req 9)

NON-GOALS
- Token counts (Slice 9b, llm.py and embed.py).
- Calling obs.configure() from an entry point (Lambda handlers are Slice 8).
- Changing any existing log message, test, or the messageId handling.

DONE WHEN
- `python -m pytest` and `python -m ruff check src tests` pass.
- The diff touches only the SCOPE paths.
