GOAL
Slice 6 of SlackKB: embed each note's text when the worker routes it,
store the vector in its own DynamoDB table, and retrieve a team's top-k
notes for a question by dot product (D-008). Bedrock is faked in tests
with botocore's Stubber; DynamoDB and S3 with moto.

SCOPE (only these paths may change)
- src/slackkb/embed.py         new; the only module that calls Bedrock
                               invoke_model (embeddings)
- src/slackkb/vectors.py       new; the only module that touches the
                               note_vectors table
- src/slackkb/retrieve.py      new; question + team -> top-k notes
- src/slackkb/worker.py        vector write between S3 and ROUTED
- src/slackkb/config.py        add vectors_table, embed_model_id
- tests/test_embed.py          new
- tests/test_vectors.py        new
- tests/test_retrieve.py       new
- tests/test_worker.py         new worker tests; existing tests may only
                               gain the new handle() arguments (through
                               one helper), nothing else in them changes
- tests/test_config.py         only if the new settings require it

CONTEXT
- Slices 1-5 and the D-014 amendment are merged; all 246 existing tests
  must stay green.
- tests/conftest.py and tests/fixtures/ are read-only. The autouse
  offline_env now also sets SLACKKB_VECTORS_TABLE and
  SLACKKB_EMBED_MODEL_ID; the vectors_table fixture creates the moto
  note_vectors table (partition key team_id, sort key note_id, both S).
- docs/DECISIONS.md D-008 is the spec for this slice; D-002, D-004,
  D-007, D-009, D-012 and D-014 also apply. docs/SLICES.md row 6 and
  okf/slackkb/ are authoritative. reference/ is testimony only.
- D-008 says an embedding or vector-write failure "raises, so SQS
  retries". In this worker that means the record is reported in
  batchItemFailures (D-004 partial batch response), exactly as an S3
  error is today; handle() itself does not raise.
- Wiring retrieve into the Events API is Slice 7, not this slice, and so
  is the "no results" reply that names the query.
- A ROUTED note has no text in DynamoDB (D-014); its text is in S3
  (slackkb.blob.get_note returns an OkfNote or None).
- Fake Bedrock: a real boto3.client("bedrock-runtime", region_name=
  "us-east-1") wrapped in botocore.stub.Stubber. invoke_model returns its
  body as a botocore.response.StreamingBody; build it in the test from
  io.BytesIO(json bytes) and the byte length. Use expected_params where a
  test checks the request. No network (pytest runs with --disable-socket).
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS
1. Settings gains required vectors_table: str (SLACKKB_VECTORS_TABLE) and
   embed_model_id: str (SLACKKB_EMBED_MODEL_ID), no defaults (D-007,
   D-012).
2. embed.DIMENSIONS = 512. embed.embed_text(client, *, model_id, text)
   -> list[float] calls client.invoke_model once with modelId=model_id,
   contentType="application/json", accept="application/json" and body
   = json.dumps({"inputText": text, "dimensions": 512, "normalize": True}),
   and returns the response's "embedding" list as floats.
   - ClientError or BotoCoreError -> EmbedError (raised from the
     original).
   - A body that is not JSON, has no "embedding", or whose embedding is
     not exactly DIMENSIONS numbers -> EmbedError.
   - embed.py is the only module that calls invoke_model; it never logs
     the text.
3. vectors.py (the caller passes the note_vectors Table in):
   - put_vector(table, team_id, note_id, vector) writes item {team_id,
     note_id, vector} with vector packed as little-endian float32 bytes
     (DynamoDB Binary); an overwrite is fine (idempotent).
   - list_vectors(table, team_id) -> list[tuple[str, list[float]]]
     queries that team's partition only, following LastEvaluatedKey to
     the end, and unpacks each vector. An item whose vector is not
     DIMENSIONS float32 values is skipped and a warning logs its note_id.
   - delete_vector(table, team_id, note_id); a missing item is not an
     error.
