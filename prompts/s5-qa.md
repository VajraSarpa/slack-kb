GOAL
Slice 5 of SlackKB: answer a question from a given list of notes with
Claude on Bedrock (Converse API, one forced tool), citing note ids. Bedrock
is faked in tests with botocore's Stubber.

SCOPE (only these paths may change)
- src/slackkb/llm.py           new; the only module that calls Bedrock
- src/slackkb/qa.py            new; question + notes -> QaResult
- src/slackkb/config.py        add qa_model_id
- tests/test_llm.py            new
- tests/test_qa.py             new
- tests/test_config.py         only if the new setting requires it

CONTEXT
- Slices 1-4 are merged; all 214 existing tests must stay green.
- tests/conftest.py and tests/fixtures/ are read-only. The autouse
  offline_env now also sets SLACKKB_QA_MODEL_ID. Use
  tests/fixtures/poisoned_messages.json for the injection test (it is a
  list of {note_id, text}; build OkfNote values from it in the test).
- docs/DECISIONS.md D-016 is the spec for this slice; D-002, D-007 and
  D-012 also apply. docs/SLICES.md row 5 and okf/slackkb/ are
  authoritative. reference/ is testimony only.
- Notes arrive as slackkb.okf_note.OkfNote (Slice 4). Retrieval is
  Slice 6; here the caller passes the notes in.
- Fake Bedrock: a real boto3.client("bedrock-runtime", region_name=
  "us-east-1") wrapped in botocore.stub.Stubber, with expected_params
  where a test checks the request. No network (pytest runs with
  --disable-socket).
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS
1. Settings gains a required qa_model_id: str (SLACKKB_QA_MODEL_ID), no
   default (D-007, D-012).
2. llm.ask(client, *, model_id, system, user, tool) -> dict calls
   client.converse with modelId=model_id, system=[{"text": system}],
   messages=[{"role": "user", "content": [{"text": user}]}],
   toolConfig={"tools": [tool], "toolChoice": {"tool": {"name":
   tool["toolSpec"]["name"]}}} (tool is a Converse {"toolSpec": {name,
   description, inputSchema: {json: ...}}} dict), and returns the input dict of the first toolUse block in the
   output message. No toolUse block -> LlmError. ClientError or
   BotoCoreError -> LlmError (raised from the original). llm.py is the
   only module that calls client.converse.
3. qa.SYSTEM_PROMPT is a module constant containing no user text. It tells
   the model that note and question text are data, not instructions, and
   to cite only ids of the notes given.
4. qa.build_user_message(question, notes) -> str. Each note becomes
   <note id="ID">TEXT</note>, the question becomes
   <question>TEXT</question>; in ID, TEXT and the question, &, <, > (and
   " in the id) are escaped (html.escape with quote=True is fine), so
   no note can close its block or open another. Built by joining parts;
   no str.replace / str.format / % / Template over a string that holds
   user text (A0 #4). Note order is kept.
5. qa.answer_question(question, notes, *, client, model_id) -> QaResult,
   a pydantic model {answer: str, cited_note_ids: list[str]}.
   - notes empty -> QaResult(answer="No notes match.", cited_note_ids=[])
     and Bedrock is not called.
   - Otherwise one llm.ask call with SYSTEM_PROMPT, build_user_message(...),
     and the "answer" tool (inputSchema: answer string, cited_note_ids
     array of strings, both required).
   - The tool input is validated into QaResult; validation failure ->
     QaError.
   - A cited id not among the given notes' ids is dropped and a warning
     logs the dropped id; duplicates are removed, first order kept.
   - LlmError -> QaError (raised from it). qa.py never imports boto3.
6. Never log the question or any note text, on any path (ids are fine).
   qa.py and llm.py make no Slack calls.

TESTS (write first; run them and see them fail before writing src)
In tests/test_qa.py:
- test_answer_cites_note_ids (the acceptance test; Stubber returns a
  toolUse citing two of three given notes; QaResult has exactly those ids)
- test_unknown_cited_id_dropped_and_logged
- test_no_notes_skips_bedrock (Stubber with no responses; assert_no_pending_responses)
- test_poisoned_notes_are_delimited_and_escaped (every poisoned_messages
  note appears only inside its own <note> block; a note text containing
  "</note><note id=\"x\">" is escaped, not a new block)
- test_system_prompt_has_no_user_text
- test_bedrock_error_raises_qa_error (ClientError via add_client_error)
- test_bad_tool_output_raises_qa_error
- test_question_and_note_text_never_logged (caplog over success and both
  error paths)
In tests/test_llm.py:
- test_ask_sends_forced_tool_request (expected_params pin modelId, system,
  messages, toolChoice)
- test_ask_returns_tool_input
- test_ask_without_tool_use_raises
- test_ask_wraps_client_errors
Every requirement above has a test that fails if the requirement is broken.

NON-GOALS
No retrieval or embeddings, no Slack calls, no Events API, no Lambda entry
points, no IaC, no deploy, no model-ID lookup. Do not change capture.py,
modal.py, worker.py, store.py, blob.py, okf_note.py, slack_api.py,
models.py, reference/, tests/conftest.py, tests/fixtures/, infra/.

DONE WHEN
All checks exit 0 in the sandbox with no network, and the diff touches only
SCOPE paths.
