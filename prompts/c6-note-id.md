GOAL
Rung C6 of Slice 1: move the D-006 note_id derivation from capture.py to
models.py, next to Note. A refactor: behavior does not change.

SCOPE (only these paths may change)
- src/slackkb/models.py
- src/slackkb/capture.py

CONTEXT
- capture.py currently defines note_id_for(team_id, trigger_id) and calls it
  once in handle().
- tests/ is read-only for this rung, including tests/conftest.py and
  tests/fixtures/. No test file may be added, edited, or deleted.
- docs/DECISIONS.md (D-006) and okf/slackkb/ are authoritative. reference/
  is testimony.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.

REQUIREMENTS
1. models.py defines note_id(team_id: str, trigger_id: str) -> str:
   sha256 of f"{team_id}:{trigger_id}", hex digest, first 32 chars (D-006).
2. capture.py imports note_id from slackkb.models and no longer defines
   note_id_for or computes the hash itself; drop any import that becomes
   unused.
3. No other change to behavior, names, or signatures in either file.
4. The full suite passes unchanged.

NON-GOALS
No new features, no renames beyond the one above, no test changes, no
changes outside SCOPE. Do not touch reference/.

DONE WHEN
All checks exit 0 in the sandbox with no network, and the diff touches only
the two SCOPE files.
