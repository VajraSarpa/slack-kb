# C10 — Claude Code side (knowledge pair)

- Command (from `~/Projects/slack-kb-cc`, branch `cmp/c2-claudecode` @ `6a21c7c`; `reference/tutorial/` identical to main): `claude -p --permission-mode plan --output-format json "$(cat prompts/c10-absence.md)"`
- Session `97e5a177-baf0-4a7f-b981-8682eaadbdaf`, 2026-10-22 19:50:53–19:51:28, 7 turns, 32.0 s, `total_cost_usd` 0.3894 (Opus 5.5 + Haiku 5.5), 0 permission denials. Raw: `docs/runs/c10-claudecode.json`.
- Non-interactive (`-p`), unlike the build-pair protocol: no chance for Vajra to intervene, so interventions = 0 by construction.

## Answer (verbatim)

reference/tutorial handles Slack retries in exactly one place, by dropping them. It does not deduplicate events anywhere.

**Retry handling: `reference/tutorial/lambda/ingestion/handler.py:30-33`**
```python
# Ignore Slack retries — prevents duplicate incident creation
if headers.get('x-slack-retry-num') or headers.get('x-slack-retry-reason') == 'http_timeout':
    logger.info('Slack retry detected — ignoring to prevent duplicate processing')
    return {'statusCode': 200, 'body': ''}
```
- Headers are lowercased first at `handler.py:28`.
- This check runs **before** the signature check (`:47-54`) and the `url_verification` branch (`:38-45`). So any request with an `x-slack-retry-num` header gets a 200 without being authenticated.
- The README states the design: `README.md:15` says ingestion "validates, deduplicates, routes", and `README.md:86-87` says "Retry deduplication | Check `x-slack-retry-num` header". In practice that "deduplication" is just dropping every retry.

**No real event deduplication.** I searched all 19 files under `reference/tutorial/` (case-insensitive) for `retry|retries|x-slack-retry|dedup|duplicate|event_id|client_msg_id|idempot`, and separately for `ConditionExpression|attribute_not_exists|already exists|already processed|seen`.
- No file reads `event_id` or `client_msg_id`, and there's no seen-events store.
- The only `KeyConditionExpression` hits (`lambda/conversation/handler.py:47`, `:69`) are read queries, not dedup guards.
- The routing Lambda's write, `table.put_item(Item=item)` at `lambda/routing/handler.py:119`, has no condition. Its key is random, `record_id = f"REC-{uuid.uuid4().hex[:8].upper()}"` at `:79`. So the same Slack message processed twice would produce two records.

**What follows from this:**
1. **The first attempt is never re-sent.** If it fails before the async invoke succeeds (e.g. a `secrets_client` or `lambda_client.invoke` error raised at `ingestion/handler.py:111-113`), Slack's retry is thrown away and the event is lost.
2. **Downstream retries aren't covered.** The async invoke at `handler.py:106-109` (`InvocationType='Event'`) uses AWS Lambda's default of 2 automatic retries. The CloudFormation template sets no `MaximumRetryAttempts` or `EventInvokeConfig`, only DLQs at `template.yaml:270-271` and `:291-292`. A routing failure partway through, after the S3 note is written but before `put_item`, can therefore produce a duplicate note or record, and the header check doesn't catch it.
