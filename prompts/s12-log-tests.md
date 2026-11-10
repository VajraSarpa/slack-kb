GOAL
Tests only: pin two thread log lines that today's tests can't fail.
Every thread test uses the default job, whose event_id is "Ev1", so a
log call that hardcoded "Ev1" would pass; and no test asserts the
"question answered" INFO line at all.

SCOPE (only these paths may change)
- tests/test_thread.py

CONTEXT
- 545 tests pass on main. docs/DECISIONS.md D-019 (logs carry ids) and
  D-022 (the "answer cited no notes" INFO line) are the spec.
- thread._process logs, at INFO:
  "answer cited no notes, event_id=%s notes=%d" (D-022, when notes were
  retrieved and none cited), and, at the end of every handled job,
  "question answered, event_id=%s notes=%d" with len(notes) (0 when
  retrieval found nothing).
- test_thread.py helpers: make_job(**overrides), record(job),
  Fakes(notes=..., result=...), run(records, fakes), reply_for(...),
  warnings(caplog), LOGGER = "slackkb". src is not in scope: if a test
  can't pass without a src change, stop and say which.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS
1. A test shows the "answer cited no notes" line carries the job's own
   event_id: with a job whose event_id is "Ev42", that INFO message
   contains "event_id=Ev42" and does not contain "Ev1".
2. A test shows the "question answered" line on the answered path: with
   event_id "Ev42" and two notes retrieved (cited ["n1"]), exactly one
   INFO message contains "question answered", and it contains
   "event_id=Ev42" and "notes=2".
3. The same on the no-notes path: with no notes retrieved, exactly one
   INFO message contains "question answered", with "event_id=Ev42" and
   "notes=0".
4. No existing test changes; src does not change.

TESTS
In tests/test_thread.py:
- test_uncited_log_uses_job_event_id (req 1)
- test_question_answered_logged (req 2)
- test_question_answered_logged_when_no_notes (req 3)
Each uses caplog.at_level(logging.DEBUG, logger=LOGGER) and reads INFO
records with r.levelno == logging.INFO. These tests pass on the current
src (it is already right); the harness mutates the src lines they run
to show they can fail, so don't edit src to check that.

NON-GOALS
- Any src change, other log lines, the reply text.

DONE WHEN
- `python -m pytest` and `python -m ruff check src tests` pass.
- The diff touches only tests/test_thread.py.
