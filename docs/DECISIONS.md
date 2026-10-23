# Decisions

- D-001 Fresh repo; tutorial code is read-only reference.
- D-002 Bedrock via llm.py; no direct Anthropic API.
- D-003 Capture via /bnote slash command. #log message capture deferred.
- D-004 Async processing via SQS with redrive DLQ.
- D-005 infra/ (SAM, IAM) is human-authored; agent may write tests for it.
- D-006 note_id = sha256(team_id:trigger_id), first 32 hex chars. Slash commands
        are not retried by Slack; the conditional put still blocks duplicates.
- D-007 Signing secret from pydantic-settings; Secrets Manager wiring in Slice 8.
- D-008 Retrieval store for Slice 6: undecided.
- D-010 The error path is its own slice (2b), not part of Slice 2: when a note
        goes FAILED after the DLQ, the user who ran /bnote gets an ephemeral
        message via response_url (30-min window; no bot token). The capture
        handler still never calls response_url; only the 2b path does.
- D-011 Events API retries (Slice 7) are deduplicated, not dropped. Key is
        Slack's event_id (same on every retry). Verify the signature first,
        then claim the key with a conditional put, then enqueue to SQS.
        Key already claimed -> 200, no work. Enqueue fails -> delete the
        claim and return 500, so Slack's retry is a real recovery (A0 #2).
        Keys live in their own DynamoDB table with a 1-hour TTL, not the
        notes table: they aren't notes, and Slack's retries end within
        minutes. The table is Vajra's to add in infra/ (Slice 8).
