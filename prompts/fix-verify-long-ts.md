GOAL
Fix: verify() lets a ValueError escape on a very long timestamp header.

SCOPE (only these paths may change)
- src/slackkb/slack_verify.py
- tests/test_slack_verify.py

CONTEXT
- docs/DECISIONS.md and okf/slackkb/ are authoritative. reference/ is
  testimony.
- Found 2026-11-04: an X-Slack-Request-Timestamp of 5000 nines passes the
  `[0-9]+` check, then `int()` raises ValueError (Python's 4300-digit limit
  for int-from-string), so verify() raises ValueError, not SignatureError.

REQUIREMENTS
1. verify() raises SignatureError, never another exception, for any
   timestamp header value, including one of 5000 digits.
2. Every existing test keeps passing unchanged.
3. Signing still uses the raw header string, as now.

TESTS (write first; they must fail before the fix)
- test_huge_timestamp_rejected: a 5000-digit timestamp raises SignatureError.

NON-GOALS
No other behavior change. Do not touch reference/.

DONE WHEN
All checks exit 0 in the sandbox with no network.
