GOAL
Add docstrings to src/slackkb/models.py where they are missing, and fix the
one docstring that is out of date. Documentation only: behavior does not
change.

SCOPE (only this path may change)
- src/slackkb/models.py

CONTEXT
- Severity, NoteStatus and _utc_now_iso have no docstring.
- The Note docstring still says the note_id derivation "is rung C6"; that
  derivation now lives in note_id() in the same file.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.

REQUIREMENTS
1. Every class and function in models.py has a one-line docstring.
2. The Note docstring no longer refers to rung C6 and points to note_id()
   (D-006).
3. No change to code, names, signatures or enum values.
4. The full suite and ruff pass unchanged.

NON-GOALS
No new files, no test changes, no changes outside SCOPE.

DONE WHEN
All checks exit 0 in the sandbox with no network, and the diff touches only
src/slackkb/models.py.
