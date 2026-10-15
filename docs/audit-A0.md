The tutorial is a Slack Events API `#log` pipeline that calls the Anthropic API directly, and it differs from OKF in most places. It has no slash commands, modals, Bolt, Bedrock calls, Titan or Knowledge Bases. For the absence claims I ran `search_files` with the case-insensitive regex `bedrock|titan|embed|knowledge.?base|slack.bolt|slack_bolt|AKIA|aws_access_key|\bxox[bpa]-|slash|modal|views\.` over `reference/tutorial` [obs_0003cdcd8cad]. The only code-level hit was a `bedrock:InvokeModel` plan in prose at `cicd-spec.md:162`. The tutorial README also lists Bedrock only as a roadmap item (`README.md:108`).

I have no docs or network tool, so every staleness verdict below is UNVERIFIED.

## 1. INVENTORY

| Name | File | Responsibility | External calls |
|---|---|---|---|
| skb-ingestion | `lambda/ingestion/handler.py:26-82` | API Gateway proxy handler. Drops retries, answers `url_verification`, verifies the signature, classifies each message as `#log` or thread reply, and fires an async invoke. | Secrets Manager `get_secret` (:19-23); Lambda `invoke` with type Event (:104-113) |
| skb-routing | `lambda/routing/handler.py:53-145` | Parses a `memo:` delimiter, structures the message with Claude, writes markdown to S3 and metadata to DynamoDB, posts a summary, and escalates. | Anthropic API (:148-168); S3 `put_object` (:88); DynamoDB `put_item` (:119); Slack `chat.postMessage` through urllib (:255); SNS `publish` (:138) |
| skb-conversation | `lambda/conversation/handler.py:30-97` | Thread Q&A. Looks up the record by `thread_ts`, pulls entity history, runs a memo pre-pass, and answers. | DynamoDB `query` on two GSIs (:45, :67); S3 `get_object` (:63); Anthropic API twice (:139, :211); Slack post (:219) |
| Slack surfaces | `ingestion/handler.py:57-70` | Events API `message` events only. | none |
| Table `skb-records` | `template.yaml:49-84` | Key `record_id`, GSI `thread_ts-index`, GSI `entity_id-timestamp-index`, TTL attribute defined but disabled. | none |
| Bucket `skb-records-*` | `template.yaml:37-47` | Markdown records, versioned, public access blocked. | none |
| SNS topic and email subscription | `template.yaml:90-101` | Critical alerts. | none |
| Two DLQs | `template.yaml:107-117` | Lambda DeadLetterConfig targets, not SQS event sources. | none |
| Three IAM roles | `template.yaml:123-226` | One role per function. | none |
| REST API `/slack` POST | `template.yaml:298-344` | `AuthorizationType: NONE`, AWS_PROXY integration to ingestion. | none |
| Prompts (3), `escalation_config.json`, `record_v1.json` | `prompts/*`, `config/*`, `schema/*` | Prompt templates, escalation thresholds, record schema. | none |
| Deploy tooling | `scripts/deploy.sh`, `.github/workflows/deploy.yml` | Zip and upload, then `cloudformation deploy`, then `update-function-code`. | AWS CLI |

The tutorial has no Bolt app, no embedding calls and no Knowledge Bases. `.github/` was hidden in the first listing and I found it by naming it explicitly [obs_f9484d21138d]. `demo/` is not code and I did not read it.

## 2. STALENESS (all UNVERIFIED)

