GOAL
D-022 (Phase 5): when retrieval returns notes but the answer cites none,
the thread reply ends with what was searched:
'Searched N notes for "<question>"; none cited.', and one INFO line is
logged.

SCOPE (only these paths may change)
- src/slackkb/thread.py
- tests/test_thread.py

CONTEXT
- 540 tests pass on main. docs/DECISIONS.md D-022 is the spec; D-016
  (note text and the question are data) and D-021 (id replacement,
  Notes: lines) still apply.
- thread._process: retrieve → if no notes, posts 'No notes match
  "<question>".' (unchanged); else answer(question, notes) →
  _reply_text(result, notes, severity_of) → chat_post_message. When
  result.cited_note_ids is empty, the reply today is the escaped answer
  alone, so a "the notes don't say" answer gives no sign of what was
  searched.
- slack_escape is in thread.py; the no-notes reply already uses it on the
  question.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS
1. When retrieval returned N ≥ 1 notes and result.cited_note_ids is
   empty, the posted reply is the reply as today (answer with ids
   replaced, escaped), then "\n\n", then
   'Searched N notes for "<question>"; none cited.' with "1 note" (not
   "1 notes") when N is 1.
2. The question in that line is Slack-escaped (&, <, > become &amp;,
   &lt;, &gt;), as in the no-notes reply.
3. In that case one INFO record is logged containing
   "answer cited no notes", "event_id=<job.event_id>" and "notes=<N>".
   No such record when the answer cites a note. No new WARNING.
4. Unchanged: the no-notes reply, replies that cite notes (no
   "Searched" text), the existing "question answered" log line, and
   _reply_text's output when called directly (test_answer_kept_when_no_note_ids
   stays as it is).

TESTS (write first; run them and see them fail before changing src)
New, in tests/test_thread.py:
- test_uncited_answer_names_query_and_count: notes n1, n2, answer
  "The notes don't say." cited []: text ==
  "The notes don't say.\n\nSearched 2 notes for \"why are orders timing out?\"; none cited."
  (req 1)
- test_uncited_one_note_is_singular: one note, cited []: text ends with
  'Searched 1 note for "why are orders timing out?"; none cited.' and
  "1 notes" not in text. (req 1)
- test_uncited_query_escaped: question '<!channel> & <@U1>', one note,
  cited []: text ends with
  'Searched 1 note for "&lt;!channel&gt; &amp; &lt;@U1&gt;"; none cited.'
  (req 2)
- test_uncited_answer_logged(caplog): notes n1, n2, cited []: exactly one
  INFO message contains "answer cited no notes", and it contains
  "event_id=Ev1" and "notes=2"; warnings(caplog) == []. Then, after
  caplog.clear(), a reply citing ["n1"]: no message contains
  "answer cited no notes". (req 3)
- test_cited_answer_has_no_searched_line: reply_for([make_note()], ["n1"])
  does not contain "Searched". (req 4)
Existing tests that change (only these two assertions, nothing else):
- test_notes_line_order_and_absent_when_no_ids, its second half (default
  Fakes has one note): expected text becomes
  "ok\n\nSearched 1 note for \"why are orders timing out?\"; none cited."
- test_longer_id_replaced_whole_when_shorter_id_is_its_prefix (two notes,
  cited []): expected text becomes
  "see a saved note and a saved note.\n\nSearched 2 notes for \"why are orders timing out?\"; none cited."

NON-GOALS
- qa.py, retrieve, the Notes: line format, the no-notes reply, the
  template, the model id.

DONE WHEN
- `python -m pytest` and `python -m ruff check src tests` pass.
- The diff touches only the SCOPE paths.