4. retrieve.retrieve(question, team_id, *, client, model_id,
   vectors_table, bucket, k=5) -> list[OkfNote]:
   - k < 1 -> ValueError.
   - The team has no vectors -> [] and Bedrock is not called.
   - Otherwise one embed_text call on the question, rank the team's
     vectors by dot product (descending; ties by note_id ascending), take
     the top k note_ids, and return their notes read from S3 with
     blob.get_note in that rank order (D-008: text comes from S3).
   - A note whose object is missing (None) is skipped and a warning logs
     its note_id; the next-ranked note does not replace it, so fewer
     than k notes may come back.
   - Only that team's partition is read; another team's notes never come
     back.
   - EmbedError propagates. Never log the question or any note text.
5. worker.handle(event, *, table, bucket, vectors_table, embed) where
   embed is a callable text -> list[float] (the Lambda entry point will
   bind embed_text to a client and model id; that entry point is not in
   this slice). For a CAPTURED note the order is: S3 object (as now),
   then embed(note.text) and put_vector, then route_note.
   - Only note.text is embedded: no frontmatter field, no OKF Markdown.
   - EmbedError, or a ClientError/BotoCoreError from put_vector -> that
     record is a batch item failure, the note stays CAPTURED, and a
     warning logs the error type name and note_id (never the text).
   - A redelivered ROUTED note still writes nothing: no S3 put, no embed
     call, no vector write (D-014).
   - Wherever the worker removes a FAILED note's S3 object today (FAILED
     at read, FAILED after a lost race), it also calls delete_vector; a
     ClientError/BotoCoreError there -> batch item failure, as for the
     object delete.
   - All other existing worker behavior is unchanged.

TESTS (write first; run them and see them fail before writing src)
In tests/test_retrieve.py:
- test_retrieval_excludes_frontmatter (the acceptance test: route a note
  through worker.handle with an embed fake that records its input; the
  recorded text equals note.text and contains none of the note's
  note_id, team_id, channel_id, user_id, created_at or "---"; then
  retrieve with a Stubber returns that note)
- test_ranks_by_dot_product_top_k (three vectors, k=2, exact order)
- test_ties_break_by_note_id
- test_other_team_never_returned
- test_no_vectors_skips_bedrock (Stubber with no responses;
  assert_no_pending_responses)
- test_missing_object_skipped_and_logged
- test_k_below_one_rejected
- test_question_never_logged (caplog)
In tests/test_embed.py:
- test_embed_sends_titan_request (expected_params pin modelId,
  contentType, accept and the exact body)
- test_embed_returns_vector
- test_embed_wrong_length_raises
- test_embed_bad_body_raises (not JSON; no "embedding")
- test_embed_wraps_client_errors
In tests/test_vectors.py:
- test_put_then_list_round_trips (float32 precision)
- test_put_overwrites
- test_list_reads_one_partition_only
- test_list_follows_pagination
- test_bad_vector_item_skipped_and_logged
- test_delete_missing_is_ok
In tests/test_worker.py:
- test_worker_writes_s3_then_vector_then_routes (order checked)
- test_worker_embed_failure_keeps_captured
- test_worker_vector_write_failure_keeps_captured
- test_worker_routed_redelivery_writes_no_vector
- test_worker_failed_note_deletes_vector
Every requirement above has a test that fails if the requirement is
broken.

NON-GOALS
No Events API, no thread replies, no "no results" reply text, no Lambda
entry points, no IaC (the note_vectors table in infra/ is Vajra's, Slice
8), no deploy, no S3 Vectors or OpenSearch, no model-ID lookup. Do not
change capture.py, modal.py, store.py, blob.py, okf_note.py, llm.py,
qa.py, slack_api.py, models.py, reference/, tests/conftest.py,
tests/fixtures/, infra/.

DONE WHEN
All checks exit 0 in the sandbox with no network, and the diff touches only
SCOPE paths.
