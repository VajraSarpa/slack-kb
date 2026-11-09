GOAL
D-021 amendment: each cited note's line shows its date and time, the
channel it was saved in, and its severity, instead of a brief of its text
(the brief repeated the answer, and severity was missing).

SCOPE (only these paths may change)
- src/slackkb/thread.py
- src/slackkb/entry.py
- tests/test_thread.py
- tests/test_entry.py

CONTEXT
- 527 tests pass on main. docs/DECISIONS.md D-021 with its "Amended
  2026-11-09" and "Severity" lines is the spec; D-009, D-014, D-016, D-019,
  D-020 still apply. infra/template.yaml already grants the thread role
  dynamodb:GetItem on the notes table (Vajra's side, done).
- thread.py today: _reply_text(result, notes) writes
  "\n• " + _when(created_at) + ": " + _brief(text) per cited note, with
  BRIEF_LIMIT and _brief for the brief. _when returns the Slack date token,
  or slack_escape(created_at) on ValueError. OkfNote has channel_id.
  thread.handle(event, *, retrieve, answer, slack) calls _process per
  record; _process calls _reply_text.
- store.get_note(table, note_id) -> Note | None; Note.severity is a
  Severity enum (its .value is e.g. "MEDIUM"), default LOW.
- entry.thread_handler builds retrieve/answer with thread.bind(...) and
  slack with thread.slack_client(settings), then calls thread.handle.
  entry has a helper that returns the DynamoDB Table for a name
  (_table(session, name)); settings.notes_table names the notes table.
  tests/test_entry.py's recorder binds kwargs to the real handle()
  signature.
- Tests in tests/test_thread.py that pin the brief and change with this
  amendment: the expected strings near lines 136, 221, 254, 262, 274, 332;
  test_brief_cut_at_word_with_ellipsis and
  test_brief_collapses_whitespace_and_is_escaped (remove both: there is no
  brief any more). make_note and the fakes may gain a channel_id
  parameter. In tests/test_entry.py only the thread-binding test's
  assertions may change or gain lines. No other existing test line changes.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS
1. Each cited line is "\n• " + WHEN, then " in <#" + channel_id + ">" when
   channel_id is a plain Slack id (one or more of A–Z and 0–9, nothing
   else; otherwise no channel part), then " · " + SEVERITY when a
   severity is known (otherwise no severity part). The "\n\nNotes:"
   header, cited order, and the no-citations reply are unchanged.
2. WHEN is unchanged (Slack date token with its UTC fallback). A
   created_at whose parsing raises ValueError or OverflowError shows as
   slack_escape(created_at).
3. The note's text no longer appears in the reply. _brief and BRIEF_LIMIT
   are removed.
4. A cited id with no retrieved note still shows as "• " + slack_escape(id).
5. thread.handle gains a keyword-only `severity_of: Callable[[str],
   str | None] | None = None`. With None, lines have no severity part
   (existing callers and tests unchanged). Otherwise SEVERITY is
   slack_escape(severity_of(note_id)). If severity_of raises, or returns
   None, the line has no severity part, one WARNING containing the
   note_id is logged, and the reply is still posted.
6. thread.severity_lookup(table) returns a callable: note_id ->
   store.get_note(table, note_id).severity.value, or None when get_note
   returns None. It does not catch exceptions (requirement 5 does).
7. entry.thread_handler passes severity_of=thread.severity_lookup(<the
   notes Table, settings.notes_table>), built once per container with the
   other thread clients.

TESTS (write first; run them and see them fail before changing src)
In tests/test_thread.py:
- test_citation_shows_date_channel_and_severity: channel_id "C0ABC123",
  created_at "2026-11-09T20:12:21.514Z", severity_of returning "MEDIUM":
  the reply ends "\n\nNotes:\n• <!date^EPOCH^{date_short_pretty} {time}|
  2026-11-09 20:12 UTC> in <#C0ABC123> · MEDIUM" (EPOCH computed in the
  test). (req 1, 5)
- test_note_text_not_in_reply: a cited note's text "SECRET-PHRASE-42" is
  not in the reply. (req 3)
- test_odd_channel_id_is_left_out: channel_id "C1>x" and "" give no
  " in " part. (req 1)
- test_unparseable_date_is_escaped: created_at "<!channel> & co" shows as
  "&lt;!channel&gt; &amp; co". (req 2)
- test_overflowing_date_falls_back: created_at "0001-01-01T00:00:00+01:00"
  shows as that string and the reply is still posted. (req 2)
- test_severity_lookup_failure_still_answers: severity_of raising
  RuntimeError, and severity_of returning None: no " · " part, one WARNING
  with the note_id each time, reply posted. (req 5)
- test_no_severity_of_means_no_severity_part (req 5).
- test_severity_lookup_reads_notes_table: with the conftest notes_table
  fixture and a note stored then given severity HIGH via
  store.set_severity, severity_lookup(table)(note_id) == "HIGH"; a
  missing id gives None. (req 6)
- Update the pinned expected strings listed above to the new format.
In tests/test_entry.py:
- the thread-binding test also asserts handle got severity_of, and that
  calling it reads Table(notes_table) (via a patched
  thread.severity_lookup that records its table). (req 7)

NON-GOALS
- qa.py, the model prompt, retrieval, logs beyond requirement 5,
  infra/ (already done), any other module.

DONE WHEN
- `python -m pytest` and `python -m ruff check src tests` pass.
- The diff touches only the SCOPE paths.
