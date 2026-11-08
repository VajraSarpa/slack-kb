GOAL
Slice 2b (D-010, D-018): a note whose capture job lands in the DLQ is
marked FAILED, its S3 object and vector are removed, and the user who ran
/bnote gets an ephemeral notice through the job's response_url.

SCOPE (only these paths may change)
- src/slackkb/models.py        CaptureRequest + CaptureJob gain response_url
- src/slackkb/capture.py       copy response_url onto the CaptureJob only
- src/slackkb/slack_api.py     response_url transport + post_response_url
- src/slackkb/notify.py        new: the capture-DLQ batch handler
- tests/test_notify.py         new
- tests/test_slack_api.py      new tests only
- tests/test_models.py         new tests only
- tests/test_capture.py        one new test, plus the one line named below
- tests/test_modal.py          the one line named below, nothing else
- tests/test_worker.py         the one line named below, nothing else

CONTEXT
- Slices 1-7b are merged; all 393 existing tests must stay green.
- docs/DECISIONS.md D-018 is the spec; D-009 (conditional status moves),
  D-010, D-014 (FAILED keeps no S3 object), D-017's amendment (10 s
  timeout, at-least-once) also apply.
- tests/conftest.py and tests/fixtures/ are read-only. Fixtures to use:
  notes_table, notes_bucket, vectors_table, capture_queue (.url, .dlq_url,
  redrive at MAX_RECEIVES = 3), slack_request (its form carries
  response_url "https://hooks.slack.invalid/commands/T000TEST/1/abc").
- Reuse store.transition_status / store.get_note, blob.delete_note,
  vectors.delete_vector (both deletes treat a missing item as success).
  worker.py does not change; its _remove_object stays private.
- Four existing lines pinned "capture never uses response_url" (Slice 1
  req 8); capture must now name the field. Change exactly these lines
  and no other existing line in those files:
  - tests/test_capture.py:333, tests/test_modal.py:597 and
    tests/test_worker.py:708, each `assert "response_url" not in source`
    -> `assert "post_response_url" not in source and "urlopen" not in source`
  - tests/test_models.py:47 `assert not hasattr(req, "response_url")`
    -> `assert req.response_url == "https://hooks.slack.invalid/commands/T000TEST/1/abc"`
- No network: pytest runs with --disable-socket. Test the transport by
  monkeypatching urllib.request.urlopen in slackkb.slack_api with a fake
  that records its Request and timeout; for a 4xx/5xx it raises
  urllib.error.HTTPError(url, code, msg, hdrs, None).
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS
1. models: CaptureRequest and CaptureJob each gain
   response_url: str | None = None, which must start with "https://"
   when present (else ValidationError). A CaptureJob body without it
   still parses (response_url None).
2. capture.handle puts the form's response_url on the CaptureJob it
   sends; it makes no call to it.
3. slack_api.RESPONSE_URL_TIMEOUT_SECONDS = 10.0.
   make_response_url_transport(timeout) returns a callable
   (url, json_body) -> int that rejects non-https URLs (ValueError),
   POSTs json_body as JSON with Content-Type
   "application/json; charset=utf-8" and no Authorization header, passes
   exactly that timeout to urlopen, and returns the HTTP status; an
   HTTPError returns its code instead of raising. The reply body is not
   parsed. response_url_transport = make_response_url_transport(
   RESPONSE_URL_TIMEOUT_SECONDS).
4. slack_api.ResponseUrlError(SlackApiError) has .status: int | None.
   post_response_url(url, text, transport=response_url_transport) sends
   exactly {"response_type": "ephemeral", "text": text}; a status in
   200-299 returns None; any other status raises ResponseUrlError with
   that status; a transport exception raises ResponseUrlError with status
   None. No ResponseUrlError message contains the URL.
