GOAL
Tests only: pin the two unusable-usage cases today's tests miss (Slice 9b
review f1, personal_9cd39c31). test_converse_usage_missing_warns tries -1
only on outputTokens, and never drops outputTokens while inputTokens is
present, so a _log_usage that checked only one key, or skipped the
negative check on inputTokens, would pass.

SCOPE (only these paths may change)
- tests/test_llm.py

CONTEXT
- 548 tests pass on main. docs/DECISIONS.md D-019 (token counts logged)
  is the spec.
- src/slackkb/llm.py: _count(usage, key) returns the value only when it
  is a non-bool int >= 0, else None. _log_usage logs one WARNING
  "bedrock usage missing, call=converse model_id=%s" if either count is
  None, else one INFO "bedrock usage, call=converse model_id=%s
  input_tokens=%d output_tokens=%d". ask() returns the tool input dict
  either way.
- test_llm.py helpers: tool_response(input_dict), FakeClient(response),
  _usage_records(caplog), TOOL. src is not in scope: if a test can't pass
  without a src change, stop and say which.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS
1. With usage {"inputTokens": -1, "outputTokens": 1}, ask() returns the
   tool input unchanged and exactly one usage record is logged: a WARNING
   whose message is "bedrock usage missing, call=converse model_id=m".
2. The same with usage {"inputTokens": 1} (outputTokens absent).
3. No existing test changes; src does not change.

TESTS
In tests/test_llm.py:
- test_converse_usage_negative_input_warns (req 1)
- test_converse_usage_output_absent_warns (req 2)
Each uses caplog.set_level("INFO", logger="slackkb.llm") and
FakeClient, as test_converse_usage_missing_warns does. These tests pass on
the current src (it is already right); the harness mutates the src lines
they run to show they can fail, so don't edit src to check that.

NON-GOALS
- Any src change, other log lines, the existing usage tests.

DONE WHEN
- `python -m pytest` and `python -m ruff check src tests` pass.
- The diff touches only tests/test_llm.py.
