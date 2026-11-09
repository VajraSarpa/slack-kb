GOAL
D-021: an answer's citations show each note's date and time and a brief
(the start of its text) instead of note ids.

SCOPE (only these paths may change)
- src/slackkb/thread.py
- tests/test_thread.py

CONTEXT
- 519 tests pass on main. docs/DECISIONS.md D-021 is the spec; D-016
  (note text is data) and D-019 (logs) still apply.
- thread._reply_text(result) builds the reply today: the escaped answer,
  then "\n\nNotes: " + the cited ids joined by ", " (none when there are
  no cited ids). _process already holds `notes`, the list of OkfNote the
  question retrieved; OkfNote has note_id, created_at (ISO 8601 UTC, e.g.
  "2026-11-09T20:12:21.514Z" or with "+00:00") and text.
- qa.answer_question already drops cited ids that aren't among the
  retrieved notes, so every cited id normally has a note.
- Existing tests that pin the old "Notes: <ids>" text, and may change only
  in their expected strings (and the notes their fakes return, if a test
  needs created_at/text values): test_thread.py lines near 120
  ("It was alpha.\n\nNotes: n1"), 204 (f"...Notes: {note_id}"), 235
  ("...\n\nNotes: n1") and test_notes_line_order_and_absent_when_no_ids.
  No other existing test line changes.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS
1. With cited ids, the reply is the escaped answer, then "\n\nNotes:",
   then for each cited id in cited order "\n• " + WHEN + ": " + BRIEF.
   With no cited ids, the reply is the escaped answer alone (as today).
2. WHEN for a parseable created_at is
   "<!date^EPOCH^{date_short_pretty} {time}|YYYY-MM-DD HH:MM UTC>", EPOCH
   the integer Unix seconds of created_at, the fallback its UTC date and
   time. Both "Z" and "+00:00" forms parse. A created_at that doesn't
   parse is shown as slack_escape(created_at) instead.
3. BRIEF is the note's text with every run of whitespace (newlines
   included) collapsed to one space and stripped. If that is at most 80
   characters it is used whole; otherwise it is cut to the last space at
   or before character 80 (or hard at 80 when there is no space), trailing
   spaces removed, and "…" appended. Then slack_escape is applied, so a
   note containing "<!channel>" or "&" can't ping or break formatting.
4. A cited id with no retrieved note is shown as "• " + slack_escape(id).
5. Note ids no longer appear in the reply text. Logging is unchanged.

TESTS (write first; run them and see them fail before changing src)
In tests/test_thread.py:
- test_citation_shows_date_token_and_brief: one cited note with
  created_at "2026-11-09T20:12:21.514Z" and short text: the reply ends
  "\n\nNotes:\n• <!date^1794255141^{date_short_pretty} {time}|2026-11-09
  20:12 UTC>: <text>". (Compute EPOCH in the test from the datetime, don't
  hard-code a number you didn't check.) (req 1, 2)
- test_citation_accepts_plus_zero_offset: "+00:00" form gives the same
  token as the "Z" form. (req 2)
- test_brief_cut_at_word_with_ellipsis: a 120-character text cut at the
  last space before 80, "…" appended; a text of exactly 80 characters is
  whole, no "…"; a single 100-character word is cut hard at 80 + "…".
  (req 3)
- test_brief_collapses_whitespace_and_is_escaped: text "a\n\n  b <!channel>
  & c" gives brief "a b &lt;!channel&gt; &amp; c". (req 3)
- test_citations_keep_cited_order: three notes cited n3, n1, n2 appear in
  that order. (req 1)
- test_unparseable_date_and_missing_note: created_at "yesterday" shows as
  "yesterday"; a cited id with no note shows as the escaped id. (req 2, 4)
- Update the four pinned expected strings above to the new format.

NON-GOALS
- qa.py, the model prompt, retrieval, logs, any other module.

DONE WHEN
- `python -m pytest` and `python -m ruff check src tests` pass.
- The diff touches only the SCOPE paths.
