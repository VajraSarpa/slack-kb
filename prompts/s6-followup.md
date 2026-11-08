GOAL
Slice 6 follow-up: make the worker's vector arguments required so no note
can reach ROUTED without a vector (D-008 order: S3, then the vector, then
ROUTED), pin the stored byte format, and turn bad vector values into a
single-record failure instead of a failed batch.

SCOPE (only these paths may change)
- src/slackkb/worker.py
- src/slackkb/vectors.py
- src/slackkb/embed.py
- tests/test_worker.py
- tests/test_vectors.py
- tests/test_embed.py
- tests/test_modal.py          only the worker.handle call in
                               test_modal_submission_on_routed_note_updates_severity
                               and that test's fixture list; nothing else

CONTEXT
- Slice 6 is merged (520b6d4); all 289 existing tests must stay green.
- tests/conftest.py and tests/fixtures/ are read-only; conftest has the
  vectors_table fixture (moto note_vectors table, PK team_id, SK note_id).
- docs/DECISIONS.md D-008 is the spec; D-004 and D-014 also apply.
  docs/SLICES.md row 6 is authoritative. reference/ is testimony only.
- The apply review of personal_19c4442c flagged: handle() defaults
  vectors_table/embed to None and then routes with no vector; a float32
  overflow escapes handle(); a vector-delete failure is logged as a blob
  error. This run fixes those.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS
1. worker.handle(event, *, table, bucket, vectors_table, embed): both new
   arguments are required keyword arguments with no default. The worker
   always writes the vector for a CAPTURED note and always deletes it
   where it removes a FAILED note's object; no code path skips either
   because an argument is None.
2. The test_modal.py call passes the vectors_table fixture and an embed
   fake returning [0.0] * embed.DIMENSIONS; the test's assertions stay as
   they are.
3. vectors.put_vector stores exactly struct.pack("<512f", *vector)
   (little-endian float32). Add vectors.VectorError(ValueError):
   put_vector raises it, before any write, for a vector that is not
   DIMENSIONS values or holds a value that is not finite or is outside
   the float32 range.
4. embed.embed_text raises EmbedError for an embedding holding NaN,
   Infinity, a value outside the float32 range, or a number float()
   cannot convert (e.g. 10**400 in the JSON body).
5. In the worker, a VectorError from put_vector is that record's batch
   item failure (note stays CAPTURED; warning logs the error type name
   and note_id, never the text), like EmbedError today. Other records in
   the same event are still processed.
6. A delete_vector failure logs its own warning ("vector delete error
   <type>, note_id=... message_id=..."), not the blob delete message; a
   delete_note failure keeps its current message.

TESTS (write first; run them and see them fail before writing src)
In tests/test_worker.py:
- test_handle_requires_vector_args (calling handle without vectors_table,
  and without embed, each raises TypeError)
- test_worker_bad_vector_is_record_failure (embed fake returns
  [1e39] * DIMENSIONS for one of two records: that record is in
  batchItemFailures and stays CAPTURED; the other is ROUTED)
- test_vector_delete_failure_logged_as_vector_error
In tests/test_vectors.py:
- test_vector_bytes_are_little_endian_float32 (read the raw item with
  boto3 and compare its bytes to a hand-packed "<512f" value of a vector
  whose bytes differ between byte orders)
- test_put_vector_rejects_bad_vector (wrong length; 1e39; NaN; nothing
  written)
In tests/test_embed.py:
- test_embed_rejects_non_finite_or_out_of_range (NaN, Infinity, 1e39,
  10**400 in the body)
Every requirement above has a test that fails if the requirement is
broken.

NON-GOALS
No Events API, no Lambda entry points, no retrieve.py or config.py
changes, no IaC, no deploy. Do not change capture.py, modal.py, store.py,
blob.py, okf_note.py, llm.py, qa.py, slack_api.py, models.py,
retrieve.py, config.py, reference/, tests/conftest.py, tests/fixtures/,
infra/.

DONE WHEN
All checks exit 0 in the sandbox with no network, and the diff touches only
SCOPE paths.
