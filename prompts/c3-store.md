GOAL
Rung C3 of Slice 1: write a Note to DynamoDB only if its note_id is new.

SCOPE (only these paths may change)
- src/slackkb/store.py
- tests/test_store.py

CONTEXT
- tests/conftest.py and tests/fixtures/ are read-only. Use the notes_table
  fixture (a moto-backed boto3 Table, hash key note_id).
- Note lives in src/slackkb/models.py; do not change it.
- docs/DECISIONS.md and okf/slackkb/ are authoritative. reference/ is
  testimony.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.

REQUIREMENTS
1. put_if_absent(table, note: Note) -> bool. One put_item with
   ConditionExpression attribute_not_exists(note_id). Returns True if
   written, False if an item with that note_id already exists. Any other
   error propagates.
2. A duplicate leaves the first item unchanged.
3. get_note(table, note_id: str) -> Note | None. Returns None if absent.
   A Note written by put_if_absent reads back equal to the original.
4. store.py is the only module that talks to DynamoDB. The caller passes
   the table in; no clients, resources or table names at import time.

TESTS (write first; they must fail before implementation)
- test_put_if_absent_writes
- test_put_if_absent_false_on_duplicate
- test_store_round_trips_note
- test_put_if_absent_propagates_other_errors (a ClientError other than
  ConditionalCheckFailedException, e.g. a table that does not exist,
  must raise, not return False)
All four use the notes_table fixture (or its moto context).
Every requirement above has a test that fails if the requirement is
broken.

NON-GOALS
No handler, no config, no note_id derivation (C6), no table creation.
Do not touch reference/, tests/conftest.py, or tests/fixtures/.

DONE WHEN
All checks exit 0 in the sandbox with no network.
