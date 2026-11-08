GOAL
D-014 as amended (2026-11-07): when the worker moves a note CAPTURED ->
ROUTED, the same conditional update removes its text from DynamoDB, so S3
holds the only copy. A redelivered ROUTED note is done: nothing is written.

SCOPE (only these paths may change)
- src/slackkb/models.py        Note.text optional for ROUTED notes only
- src/slackkb/store.py         add route_note; get_note loads a text-less item
- src/slackkb/worker.py        CAPTURED -> put_note, then route_note;
                               ROUTED -> done, no write
- tests/test_models.py         add tests
- tests/test_store.py          add tests
- tests/test_worker.py         test_worker_redelivery_rewrites_routed_note
                               is replaced (the rule it pins is reversed);
                               monkeypatches of worker.transition_status may
                               target worker.route_note instead, with the
                               same behavior; add tests. No other existing
                               assertion may change.
- tests/test_modal.py          add one test

CONTEXT
- Slices 1-5 are merged; all 238 existing tests must stay green except the
  one replaced redelivery test.
- docs/DECISIONS.md D-014 (with its 2026-11-07 amendment) is the spec; D-009
  and D-013 also apply. tests/conftest.py and tests/fixtures/ are read-only.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS
1. Note.text becomes `str | None = None`. A model validator rejects
   text=None unless status is ROUTED (ValueError / ValidationError). Every
   existing way of building a Note with text is unchanged.
2. store.route_note(table, note_id) -> bool: one update_item with
   UpdateExpression "SET #status = :routed REMOVE #text" and the condition
   attribute_exists(note_id) AND status = CAPTURED. Same contract as
   transition_status: True if updated, False if the note is in another
   status (item left unchanged, text included), NoteNotFoundError if absent,
   other ClientErrors propagate. transition_status is unchanged.
3. store.get_note returns Note(text=None) for a ROUTED item with no text
   attribute.
4. worker._process, after loading the note:
   - FAILED: unchanged.
   - ROUTED: log INFO "note already routed, nothing written" with note_id
     and message_id; return True; no S3 call and no store write.
   - CAPTURED: put_note, then route_note in place of transition_status;
     every existing failure and lost-race path behaves as now.
5. The severity modal (button and view_submission) works on a ROUTED note
   whose text was removed, as it does on a CAPTURED note.
6. Never log note text (as now).

TESTS (write first; run them and see them fail before writing src)
- tests/test_models.py: test_note_text_none_only_when_routed (None with
  CAPTURED and with FAILED rejected; None with ROUTED accepted).
- tests/test_store.py: test_route_note_sets_routed_and_removes_text (the
  stored item has status ROUTED and no text attribute);
  test_route_note_only_from_captured (FAILED and ROUTED items unchanged,
  a FAILED note keeps its text; missing note raises NoteNotFoundError);
  test_get_note_loads_routed_note_without_text.
- tests/test_worker.py: test_worker_routes_and_drops_text (the acceptance
  test: the S3 object holds the text and parses; the DynamoDB item is
  ROUTED with no text attribute);
  test_worker_redelivery_of_routed_note_writes_nothing (replaces the old
  redelivery test; a bucket whose put raises proves no write; record is a
  success; the INFO line names note_id and message_id);
  test_worker_failed_note_keeps_text.
- tests/test_modal.py: test_modal_submission_on_routed_note_updates_severity
  (the note has been routed by the worker, so its text is gone).
Every requirement above has a test that fails if the requirement is broken.

NON-GOALS
No retrieval, embeddings or vectors (Slice 6). No change to capture.py,
blob.py, okf_note.py, qa.py, llm.py, slack_api.py, config.py, modal.py,
reference/, tests/conftest.py, tests/fixtures/, infra/.

DONE WHEN
All checks exit 0 in the sandbox with no network, and the diff touches only
SCOPE paths.