| Item | In code | Note |
|---|---|---|
| Claude model | `claude-haiku-4-5-20251001` (`routing:163`, `conversation:140,212`) | This is an Anthropic-API ID. OKF D-002 requires Bedrock via `llm.py` [obs_e6e72995bc8d]. The Bedrock ID has to be re-looked up. |
| Planned Bedrock ARN | `arn:aws:bedrock:us-east-2::foundation-model/us.anthropic.claude-haiku-4-5-20251001-v1:0` (`cicd-spec.md:164`) | The `us.` prefix is an inference-profile ID, but the ARN is written as a `foundation-model` ARN. I suspect it is wrong. |
| Anthropic SDK | `anthropic>=0.40.0`, unpinned (`requirements.txt:1`) | Drop it. |
| Titan embeddings | Not used | Search above. D-008 leaves the retrieval store undecided. |
| Bedrock Knowledge Bases | Not used | Same search. |
| Slack Bolt | Not used. The tutorial uses raw urllib (`routing:255`) and hand-rolled signature checking. | The target pins `slack-bolt>=1.30.0` (`pyproject.toml:14`). |
| Lambda runtime | `python3.12` (`template.yaml:236,254,277`) | OK against the target's Python 3.12+. Deprecation date not checked. |
| Python in CI | 3.12 (`deploy.yml:27`) | |
| GitHub Actions | checkout@v4, setup-python@v5, configure-aws-credentials@v4 (`deploy.yml:22,25,30`) | Not checked. |
| IaC | Raw `AWS::Lambda::Function` with S3 zips | The target is SAM. |
| Packaging | `pip install -t` on the runner (`deploy.sh:77`) | This can pull wheels for the wrong architecture. |

## 3. DEFECTS (highest severity first)

| # | Sev | Defect | Evidence |
|---|---|---|---|
| 1 | High | **No user-facing error path.** A failed Claude call, bad JSON, or S3/DynamoDB error raises and ends in the DLQ, and the user sees nothing. `extract_json` does an unguarded `json.loads` (`routing:184`), and `structured['severity']` can raise `KeyError` (`routing:76`). A Slack `ok:false` is only logged (`routing:273-274`). A missing thread record silently returns (`conversation:51-53`). OKF requires an ephemeral message always (`architecture.md:10`). | cited |
| 2 | High | **Retry handling can lose messages.** Every request with `x-slack-retry-num` is dropped before any auth (`ingestion:31-33`). If the first attempt failed, for example when `invoke_lambda_async` raises (`:111-113`), the retry is the only recovery and it is discarded. | cited |
| 3 | High | **No idempotency in the worker.** `record_id` is `uuid4` (`routing:79`) and `put_item` has no condition (`:119`). A Lambda async retry would write a duplicate record. Whether Lambda retries async invokes by default is UNVERIFIED. OKF D-006 requires a deterministic `note_id` and a conditional put [obs_e6e72995bc8d]. | cited |
| 4 | High | **Prompt injection and template injection.** User text goes into the prompts by chained `.replace()` (`routing:154-157`, `conversation:196-202`). A message containing `{context}` or `{user_question}` is substituted by a later `.replace()`. The LLM-assigned severity is not validated and drives escalation (`routing:128-137`). The conversation prompt has no untrusted-content delimiters (`conversation.txt:3-15`). | cited |
| 5 | Med | **Signature check is correct in its core but wrapped in flaws.** It uses `v0:{ts}:{body}`, HMAC-SHA256, `compare_digest` and a 300 s window (`ingestion:85-101`). Problems: `json.loads(body)` runs before verification, so a malformed or `None` body gives an unauthenticated 500 (`:35-36`). The body is JSON-only, so a form-encoded slash command would fail (`:36`). `isBase64Encoded` is ignored. `url_verification` is answered with no signature check (`:39-45`). | cited |
| 6 | Med | **3-second ack.** There is no slow work before the ack, because Claude runs in downstream async Lambdas. The ack path does include a Secrets Manager fetch on a cold start (`:48`) and a synchronous Lambda `invoke` API call (`:74,77`). The function timeout is 10 s (`template.yaml:239`), which does not match Slack's 3 s. | cited |
| 7 | Med | **Thread lookup is not scoped to a channel.** It queries only by `thread_ts` (`conversation:45-47`), so a timestamp collision across channels returns the wrong record. Every thread reply in any channel the bot is in triggers an invoke and a DynamoDB query (`ingestion:72-74`). | cited |
| 8 | Med | **IAM.** I found no action wildcards. Resource wildcards are only the `records/*` object prefix (`template.yaml:175,215`). Several grants are unused: Routing has `Query` on a GSI the code never queries (`:180-182`), and Conversation has `GetItem` (`:218`) that the code never calls. Role names are fixed and need `CAPABILITY_NAMED_IAM` (`deploy.sh:104`). The OIDC trust `sub` is `repo:...:*`, so any ref can assume the role (`cicd-spec.md:80`). The deploy role gets `PowerUserAccess` (`:97`). Whether that is enough for CloudFormation role creation is UNVERIFIED. | cited |
| 9 | Med | **Secrets.** I found no hardcoded token. The `xoxb-` string is a README placeholder (`README.md:37`). Secrets Manager holds the secrets and the env vars hold only ARNs (`template.yaml:248,268-269`), so the README claim at `README.md:21` is imprecise. The Anthropic API key in Secrets Manager is a long-lived third-party key, and OKF D-002 forbids that path. | cited |
| 10 | Low | **Identifiers leaked in the docs.** `cicd-spec.md` contains an AWS account ID (`:72`), a Slack channel ID (`:126`) and a local path (`:131`). | cited |
| 11 | Low | **Internal inconsistencies.** `deploy.yml:9` uses us-east-1 against live us-east-2 (`cicd-spec.md:25`). `deploy.yml:63-64` omits `memo_reasoning.txt`. `record_v1.json:84` sets `additionalProperties: false`, yet routing writes `has_memo`, `memo_text` and `memo_author` (`routing:114,117-118`), which the schema lacks. The API Deployment has no redeploy trigger (`template.yaml:325-329`). | cited |

