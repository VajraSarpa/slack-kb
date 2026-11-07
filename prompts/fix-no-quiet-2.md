GOAL
Close the five gaps the apply review found in the "nothing fails quietly"
change (merged 010c68b): a FAILED note can keep an S3 object forever, bad
frontmatter can escape as the wrong exception type, and two behaviors have
no test.

SCOPE (only these paths may change)
- src/slackkb/worker.py
- src/slackkb/okf_note.py
- src/slackkb/blob.py
- tests/test_worker.py, tests/test_okf_note.py, tests/test_blob.py
  Existing tests may gain fixtures and new assertions. Only the assertions
  named in requirement 1 may change. New tests may be added.

CONTEXT
- All 199 existing tests must stay green except as requirement 1 states.
- tests/conftest.py and tests/fixtures/ are read-only; use their fixtures.
- docs/DECISIONS.md D-014 (a FAILED note has no S3 object) and D-009 apply.
- Log style as in the module now: logger.warning / logger.info, short
  lowercase message, then key=value pairs; never note text.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS
1. worker: a note that is FAILED at read calls blob.delete_note (deleting a
   missing key is fine), then logs INFO "note failed, no object, note_id=…
   message_id=…" and is handled. A delete error (ClientError/BotoCoreError)
   logs WARNING naming the error class, note_id and message_id, and the
   record is a batch failure so SQS retries. The lost-race FAILED path uses
   the same helper. Existing tests that assert the old "not written" message
   or a delete count of zero on this path may change to match.
2. A redelivery after a failed delete removes the object: test it end to end
   (first handle: delete fails -> batch failure, object present; second
   handle with a working bucket -> handled, object gone).
3. The lost-race re-read that still shows CAPTURED keeps today's behavior
   (WARNING, batch failure); add a test that pins both.
4. okf_note.from_markdown: any exception raised by yaml.safe_load becomes
   OkfNoteError (chained with `from None`). Frontmatter field values must be
   str exactly: bytes (`!!binary`), ints, dates, None are rejected with
   OkfNoteError (strict str). Tests: `note_id: !!int ""` (IndexError today),
   `note_id: !!bool foo` (KeyError), `created_at: !!timestamp foo`
   (AttributeError), `note_id: !!binary "@@"` (accepted today), and a
   monkeypatched safe_load raising TypeError; each -> OkfNoteError. The
   round-trip tests stay green.
5. One key format: okf_note gains key_for(team_id, note_id) -> str;
   object_key(note) returns key_for(note.team_id, note.note_id); blob uses
   key_for (no second f-string). A test asserts
   key_for(n.team_id, n.note_id) == object_key(n) for a sample note.
Every requirement above has a test that fails if the requirement is broken.

NON-GOALS
No changes to capture.py, modal.py, store.py, queue.py, models.py,
config.py, slack_api.py, slack_verify.py, conftest, fixtures, docs/, infra/.
No logging configuration.

DONE WHEN
All checks exit 0 in the sandbox with no network, and the diff touches only
SCOPE paths.
