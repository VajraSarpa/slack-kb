GOAL
Tests only. D-023 (2026-11-12) is implemented in worker.handle,
thread.handle and notify.handle (merged 458f01e), but two of its
requirements are pinned in one module or none: only worker has a test
that KeyboardInterrupt propagates, and no module tests that a record
with no messageId still raises KeyError. Add those tests; change no
source file.

SCOPE (only these paths may change)
- tests/test_worker.py
- tests/test_thread.py
- tests/test_notify.py

CONTEXT
- 559 tests pass on main. docs/DECISIONS.md D-023 is the spec: "Only
  Exception is caught; a record with no messageId still raises."
- Each handle() wraps `_process(record, ...)` in
  `try/except Exception` inside `with obs.trace():`; the except block
  logs "record failed, <Class>, message_id=<id>" reading
  record["messageId"], and the failures.append after it reads
  record["messageId"] too.
- tests/test_worker.py already has test_keyboard_interrupt_propagates
  and helpers _raising_for_m1(monkeypatch, exc), _two_records(),
  _handle_v(event, table=..., bucket=...). tests/test_thread.py and
  tests/test_notify.py have their own _raising_for_m1-style helpers from
  the same change, plus record()/run() (thread) and
  _record()/_event()/_run() (notify).
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS
1. In thread and notify: KeyboardInterrupt raised by _process propagates
   out of handle() (as the worker test already shows), and no WARNING
   "record failed" is logged for it.
2. In each of worker, thread and notify: a record with no "messageId"
   key (and any body) makes handle() raise KeyError, with the real
   _process (not monkeypatched): _process reads record["messageId"]
   first, and the except block reads it again.
3. Every existing test passes unchanged; no file outside SCOPE changes.

TESTS
- tests/test_thread.py, tests/test_notify.py:
  test_keyboard_interrupt_propagates (req 1).
- tests/test_worker.py, tests/test_thread.py, tests/test_notify.py:
  test_record_without_message_id_raises (req 2).

NON-GOALS
- Any change under src/, any change to existing tests' assertions.

DONE WHEN
- `python -m pytest` and `python -m ruff check src tests` pass.
- The diff touches only the SCOPE paths.
