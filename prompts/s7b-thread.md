GOAL
Slice 7b of SlackKB: the question worker (D-017). It consumes the
QuestionJobs that Slice 7a's events handler enqueues, retrieves the
team's notes (Slice 6), answers from them (Slice 5) and posts the reply
in the Slack thread the question came from. Bedrock is faked in tests
with botocore's Stubber, DynamoDB and S3 with moto, and Slack with an
injected transport.

SCOPE (only these paths may change)
- src/slackkb/thread.py        new; the question worker
- src/slackkb/slack_api.py     add chat_post_message and
                               chat_post_ephemeral; views_open unchanged
- tests/test_thread.py         new
- tests/test_slack_api.py      new

CONTEXT
- Slices 1-7a are merged; all 363 existing tests must stay green.
- tests/conftest.py and tests/fixtures/ are read-only. Fixtures you will
  use: notes_bucket, vectors_table (moto), offline_env (sets
  SLACKKB_EMBED_MODEL_ID, SLACKKB_QA_MODEL_ID, SLACKKB_SLACK_BOT_TOKEN
  among others; SLACKKB_CAPTURE_QUEUE_URL is not set by it, so a test
  that builds Settings() sets it, as tests/test_config.py does).
- docs/DECISIONS.md D-017 is the spec for this slice; D-008 (no-results
  reply names the query), D-013 (bot token), D-016 (QaError, untrusted
  text) and D-004 (partial batch response) also apply. docs/SLICES.md
  row 7b and okf/slackkb/ are authoritative. reference/ is testimony
  only.
- models.QuestionJob is the SQS body (event_id, team_id, channel, user,
  thread_ts, question). retrieve.retrieve(question, team_id, *, client,
  model_id, vectors_table, bucket, k=5) -> list[OkfNote] and
  qa.answer_question(question, notes, *, client, model_id) -> QaResult
  exist; do not change them. Both Bedrock calls (embedding
  invoke_model, then Converse) go through one bedrock-runtime client;
  a single Stubber can queue both responses in order. tests/
  test_retrieve.py and tests/test_qa.py show how to stub each.
- worker.py shows the batch shape: handle(event, ...) returns
  {"batchItemFailures": [{"itemIdentifier": messageId}, ...]}.
- tests/test_modal.py has a FakeTransport for SlackClient; write your
  own in the new tests (do not import from test_modal).
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS
1. slack_api.SlackClient gains:
   - chat_post_message(channel, thread_ts, text): POST
     https://slack.com/api/chat.postMessage with body exactly
     {"channel", "thread_ts", "text"}.
   - chat_post_ephemeral(channel, user, thread_ts, text): POST
     https://slack.com/api/chat.postEphemeral with body exactly
     {"channel", "user", "thread_ts", "text"}.
   Both go through the existing _call (bearer token, SlackApiError on
   ok != true or a transport failure, token never in a message).
2. thread.slack_escape(text) replaces & with &amp;, then < with &lt; and
   > with &gt; (so "<!channel>" becomes "&lt;!channel&gt;").
3. Reply text, exactly:
   - notes found: slack_escape(result.answer), then, if
     result.cited_note_ids is non-empty, "\n\nNotes: " + the ids joined
     with ", " in the order given.
   - no notes: 'No notes match "' + slack_escape(question) + '".'
   - QaError (ephemeral): "Sorry, I couldn't answer that. Please try
     again."