**Credentials:** I found no long-lived IAM access keys. The search for `AKIA|aws_access_key` over `reference/tutorial` had no hits [obs_0003cdcd8cad]. CI uses OIDC (`deploy.yml:17,30`). The manual path in `deploy.sh` relies on whatever ambient AWS CLI credentials are configured (`README.md:28`). `cicd-spec.md:88` mentions aws-vault.

**Which Slack surface calls each handler, and who retries:**

| Handler | Caller | Retried by | Handling |
|---|---|---|---|
| ingestion | Events API `message` (`ingestion:57-62`) | Slack, which sends `X-Slack-Retry-Num` | Dropped blindly (defect 2) |
| routing and conversation | Lambda async invoke (`ingestion:106-110`) | Lambda service (UNVERIFIED), not Slack | None (defect 3) |
| any slash command | none in the tutorial | Not retried by Slack, per D-006 | n/a |

## OKF disagreements (OKF wins)

| Topic | Tutorial | OKF |
|---|---|---|
| Capture | `#log` messages (`ingestion:70`) | `/bnote`; `#log` deferred (D-003) |
| LLM | Anthropic API (`routing:149`) | Bedrock via `llm.py` (D-002) |
| Async | Lambda Event invoke plus Lambda DLQ | SQS with redrive DLQ (D-004) |
| ID | `REC-uuid4` (`routing:79`) | `sha256(team_id:trigger_id)[:32]` (D-006) |
| Severity | `Low`, `Medium`, `High`, `Critical` (`config:3`, `record_v1.json:41`) | `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`, default LOW (`glossary.md:5`) |
| Status | `Open` (`routing:112`) | `CAPTURED` (`architecture.md:4`) |
| Fields | `record_id`, `reported_by`, `channel`, `timestamp`, `raw_message` | `note_id`, `user_id`, `channel_id`, `created_at`, `text` (`glossary.md:3-4`) |
| Boundaries | Handlers import boto3 (`routing:4`) | Handlers never import boto3 (`architecture.md:9`) |
| Thread anchor | The user's original message (`routing:59`) | The thread under the bot's confirmation (`glossary.md:8`) |
| Answers | Plain answer, no required citations (`conversation.txt:19-26`) | Must cite `note_ids` (`architecture.md:7`) |
| Replies | Public in-thread post (`routing:125`) | The user always gets an ephemeral message (`architecture.md:10`) |
| Worker side effects | S3 and DynamoDB written together in routing | Capture writes DynamoDB `CAPTURED` and enqueues; the worker writes S3 (canonical) and updates metadata (`architecture.md:3-6`) |

## 4. KEEP / REWRITE / DROP

