GOAL
D-012 output cap (2026-11-09, cost): every Bedrock Converse call carries
inferenceConfig maxTokens = 1024, and a response that stopped on the cap
is an LlmError, never a partial answer.

SCOPE (only these paths may change)
- src/slackkb/llm.py
- tests/test_llm.py
- tests/test_qa.py       only the expected params in test_request_shape
- tests/test_thread.py   only the expected params in test_real_retrieve_wired

CONTEXT
- 517 tests pass on main. docs/DECISIONS.md D-012 (its "Output cap" lines)
  is the spec; D-016 and D-019 still apply to llm.ask.
- llm.ask(client, *, model_id, system, user, tool) is the only Converse
  call. Three existing tests pin its request with botocore's Stubber
  expected_params: test_llm.py test_ask_sends_forced_tool_request,
  test_qa.py test_request_shape, test_thread.py test_real_retrieve_wired.
  Each gains exactly "inferenceConfig": {"maxTokens": 1024}; nothing else
  in those tests changes, and no other existing test line changes.
- Bedrock reports a capped response with stopReason "max_tokens".
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.
- Write files with edit_file / write_file, not shell redirection or sed.

REQUIREMENTS
1. llm.py has a module constant MAX_TOKENS = 1024, and ask() sends
   inferenceConfig={"maxTokens": MAX_TOKENS} on every call. No new
   parameter on ask(); callers don't change.
2. If the response's stopReason is "max_tokens", ask() raises LlmError
   with a message naming max_tokens, even when a toolUse block is present
   (a capped tool call may be cut off), and logs one WARNING containing
   "max_tokens" and the model_id. The usage INFO line (D-019) is still
   logged first.
3. Any other stopReason behaves as today.

TESTS (write first; run them and see them fail before changing src)
In tests/test_llm.py:
- test_ask_caps_output_tokens: the Stubber expected params include
  inferenceConfig {"maxTokens": 1024} (you may fold this into the updated
  test_ask_sends_forced_tool_request instead; say which). (req 1)
- test_max_tokens_stop_is_an_error: a response with a toolUse block and
  stopReason "max_tokens": ask raises LlmError naming max_tokens; caplog
  has the usage INFO line and one WARNING with "max_tokens" and the model
  id. (req 2)
Plus the inferenceConfig line in the three pinned tests above.

NON-GOALS
- embed.py, qa.py, thread.py, the template, the model id.

DONE WHEN
- `python -m pytest` and `python -m ruff check src tests` pass.
- The diff touches only the SCOPE paths.
