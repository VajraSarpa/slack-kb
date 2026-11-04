Slack retries are handled in the ingestion Lambda. It ignores any request that Slack marks as a retry.

- **Handler:** `reference/tutorial/lambda/ingestion/handler.py:30-32`. A comment says this prevents duplicate incident creation. Line 31 checks `headers.get('x-slack-retry-num')` and also checks whether `x-slack-retry-reason` is `'http_timeout'`. Line 32 logs "Slack retry detected — ignoring to prevent duplicate processing". [obs_e80e04543168]
- **Docs:** `reference/tutorial/README.md:87` lists "Retry deduplication: Check `x-slack-retry-num` header". `README.md:86` explains why: Slack retries if it gets no response within 3s, so ingestion returns 200 immediately and invokes the downstream Lambdas asynchronously. `README.md:15` describes `skb-ingestion` as validating, deduplicating and routing. [obs_e80e04543168]

This is retry-header filtering only. My grep for `event_id`, `idempot`, `dedup` and `duplicate` (case-insensitive) across `reference/tutorial` found no event-ID-based deduplication. I did not open the handler beyond the matched lines, so I haven't checked what it returns after the ignore. [obs_e80e04543168]
(spent $0.0000, notional $0.0333)
report: /home/vajrasarpa/.prama/reports/personal_38dea6b0_report.html
