GOAL
Slice 5 follow-up: close the two gaps the S5 reviews found. Log only the
count of dropped cited ids, never an id (D-016 as amended), and pin the
"first toolUse block" rule with a test.

SCOPE (only these paths may change)
- src/slackkb/qa.py            the dropped-id warning only
- tests/test_qa.py             test_unknown_cited_id_dropped_and_logged may
                               change its log assertion (it now expects the
                               id in the log, which D-016 forbids); add tests
- tests/test_llm.py            add a test; no existing assertion may change

CONTEXT
- Slice 5 is merged; all 235 existing tests must stay green (one log
  assertion in test_unknown_cited_id_dropped_and_logged changes on purpose).
- docs/DECISIONS.md D-016 (amended): a cited id not among the notes given
  is dropped; only the count of dropped ids is logged, never an id (it is
  model output and can carry note text).
- tests/conftest.py and tests/fixtures/ are read-only.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS
1. qa.answer_question logs at most one WARNING per call about dropped
   cited ids, only when at least one was dropped, giving the count of
   dropped ids (duplicates of a kept id are not "dropped"). The message
   never contains a dropped id, a kept id's text, the question or any
   note text. Everything else in answer_question is unchanged.
2. llm.ask is unchanged; a test pins that it returns the input of the
   first toolUse block: content [text block, toolUse A, toolUse B] -> A.

TESTS (write first; run them and see them fail before writing src)
In tests/test_qa.py:
- test_unknown_cited_id_dropped_and_logged: same result assertion; the
  log assertion now checks one WARNING naming the count (2 for
  ["n2", "ghost", "n2", "n1", "ghost2"]-style input) and no dropped id.
- test_dropped_id_carrying_note_text_is_not_logged: the model "cites" an
  id equal to a note's text and one equal to the question; neither string
  appears in any log record; the warning gives the count.
- test_no_warning_when_nothing_dropped
In tests/test_llm.py:
- test_ask_returns_first_tool_use_input
Every requirement above has a test that fails if the requirement is broken.

NON-GOALS
No logging configuration (botocore DEBUG levels belong to the entry
points, Slice 8/9). No change to llm.py, config.py, any other src file,
reference/, tests/conftest.py, tests/fixtures/, infra/.

DONE WHEN
All checks exit 0 in the sandbox with no network, and the diff touches only
SCOPE paths.
