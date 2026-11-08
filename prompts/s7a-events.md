GOAL
Slice 7a of SlackKB: an Events API handler for @-mentions of the bot
(D-017). Verify the signature, answer url_verification, ignore bot and
subtype events, deduplicate Slack's retries on event_id with a
conditional put instead of dropping them (D-011), and enqueue a
QuestionJob to the question queue. Answering the question is Slice 7b,
not this slice. DynamoDB and SQS are moto in tests.

SCOPE (only these paths may change)
- src/slackkb/events.py        new; the Events API handler
- src/slackkb/dedup.py         new; the only module that touches the
                               events table
- src/slackkb/queue.py         add send_question_job; send_capture_job
                               unchanged
- src/slackkb/models.py        add QuestionJob; nothing else changes
- src/slackkb/config.py        add events_table, question_queue_url
- tests/test_events.py         new
- tests/test_dedup.py          new
- tests/test_queue.py          new
- tests/test_models.py         QuestionJob tests only
- tests/test_config.py         tests for the two new settings only

CONTEXT
- Slices 1-6 are merged; all 308 existing tests must stay green.
- tests/conftest.py and tests/fixtures/ are read-only. New in them:
  - fixtures/app_mention.json: an event_callback whose event is an
    app_mention in a thread (team_id T000TEST, channel C000TEST, user
    U000TEST, ts 1762600000.000200, thread_ts 1762600000.000100,
    event_id Ev000TEST0001, text "<@U0BOTTEST> how do we rotate the
    signing secret?"). fixtures/url_verification.json: a challenge.
  - slack_event(kind="app_mention", *, text=, event_id=, bot_id=,
    subtype=, thread_ts=, retry=, ts=, secret=, body=) builds a signed
    API Gateway proxy event with a JSON body. thread_ts=None removes the
    event's thread_ts (a top-level mention); retry=N sets
    X-Slack-Retry-Num; body="..." signs and sends that raw string.
  - events_table: moto table, partition key event_id (S), TTL enabled
    on expires_at. question_queue: moto queue with its own redrive DLQ;
    returns Queues(url, dlq_url).
  - The autouse offline_env now also sets SLACKKB_EVENTS_TABLE and
    SLACKKB_QUESTION_QUEUE_URL (= the question_queue fixture's URL).
    SLACKKB_CAPTURE_QUEUE_URL is not set by offline_env; tests that
    build Settings() set it, as tests/test_config.py does.
- docs/DECISIONS.md D-011 and D-017 are the spec for this slice; D-004,
  D-007 and D-013 also apply. docs/SLICES.md row 7a and okf/slackkb/ are
  authoritative. reference/ is testimony only (its ingestion handler
  drops every retry before auth: A0 #2, the defect this slice fixes).
- Follow the shape of src/slackkb/capture.py: handle(...) takes the
  proxy event and returns {"statusCode", "headers", "body"}; the body
  may be base64 (isBase64Encoded); verify with slack_verify.verify.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS
1. Settings gains required events_table: str (SLACKKB_EVENTS_TABLE) and
   question_queue_url: str (SLACKKB_QUESTION_QUEUE_URL), no defaults
   (D-007).
2. models.QuestionJob (the SQS body from events to the 7b worker):
   event_id, team_id, channel, user, thread_ts, question, all str and
   non-empty; extra fields rejected.
3. queue.send_question_job(sqs, queue_url, job) sends one message whose
   body is job.model_dump_json(); ClientError or BotoCoreError ->
   EnqueueError (the existing class), as send_capture_job does.
4. dedup.py (the caller passes the events Table in):
   - claim(table, event_id, now) -> bool puts {event_id, expires_at:
     now + 3600} (expires_at a number) with a condition that event_id
     does not exist; True if claimed, False if already claimed.
   - release(table, event_id) deletes the claim; a missing item is not
     an error.
   - Any other ClientError/BotoCoreError from either -> DedupError
     (raised from the original).
5. events.handle(event, *, events_table, sqs, settings, now) -> proxy
   response:
   a. The signature is verified before the body is parsed or anything
      else is read from it. SignatureError or a bad body encoding -> 401
      "unauthorized", nothing claimed or sent, a warning logs the reason.
   b. A verified body that is not a JSON object -> 400, nothing claimed
      or sent.
   c. type "url_verification" -> 200 with the challenge string as a
      text/plain body; a missing or non-string challenge -> 400. It is
      answered only after the signature check (a bad signature -> 401).
   d. type "event_callback" whose event.type is "app_mention":
      - event has a bot_id or a subtype -> 200, nothing claimed or sent.
      - event_id, team_id (top level), event.channel, event.user,
        event.ts and event.text must be non-empty strings, else 400 and
        nothing claimed or sent.
      - question = event.text with every mention token (<@U...> or
        <@U...|name>) removed, then stripped. Empty -> 200, nothing
        claimed or sent.
      - claim(event_id). Already claimed -> 200, nothing sent, an info
        log names the event_id. DedupError -> 500, nothing sent.
      - Send QuestionJob(event_id, team_id, channel, user, thread_ts =
        event.thread_ts if present, else event.ts, question) to
        settings.question_queue_url -> 200.
      - EnqueueError -> release(event_id), then 500, so Slack's retry
        does the work (D-011). A DedupError from release is logged as a
        warning naming the event_id and the response is still 500.
   e. Any other type or event type -> 200, nothing claimed or sent.
   f. X-Slack-Retry-Num changes nothing: a retry is handled like a first
      delivery (the claim is what deduplicates).
   g. Never log the event text or the question; ids and error class
      names are fine.

TESTS (write first; run them and see them fail before writing src)
In tests/test_events.py:
- test_retry_is_deduplicated (the acceptance test: deliver the same
  event twice, the second with retry=1; exactly one message on the
  question queue, both responses 200)
- test_enqueue_failure_releases_claim_and_retry_recovers (first delivery
  with a failing SQS client -> 500 and no claim left; the retry with a
  working client -> 200 and one message)
- test_release_failure_still_500_and_logged
- test_claim_failure_returns_500_sends_nothing
- test_job_body_exact (decode the queued body and compare it to the
  exact dict expected from the fixture, including the stripped question)
- test_top_level_mention_uses_ts
- test_mention_tokens_removed (both <@U...> and <@U...|name>, mention in
  the middle of the text)
- test_empty_question_does_nothing
- test_bot_and_subtype_events_ignored
- test_missing_fields_400 (one case per required field)
- test_bad_signature_401_before_parse (bad secret with a body that is not
  JSON still gets 401; stale timestamp too)
- test_not_json_object_400 (not JSON; a JSON list)
- test_url_verification_returns_challenge
- test_url_verification_needs_signature
- test_url_verification_bad_challenge_400
- test_other_events_ignored (another event type; another envelope type)
- test_question_never_logged (caplog at DEBUG on the "slackkb" logger
  only, over the success, duplicate, enqueue-failure and release-failure
  paths; neither the raw text nor the question appears)
In tests/test_dedup.py:
- test_claim_then_claim_again
- test_claim_sets_expires_at (exact value now + 3600, stored as a number)
- test_release_then_claim_again
- test_release_missing_is_ok
- test_errors_wrap_as_dedup_error (claim and release)
In tests/test_queue.py:
- test_send_question_job_body (exact JSON body read back from the queue
  and compared to fixed expected values, not to model_dump_json())
- test_send_question_job_wraps_errors
In tests/test_models.py:
- test_question_job_rejects_empty_and_extra
In tests/test_config.py:
- test_reads_events_settings
- test_missing_events_settings_fail (each of the two)
Every requirement above has a test that fails if the requirement is
broken.

NON-GOALS
No question worker, no retrieval call, no Bedrock, no Slack Web API
call, no chat.postMessage, no thread.py (all Slice 7b). No Lambda entry
points, no IaC (the events table and question queue in infra/ are
Vajra's, Slice 8), no deploy. Do not change capture.py, modal.py,
worker.py, store.py, blob.py, okf_note.py, llm.py, qa.py, embed.py,
vectors.py, retrieve.py, slack_api.py, slack_verify.py, reference/,
tests/conftest.py, tests/fixtures/, infra/.

DONE WHEN
All checks exit 0 in the sandbox with no network, and the diff touches only
SCOPE paths.
