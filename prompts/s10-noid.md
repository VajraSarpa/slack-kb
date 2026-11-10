GOAL
D-021 amended 2026-11-10: a note id never appears in the answer's text.
The qa system prompt tells the model not to write ids in the answer, and
the reply replaces any given note's id left in the answer with
"a saved note", logging a WARNING with the id.

SCOPE (only these paths may change)
- src/slackkb/qa.py
- src/slackkb/thread.py
- tests/test_qa.py
- tests/test_thread.py

CONTEXT
- 534 tests pass on main. docs/DECISIONS.md D-021 (its "Amended
  2026-11-10" paragraph) is the spec; D-016 (note text is data) and D-019
  (logs keep ids) still apply.
- Found live: an answer's prose named the raw id
  '1395e861768cb4b03fe5f60f858cae43', copied from the <note id="...">
  tags qa.py puts in the user message. The Notes: lines were correct.
- thread._reply_text(result, notes, severity_of) builds the reply: the
  Slack-escaped answer, then the Notes: lines. `notes` are the notes the
  model was given.
- test_qa.py test_request_shape pins the request with
  "system": [{"text": qa.SYSTEM_PROMPT}], so it follows the constant.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS
1. qa.SYSTEM_PROMPT gains a sentence telling the model never to write a
   note id in the answer text; ids go only in cited_note_ids. The prompt's
   existing sentences stay.
2. _reply_text replaces every occurrence of each given note's note_id in
   result.answer with "a saved note", before Slack-escaping. Only whole
   tokens: an occurrence with a letter, digit, "_" or "-" directly before
   or after it is left alone (so id "n1" never changes "n10" or "xn1").
   Ids of notes that were not given are left alone.
3. For each note_id replaced at least once, one WARNING is logged
   containing "note id in answer" and the note_id. No WARNING when
   nothing is replaced.
4. The Notes: lines, the escaping of the rest of the answer, and every
   other reply behavior are unchanged.

TESTS (write first; run them and see them fail before changing src)
In tests/test_qa.py:
- test_system_prompt_forbids_ids_in_answer: SYSTEM_PROMPT (lowercased)
  contains "never write a note id" and still contains "cite only ids".
  (req 1)
In tests/test_thread.py:
- test_note_id_in_answer_is_replaced: given notes "n1" and "n2", answer
  "See n1 & <n2> and n10, xn1, n1_b; n1." cited ["n1"]: the reply text
  starts with "See a saved note &amp; &lt;a saved note&gt; and n10, xn1,
  n1_b; a saved note." and its Notes: lines are as before. (req 2, 4)
- test_ungiven_id_left_alone: answer naming "n9" with only "n1" given:
  "n9" stays. (req 2)
- test_replaced_id_logged_once: the answer names "n1" twice and "n2"
  once: caplog has exactly two WARNINGs containing "note id in answer",
  one naming n1, one naming n2; an answer with no ids logs none. (req 3)

NON-GOALS
- llm.py, retrieve, the Notes: line format, the template, the model id.

DONE WHEN
- `python -m pytest` and `python -m ruff check src tests` pass.
- The diff touches only the SCOPE paths.