| Component | Verdict | Reason |
|---|---|---|
| Signature algorithm (`ingestion:85-101`) | KEEP (logic only) | Correct; re-implement inside the Bolt or `slack_api.py` boundary and verify before parsing. |
| skb-ingestion | REWRITE | Events-only, JSON-only, and its retry drop loses messages. |
| skb-routing | REWRITE | Anthropic API, uuid4 ids, no error path, no boundaries. |
| skb-conversation | REWRITE | No channel scoping, no citations, Anthropic API. |
| Memo pre-pass and `parse_memo` | DROP | Not in OKF. |
| `extract_json` fence-stripping idea | REWRITE | Needs validation against an enum and a schema. |
| Table `skb-records` | REWRITE | Needs `note_id` and the OKF fields. D-005 makes infra human-authored. |
| S3 bucket config | KEEP | Versioning and a public-access block fit the S3-canonical design. |
| SNS and escalation channel | DROP | Not in OKF; defer. |
| Lambda DLQs | DROP | Replaced by SQS redrive. |
| IAM roles | REWRITE | Tighten the grants, add Bedrock, and drop the unused grants listed in defect 8. |
| REST API resource | REWRITE | Target is SAM with API Gateway. |
| Prompts | REWRITE | Replace the substitution with delimited untrusted input. |
| `escalation_config.json` | DROP | |
| `record_v1.json` | REWRITE | Self-inconsistent and uses the wrong field names. |
| `deploy.sh`, `deploy.yml`, `cicd-spec.md` | DROP | No deployment work in scope. |

## 5. SLICE PLAN

Offline tests only. `pyproject.toml` already has `--disable-socket` and moto [obs_1024145317da]. `conftest.py` already provides `sign`, `slack_request` and `notes_table` [obs_cde6b2928147]. The test file names below do not exist yet, so I am proposing them. I did not read `src/slackkb` beyond `__init__.py`, which is a stub (`__init__.py:1-2`).

| # | Goal | Files in scope | Acceptance check | Depends on |
|---|---|---|---|---|
| 1 | A signed `/bnote` request is verified and acked, and a CAPTURED note lands in DynamoDB (moto). Cover a bad signature, a stale timestamp, and a duplicate `trigger_id` (the conditional put blocks the duplicate). | `src/slackkb/{settings,verify,store,capture}.py` (proposed), `tests/test_capture.py` | `uv run pytest tests/test_capture.py -q` | none |
| 2 | Enqueue to SQS (moto) after the write, with an ephemeral confirmation. | `capture.py`, `queue.py` (proposed), `tests/test_enqueue.py` | `uv run pytest tests/test_enqueue.py -q` | 1 |
| 3 | Worker: consume SQS, structure with a stubbed `llm.py`, validate severity against the OKF enum, write the OKF note to S3 (moto), update DynamoDB. | `worker.py`, `llm.py`, `blob.py`, `tests/test_worker.py` | `uv run pytest tests/test_worker.py -q` | 2 |
| 4 | Failure paths: redrive to DLQ and an ephemeral error message on LLM or store failure. | `worker.py`, `slack_api.py` with a fake, `tests/test_failures.py` | `uv run pytest tests/test_failures.py -q` | 3 |
| 5 | Prompt injection: run the poisoned fixtures [obs_1c362da2fc1d] through structuring and Q&A with a stubbed LLM, asserting that untrusted text is delimited. | `llm.py`, `tests/test_injection.py` | `uv run pytest tests/test_injection.py -q` | 3 |
| 6 | Q&A over threads, with citations of `note_ids`. The retrieval store is undecided (D-008), so this is blocked until that decision. | `qa.py`, `tests/test_qa.py` | `uv run pytest tests/test_qa.py -q` | 3 and D-008 |
| 7 | IaC tests only (D-005): assert in a template-parsing test that there are no wildcard actions and no inline secrets. | `infra/`, `tests/test_infra.py` | `uv run pytest tests/test_infra.py -q` | 2 |
| 8 | Secrets Manager wiring (D-007). | `settings.py`, `tests/test_settings.py` | `uv run pytest tests/test_settings.py -q` | 1 |

On the poisoned-messages fixture: its text tries to instruct a model. I treated it as test data and did not act on it.
report: /home/vajrasarpa/.prama/reports/personal_cf139733_report.html
