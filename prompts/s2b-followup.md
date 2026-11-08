GOAL
Slice 2b follow-up (D-018): pin notify's log lines and the response_url
transport's timeout argument with tests. Tests only; no source change.

SCOPE (only these paths may change)
- tests/test_notify.py         new assertions in existing tests, or new tests
- tests/test_slack_api.py      one new test

CONTEXT
- Slice 2b is merged; all 421 existing tests must stay green.
- docs/DECISIONS.md D-018 is the spec. src/slackkb/notify.py and
  src/slackkb/slack_api.py are correct as they stand and must not change.
- Found at review and confirmed by operator mutants, each of which
  passes today's tests: (a) the 4xx warning without its status; (b) the
  store-error warning without the exception class name; (c) the
  "note not found" warning logged at INFO; (d)
  make_response_url_transport ignoring its timeout and passing 10.0.
- Use caplog with logger "slackkb.notify"; check record.levelno and
  record.getMessage(), not caplog.text alone.
- tests/conftest.py and tests/fixtures/ are read-only.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS (each one a test that fails if the named line is broken)
1. A store ClientError and a BotoCoreError on the transition, on the
   re-read, and on the deletes each give exactly one WARNING record from
   slackkb.notify whose message contains the exception class name (e.g.
   "ClientError", "EndpointConnectionError"), the note_id and the
   message_id.
2. A post that raises ResponseUrlError with status 403, 404, 500, and
   None gives a WARNING whose message contains "status=403",
   "status=404", "status=500", "status=None" respectively.
3. Each "done, logged" path gives a WARNING (not INFO): unparsable job,
   note not found on the transition, note gone on re-read, no
   response_url.
4. The success-path lines are INFO: "note failed" (moved), "user
   notified", and the ROUTED no-notice line; none of them is a WARNING.
5. make_response_url_transport(3.5): a call reaches urlopen with
   timeout exactly 3.5.

TESTS (write first; run them against today's source: they pass, because
the source is right. Then break each named line by hand to see the new
assertion fail, and put it back.)
- In tests/test_notify.py: add the assertions to the existing tests
  (test_store_error_is_retried, test_store_error_on_reread_is_retried,
  test_delete_error_is_retried_before_post, test_post_4xx_is_not_retried,
  test_post_5xx_and_transport_error_are_retried,
  test_unparsable_job_and_missing_note_finish,
  test_missing_note_on_reread_finishes,
  test_missing_response_url_finishes_without_notice,
  test_failed_note_notifies_user, test_routed_note_gets_no_notice), or
  add new tests beside them.
- In tests/test_slack_api.py: test_response_url_transport_passes_timeout.

NON-GOALS
No source changes (the extra get_note read stays: the deletes need the
note's team_id, and the job carries only note_id). No changes outside
SCOPE.

DONE WHEN
All checks exit 0 in the sandbox with no network, and the diff touches only
SCOPE paths.
