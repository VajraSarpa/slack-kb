ROLE
You are auditing a stale tutorial implementation of SlackKB so it can be rebuilt
cleanly. You are read-only. Do not propose code yet.

CONTEXT
- reference/tutorial/ holds code from a guide that produced a working app at some
  point. Treat it as testimony: it may be outdated, insecure, or wrong.
- okf/slackkb/ holds the target architecture, glossary, and decisions. Where the
  tutorial disagrees with OKF, OKF wins; report the disagreement.
- Target stack: Python 3.12+, uv, pytest, AWS Lambda, API Gateway, DynamoDB, S3,
  Amazon Bedrock, CloudFormation (SAM). Slack Bolt for Python.

TASK
Produce five sections, each claim cited to a file:line in reference/tutorial/
or an okf/ file. If you did not find something, say what you searched and where
(an absence claim must be replayable).

1. INVENTORY
   Every component in the tutorial: Slack handlers (slash commands, modals,
   events, thread replies), Lambdas, tables, buckets, Bedrock calls, IAM, IaC.
   One row each: name | file | responsibility | external calls.

2. STALENESS
   For each dependency and AWS/Slack API used: version or model ID in the code,
   and whether it is deprecated, renamed, or superseded. Mark each as
   VERIFIED (you checked docs) or UNVERIFIED (from training data). Specifically
   check: Bedrock model IDs, Titan embedding version, Slack Bolt version,
   Lambda runtime, Python version, any Bedrock Knowledge Bases usage.

3. DEFECTS
   Security and reliability problems, highest severity first:
   - Slack request signature verification present and correct?
   - 3-second ack: does any handler do slow work before acking?
   - Secrets: hardcoded tokens, env vars vs Secrets Manager?
   - IAM: wildcards on actions or resources?
   - Idempotency: Slack retries (X-Slack-Retry-Num) handled?
   - Error paths: what does the user see when Bedrock or DynamoDB fails?
   - Retries: X-Slack-Retry-Num is sent by the Events API, not slash commands. For each handler, state which Slack surface calls it and whether it is retried.
   - Credentials: does the tutorial rely on long-lived IAM access keys?

4. KEEP / REWRITE / DROP
   For each inventory row, one verdict and one-line reason.

5. SLICE PLAN
   Vertical slices, each end-to-end and independently testable offline.
   For each: goal | files in scope | acceptance check (exact pytest command) |
   depends on. Slice 1 must be the thinnest path that proves the skeleton:
   a signed Slack slash-command request reaches a handler, is verified,
   acked, and a note is written to DynamoDB (moto).

CONSTRAINTS
- Do not invent files, functions, or APIs. If unsure, say UNVERIFIED.
- No deployment steps. No credentials. No network calls in proposed checks.
- Under 1,500 words. Tables over prose.