5. notify.FAILED_TEXT = "Sorry, your /bnote note couldn't be saved.
   Please run /bnote again." (one line, one space after the period).
   notify.handle(event, *, table, bucket, vectors_table, post) -> dict
   returns {"batchItemFailures": [{"itemIdentifier": messageId}, ...]}
   for exactly the records that must be retried. post is called as
   post(response_url, FAILED_TEXT).
6. Per record, in order:
   a. Body doesn't parse as a CaptureJob -> warning naming message_id;
      done (not retried).
   b. transition_status(table, note_id, FAILED). NoteNotFoundError ->
      warning; done. ClientError / BotoCoreError -> warning naming the
      class; retried. Moved -> info "note failed".
   c. Not moved: get_note. ROUTED -> info, no notice, nothing deleted;
      done. FAILED (a repeat DLQ delivery) -> continue to d. Missing ->
      warning; done. Store error -> retried.
   d. delete_note then delete_vector for the note's team_id/note_id. A
      ClientError / BotoCoreError -> warning; retried, and post is not
      called.
   e. response_url is None -> warning that the user can't be told; done.
   f. post. Success -> info "user notified". ResponseUrlError with a
      status 400-499 -> warning naming the status; done. Any other
      ResponseUrlError (5xx or status None) -> warning; retried.
7. Every notify log line names note_id (when parsed) and message_id.
   No log line from capture or notify contains the response_url or the
   note text.

TESTS (write first; run them and see them fail before writing src)
In tests/test_notify.py:
- test_failed_note_notifies_user: capture a note with slack_request,
  receive the job from capture_queue.url MAX_RECEIVES times with
  VisibilityTimeout=0 and no delete, then once more (moto moves it to
  the DLQ on that receive, which returns nothing; checked 2026-11-08),
  receive it from dlq_url, pass it as
  an SQS event to notify.handle: status FAILED, post called exactly once
  with the fixture's response_url and FAILED_TEXT, batchItemFailures [].
- test_failed_note_object_and_vector_removed (object and vector existed
  before; both gone after)
- test_routed_note_gets_no_notice (post not called; status still ROUTED;
  object still there)
- test_repeat_dlq_delivery_posts_again (note already FAILED -> posted)
- test_missing_response_url_finishes_without_notice
- test_post_4xx_is_not_retried (403 and 404)
- test_post_5xx_and_transport_error_are_retried
- test_store_error_is_retried (transition raises ClientError; note
  unchanged)
- test_delete_error_is_retried_before_post
- test_unparsable_job_and_missing_note_finish
- test_mixed_batch_reports_only_retries (exact itemIdentifier list)
- test_notify_logs_name_ids_never_url_or_text (caplog over all paths)
In tests/test_slack_api.py:
- test_post_response_url_request_shape (exact URL, POST, exact body
  bytes, Content-Type, no Authorization header, timeout 10.0)
- test_post_response_url_status_handling (204 ok; 404 -> status 404;
  500 -> 500; transport exception -> None; message lacks the URL)
- test_response_url_transport_ignores_reply_body (body b"ok" is success)
- test_response_url_transport_rejects_non_https
In tests/test_models.py:
- test_response_url_optional_and_https_only (both models: absent -> None,
  https kept, "http://..." rejected)
In tests/test_capture.py:
- test_capture_job_carries_response_url (the job body on the queue has
  the fixture's response_url)
Every requirement above has a test that fails if the requirement is
broken; each "exactly" value is compared to a fixed expected value.

NON-GOALS
No Lambda entry points or client wiring, no IaC, no change to how the
worker processes jobs. Do not change worker.py, store.py, blob.py,
vectors.py, queue.py, config.py, events.py, dedup.py, thread.py, modal.py,
okf_note.py, llm.py, qa.py, embed.py, retrieve.py, slack_verify.py,
reference/, tests/conftest.py, tests/fixtures/, infra/.

DONE WHEN
All checks exit 0 in the sandbox with no network, and the diff touches only
SCOPE paths.
