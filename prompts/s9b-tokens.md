GOAL
Slice 9b (D-019): every Bedrock call that returns logs one INFO line with
its model_id and token counts, so token spend can be read from the logs.

SCOPE (only these paths may change)
- src/slackkb/llm.py           a module logger and the converse usage line
- src/slackkb/embed.py         a module logger and the embed usage line
- tests/test_llm.py            new tests only
- tests/test_embed.py          new tests only

CONTEXT
- Slices 1-7b, 2b and 9a are merged; all 445 existing tests must stay
  green and no existing test line changes.
- docs/DECISIONS.md D-019 is the spec (the "Token spend (9b)" sentence);
  D-016 (Converse, never log prompts) and D-008 (Titan V2 embeddings) also
  apply. obs.py (Slice 9a) stamps the trace id on every record already;
  9b adds no trace code.
- Converse returns usage {"inputTokens", "outputTokens", "totalTokens"}.
  Titan Text Embeddings V2 returns a JSON body with "embedding" and
  "inputTextTokenCount". The existing embed tests send bodies without
  inputTextTokenCount; they must keep passing (they will now log the
  warning in req 3).
- botocore's Stubber validates responses against the service model, and
  Converse usage is required there, so a Converse response without usage
  can't be stubbed: use a small fake client object with a converse method
  for that test only.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS
1. llm.ask: once client.converse returns (before the toolUse check, so a
   reply with no toolUse is still counted), it logs exactly one INFO line
   on logger "slackkb.llm":
   "bedrock usage, call=converse model_id=%s input_tokens=%d output_tokens=%d"
   with the response's usage.inputTokens and usage.outputTokens. Return
   value and LlmError behaviour are unchanged. A converse call that raises
   logs no usage line.
2. embed.embed_text: once the response body parses as a JSON object
   (before the embedding checks, so a bad embedding is still counted), it
   logs exactly one INFO line on logger "slackkb.embed":
   "bedrock usage, call=embed model_id=%s input_tokens=%d"
   with the body's inputTextTokenCount. Return value and EmbedError
   behaviour are unchanged. An invoke_model call that raises, or a body
   that isn't JSON, logs no usage line.
3. A count that is missing, not an int, a bool, or negative: instead of
   the INFO line, one WARNING "bedrock usage missing, call=<converse|embed>
   model_id=%s"; the call still succeeds or fails exactly as before.
4. No usage line or warning contains the system prompt, the user message,
   the input text, or any embedding value; no line names a price or cost.

TESTS (write first; run them and see them fail before writing src)
In tests/test_llm.py:
- test_converse_usage_logged: Stubber response with usage inputTokens 123,
  outputTokens 45: exactly one record on "slackkb.llm", level INFO,
  message exactly "bedrock usage, call=converse model_id=model-x
  input_tokens=123 output_tokens=45". (req 1)
- test_converse_usage_logged_without_tool_use: a reply with no toolUse
  raises LlmError and still logs the one usage line. (req 1)
- test_converse_error_logs_no_usage: a stubbed ClientError: LlmError, no
  "bedrock usage" record. (req 1)
- test_converse_usage_missing_warns: fake client returning no usage, then
  usage with inputTokens "3", then True, then -1: each time exactly one
  WARNING "bedrock usage missing, call=converse model_id=m", no INFO usage
  line, and ask still returns the tool input. (req 3)
- test_converse_usage_line_has_no_prompt_text: system "SYS-SECRET", user
  "USER-SECRET": no record from "slackkb.llm" contains either, nor "$",
  "usd" or "cost" (case-insensitive). (req 4)
- test_converse_usage_line_carries_trace: with obs.configure(io.StringIO())
  (remove the handler and restore the root/botocore/boto3/urllib3 levels
  after), inside obs.trace() with obs.bind("Ev1"): the usage JSON line has
  trace_id "Ev1". (D-019)
In tests/test_embed.py:
- test_embed_usage_logged: body {"embedding": [...512...],
  "inputTextTokenCount": 7}: exactly one INFO record on "slackkb.embed",
  message exactly "bedrock usage, call=embed model_id=<EMBED_MODEL_ID>
  input_tokens=7". (req 2)
- test_embed_usage_logged_on_bad_embedding: wrong length with
  inputTextTokenCount 7: EmbedError and the one usage line. (req 2)
- test_embed_error_and_bad_json_log_no_usage: stubbed ClientError, and a
  body that isn't JSON: EmbedError, no "bedrock usage" record. (req 2)
- test_embed_usage_missing_warns: missing, "7", True, -1: one WARNING
  "bedrock usage missing, call=embed model_id=<EMBED_MODEL_ID>" each, no
  INFO usage line, and the vector is still returned. (req 3)
- test_embed_usage_line_has_no_text_or_vector: input text "TEXT-SECRET",
  embedding values all 0.123: no "slackkb.embed" record contains
  "TEXT-SECRET" or "0.123", nor "$", "usd" or "cost". (req 4)

NON-GOALS
- Prices, budgets, totals or metrics (EMF/CloudWatch) - Slice 8 or later.
- Changing obs.py, any handler, or any existing test line.

DONE WHEN
- `python -m pytest` and `python -m ruff check src tests` pass.
- The diff touches only the SCOPE paths.
