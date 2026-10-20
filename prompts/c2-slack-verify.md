GOAL
Rung C2 of Slice 1: verify a Slack request signature and timestamp.

SCOPE (only these paths may change)
- src/slackkb/slack_verify.py
- tests/test_slack_verify.py

CONTEXT
- tests/conftest.py and tests/fixtures/ are read-only. Use sign() and the
  slack_request fixture.
- docs/DECISIONS.md and okf/slackkb/ are authoritative. reference/ is
  testimony.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.

REQUIREMENTS
1. verify(headers: Mapping[str, str], body: str, secret: str, now: int) -> None.
   Raises SignatureError on any failure.
2. Header lookup is case-insensitive.
3. Rejects: missing timestamp or signature header, non-integer timestamp,
   |now - timestamp| > 300 seconds, signature mismatch.
4. Compare with hmac.compare_digest. Never log the secret or the signature.

TESTS (write first; they must fail before implementation)
- test_valid_signature_passes
- test_bad_signature_rejected
- test_stale_timestamp_rejected
- test_future_timestamp_rejected
- test_missing_headers_rejected
- test_lowercase_headers_accepted

NON-GOALS
No handler, no DynamoDB, no Slack Bolt. Do not touch reference/,
tests/conftest.py, or tests/fixtures/.

DONE WHEN
All checks exit 0 in the sandbox with no network.