4. thread.handle(event, *, retrieve, answer, slack) -> partial batch
   response, where retrieve is a callable (question, team_id) ->
   list[OkfNote], answer is a callable (question, notes) -> QaResult,
   and slack is a SlackClient. For each SQS record:
   a. The body is parsed as a QuestionJob; a body that does not validate
      -> batch item failure, a warning logs the messageId, nothing is
      retrieved or posted.
   b. retrieve(job.question, job.team_id) once.
   c. No notes -> chat_post_message(job.channel, job.thread_ts, the
      no-notes text); answer is not called.
   d. Notes -> answer(job.question, notes) once, then
      chat_post_message(job.channel, job.thread_ts, the reply text).
   e. answer raises QaError -> chat_post_ephemeral(job.channel,
      job.user, job.thread_ts, the QaError text); no chat_post_message;
      the record succeeds (not a batch item failure); a warning logs the
      event_id.
   f. Any other exception from retrieve, answer or either post (e.g.
      EmbedError, a botocore error, SlackApiError) -> batch item
      failure, a warning logs the exception class name and the event_id;
      other records in the batch are still processed.
   g. Success -> an info log names the event_id and the number of notes.
   h. Never log the question, the answer, any note text or the reply
      text; ids, counts and exception class names are fine.
5. thread.bind(settings, *, bedrock, vectors_table, bucket) -> (retrieve,
   answer): the real callables for handle. retrieve calls
   retrieve.retrieve with client=bedrock, model_id=
   settings.embed_model_id and the given table and bucket; answer calls
   qa.answer_question with client=bedrock, model_id=
   settings.qa_model_id. (The Lambda entry point that builds the clients
   is Slice 8, not this slice.)

TESTS (write first; run them and see them fail before writing src)
In tests/test_thread.py:
- test_reply_posts_in_thread_ts (the acceptance test: fakes for retrieve
  and answer; exactly one chat.postMessage whose body is exactly
  {"channel": job.channel, "thread_ts": job.thread_ts, "text": ...}
  with fixed expected values)
- test_real_retrieve_wired (bind with moto vectors_table + notes_bucket
  holding one note and its vector, one Stubber for the embedding and the
  Converse answer; the posted text is the escaped answer and
  "Notes: <that note_id>"; Stubber expected_params pin both model ids)
- test_no_notes_reply_names_query (answer not called; exact text)
- test_no_notes_query_escaped (a question containing <!channel> & <@U1>)
- test_answer_escaped (an answer containing <!here> and &)
- test_notes_line_order_and_absent_when_no_ids
- test_qa_error_posts_ephemeral_and_succeeds (exact ephemeral body;
  no postMessage; batchItemFailures empty; warning names the event_id)
- test_failures_are_batch_items (parametrized: retrieve raises
  EmbedError; answer raises a botocore ClientError; postMessage gets
  ok:false; the ephemeral post fails; each -> that record's messageId
  in batchItemFailures and a warning with the class name and event_id)
- test_bad_body_is_batch_item (not JSON; missing field; warning names
  the messageId; retrieve not called)
- test_batch_continues_after_failure (two records, the first fails, the
  second is posted)
- test_success_logs_event_id_and_count
- test_text_never_logged (caplog at DEBUG on the "slackkb" logger only,
  over the success, no-notes, QaError and failure paths, with distinct
  marker strings in the question, answer and note text; none appears)
In tests/test_slack_api.py:
- test_chat_post_message_request (exact URL, Authorization header and
  body)
- test_chat_post_ephemeral_request (same)
- test_chat_errors_raise_without_token (ok:false and a transport
  exception, for both methods; the token is not in the message)
Every requirement above has a test that fails if the requirement is
broken, including each "a warning/info logs ..." clause.

NON-GOALS
No Events API changes (7a is done), no second dedup in the worker (a
redelivered job can post twice; accepted for now), no Lambda entry
points, no IaC (the question queue in infra/ is Vajra's, Slice 8), no
deploy. Do not change events.py, dedup.py, queue.py, models.py,
config.py, capture.py, modal.py, worker.py, store.py, blob.py,
okf_note.py, llm.py, qa.py, embed.py, vectors.py, retrieve.py,
slack_verify.py, reference/, tests/conftest.py, tests/fixtures/, infra/.

DONE WHEN
All checks exit 0 in the sandbox with no network, and the diff touches only
SCOPE paths.
