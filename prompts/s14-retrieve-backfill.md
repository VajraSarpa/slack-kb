GOAL
retrieve() skips a top-k note whose S3 object is missing and returns
fewer than k notes, even when lower-ranked notes exist. Per the D-008
amendment of 2026-11-12, the next-ranked note takes the missing one's
place: retrieve returns up to k notes whose objects exist.

SCOPE (only these paths may change)
- src/slackkb/retrieve.py
- tests/test_retrieve.py

CONTEXT
- 550 tests pass on main. docs/DECISIONS.md D-008 and its 2026-11-12
  amendment are the spec.
- src/slackkb/retrieve.py: retrieve(question, team_id, *, client,
  model_id, vectors_table, bucket, k=5) ranks the team's vectors by dot
  product (ties by note_id), then fetches scored[:k] with
  blob.get_note(bucket, team_id, note_id), which returns None for a
  missing object; a None is logged at WARNING
  "note object missing, skipped, note_id=%s" and skipped.
- tests/test_retrieve.py helpers: unit(i, scale), add_note(bucket,
  vectors_table, note_id, vector), put_vector (a vector with no object),
  run(client, vectors_table, bucket, query_vec, **kwargs), TEAM.
  test_missing_object_skipped_and_logged pins the old behaviour
  ("third does not replace the missing ghost"); it changes with this task.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS
1. A missing object's place goes to the next-ranked note: notes "first"
   (score 0.9), "ghost" (0.8, vector only, no object), "third" (0.7),
   k=2 -> ["first", "third"], best first.
2. Each missing object still logs exactly one WARNING
   "note object missing, skipped, note_id=<id>"; the message text does
   not change.
3. It stops when k notes are found: with k=1 and the top note present,
   no other note's object is read.
4. When the ranking runs out first, it returns what it found: "a" (0.9),
   "ghost" (0.8, no object), "b" (0.7), k=3 -> ["a", "b"].
5. k < 1 still raises ValueError; no vectors still returns [] without
   calling Bedrock; other existing tests do not change.

TESTS
In tests/test_retrieve.py:
- test_missing_object_skipped_and_logged: changed to req 1 and 2
  (["first", "third"], one WARNING naming ghost).
- test_stops_reading_at_k (req 3): wrap the bucket so each Object(key)
  call is recorded, and assert only the top note's key was read. This
  already holds today; the test keeps the change from reading every
  object and slicing afterwards.
- test_ranking_runs_out_returns_what_exists (req 4).

NON-GOALS
- Deleting stale vectors, changing blob.py, vectors.py or thread.py,
  changing k's default, any other log line.

DONE WHEN
- `python -m pytest` and `python -m ruff check src tests` pass.
- The diff touches only the SCOPE paths.
