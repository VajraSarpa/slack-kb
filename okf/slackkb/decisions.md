# Decisions (mirror of docs/DECISIONS.md)

- D-001 Fresh repo; tutorial code is read-only reference.
- D-002 Bedrock via llm.py; no direct Anthropic API.
- D-003 Capture via /bnote slash command. #log message capture deferred.
- D-004 Async processing via SQS with redrive DLQ.
- D-005 infra/ (SAM, IAM) is human-authored; agent may write tests for it.
- D-006 note_id = sha256(team_id:trigger_id), first 32 hex chars. Slash
  commands are not retried by Slack; the conditional put still blocks
  duplicates.
- D-007 Signing secret from pydantic-settings; Secrets Manager wiring in
  Slice 8.
- D-008 Retrieval store for Slice 6: undecided.
