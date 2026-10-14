# Slack KB

A serverless AWS system that turns Slack messages into structured, searchable knowledge base records — powered by Claude.

Team members post `#log` messages in any Slack channel. The system captures them, runs them through Claude, structures the raw text into a typed record, stores it in S3 and DynamoDB, and responds in the same thread. Follow-up questions in the thread get conversational answers grounded in the record and the entity's prior history.

---

## Architecture

Three Lambdas behind API Gateway:

| Lambda | Role |
|---|---|
| `skb-ingestion` | Slack gateway — validates, deduplicates, routes |
| `skb-routing` | Claude structuring, S3/DynamoDB write, escalation |
| `skb-conversation` | Thread Q&A via Claude with full record context |

**Storage:** S3 (full markdown records) + DynamoDB (structured metadata + GSIs)  
**Escalation:** Configurable Slack channel + SNS for critical severity  
**Secrets:** AWS Secrets Manager — no credentials in code or environment variables

---

## Deployment

### Prerequisites
- AWS CLI configured
- Python 3.12 + pip
- 3 Secrets Manager secrets created (see below)
- Slack app created with `chat:write`, `channels:history`, `groups:history` scopes and Events API enabled

### Create Secrets Manager Secrets

```bash
aws secretsmanager create-secret --name skb/slack-signing-secret --secret-string "YOUR_SIGNING_SECRET"
aws secretsmanager create-secret --name skb/slack-bot-token --secret-string "xoxb-YOUR-BOT-TOKEN"
aws secretsmanager create-secret --name skb/anthropic-api-key --secret-string "sk-ant-YOUR-KEY"
```

### Deploy

```bash
export SLACK_SIGNING_SECRET_ARN=arn:aws:secretsmanager:...
export SLACK_BOT_TOKEN_ARN=arn:aws:secretsmanager:...
export ANTHROPIC_API_KEY_ARN=arn:aws:secretsmanager:...
export SLACK_ESCALATIONS_CHANNEL_ID=C0XXXXXXXXX
export SNS_ESCALATION_EMAIL=oncall@example.com  # optional

chmod +x scripts/deploy.sh
./scripts/deploy.sh
```

The script will print the Slack Events URL to configure in your Slack app.

---

## Usage

Post any message containing `#log` in your connected Slack channel:

```
#log service is returning 502s on /api/checkout — started about 10 minutes ago
```

Slack KB will reply in the thread with a structured record. Reply in the thread to ask Claude follow-up questions:

```
Has this happened before?
What was the last resolution?
```

---

## Configuration

Edit `config/escalation_config.json` to change escalation thresholds or entity defaults.  
No code changes required.

---

## Key Design Decisions

| Decision | Choice | Reason |
|---|---|---|
| Slack 3-second timeout | Ingestion returns 200 immediately; async invokes downstream Lambdas | Slack retries if no response within 3s; Claude calls take longer |
| Retry deduplication | Check `x-slack-retry-num` header | Prevents duplicate records from Slack retries |
| Dead Letter Queues | SQS DLQ on routing and conversation Lambdas | Silent async failures are caught for inspection |
| Claude JSON parsing | Strip markdown fencing before `json.loads()` | Claude occasionally wraps JSON in backticks despite instruction |
| `thread_ts` type | Stored and compared as string throughout | Float conversion loses precision on Slack timestamps |
| Secrets caching | Module-level `_secrets_cache` dict | Avoids repeated Secrets Manager calls on warm invocations |
| Config externalization | `config/escalation_config.json` bundled in routing Lambda zip | Thresholds changeable without code changes |
| DynamoDB TTL | Attribute defined, disabled | Ready for lifecycle management without a schema migration |
| IAM | One least-privilege role per Lambda | Each function has exactly the permissions it uses |

---

## Roadmap

**Phase 2**
- Entity registry in DynamoDB
- QR code / deep link pre-population
- GitHub Actions CI/CD

**Phase 3**
- OpenSearch Serverless for full-text and semantic search
- Web UI for browsing and searching record history
- Bedrock migration option
- Dedicated `#claude-ops` query channel
- Dashboard for record trends by entity, severity, category
