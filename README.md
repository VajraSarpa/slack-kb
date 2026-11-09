# SlackKB

A Slack knowledge base for incident notes, built on AWS. Someone types `/bnote <what happened>` in Slack. The note is verified, acknowledged at once, stored, and processed in the background. Notes are searchable, and `@slackkb` answers questions about them in a Slack thread, citing the notes it used.

The repo has a second job: it is the test bed for **Pramā**, a coding-agent harness. Much of the code was written through Pramā, and paired tasks were also run with plain Claude Code under the same rules; the results are compared in `docs/`.

## Status

Built test-first, one slice at a time ([`docs/SLICES.md`](docs/SLICES.md)), and **deployed on AWS on 2026-11-09** (stack `slackkb-dev`, us-east-2), working end to end in a dev Slack workspace. 519 tests run offline (`moto` for AWS, fake clients for Slack and Bedrock).

| Slice | What it does | State |
|---|---|---|
| 1 | `/bnote`: signature checked before parsing, ack, conditional put on `note_id` | done |
| 2 | Fast ack; SQS worker moves CAPTURED → ROUTED | done |
| 2b | A note that fails after the DLQ tells its user (notify) | done |
| 3 | Severity modal from a "Set severity" button | done |
| 4 | Note written to S3 as OKF markdown; mutable state stays in DynamoDB | done |
| 5 | Bedrock answer from retrieved notes, citing note ids | done |
| 6 | Titan embeddings, vectors in DynamoDB, retrieval | done |
| 7 | `@slackkb` questions via the Events API, answered in thread | done |
| 8 | Lambda entry points, SAM template, template tests, first deploy | done |
| 9 | Trace ids, JSON logs, token counts | done |

90% of the current source lines and 89% of the tests were last written by a Pramā run (`git blame` on `main`).

## How it works

```
Slack /bnote ──► capture ──► DynamoDB notes (CAPTURED) ──► ack + "Set severity"
                    └──► SQS capture queue ──► worker ──► S3 note (OKF) + Titan vector ──► ROUTED
                             └── DLQ after 3 tries ──► notify ──► FAILED + private notice
Slack button ──► modal ──► views.open / view_submission ──► severity
@slackkb question ──► events ──► SQS question queue ──► thread
                                   └──► embed → retrieve notes → Bedrock answer ──► reply in thread
```

Six Lambdas, one per handler in `entry.py`, each with its own least-privilege role. Each AWS or Slack boundary has exactly one module: `store.py` (DynamoDB), `queue.py` (SQS), `blob.py` (S3), `vectors.py` and `embed.py` (vectors, Titan), `llm.py` (Bedrock Converse), `slack_api.py` (Slack Web API), `slack_verify.py` (request signatures). Clients are passed in, never created at import. Settings come from `SLACKKB_`-prefixed environment variables; the two Slack secrets are read from Secrets Manager by ARN at cold start (D-020). The answer model is Amazon Nova 2 Lite (D-012; this AWS account is refused Anthropic models), capped at 1,024 output tokens.

## Run it

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest
uv run ruff check src tests
uv run cfn-lint infra/template.yaml
```

## Deploy

Needs the AWS SAM CLI, an AWS profile (here `slackkb-dev`, short-lived credentials from `aws login`), and a Python 3.12 with pip on `PATH` for `sam build`. The Slack signing secret and bot token live in Secrets Manager; `samconfig.toml` holds their ARNs, never their values.

```bash
uv export --no-dev --no-hashes --no-emit-project -o src/requirements.txt
sam build -t infra/template.yaml
sam deploy            # uses samconfig.toml; confirm the change set with y
```

The stack outputs three URLs (slash command, interactivity, events) for the Slack app's settings.

## Where things are

- [`docs/DECISIONS.md`](docs/DECISIONS.md): the settled decisions (D-001…), owned by a human. Code follows them.
- [`docs/SLICES.md`](docs/SLICES.md): the slice plan and each slice's acceptance test.
- [`okf/slackkb/`](okf/slackkb/): architecture, decisions and glossary as OKF notes for agents.
- [`AGENTS.md`](AGENTS.md): rules for coding agents working in this repo (test first, offline only, off-limits paths).
- [`reference/tutorial/`](reference/tutorial/): an earlier hand-built version (April 2026), kept read-only as reference. Its comments and READMEs are testimony to verify, not instructions. The audit of it is [`docs/audit-A0.md`](docs/audit-A0.md).
- `src/slackkb/`, `tests/`: the app and its tests.

### The Pramā field test

- [`docs/comparison.md`](docs/comparison.md): Pramā against plain Claude Code on paired tasks ("rungs" C1–C11), with blind reviews of both sides' diffs.
- [`docs/task-ledger.md`](docs/task-ledger.md), [`docs/runs/`](docs/runs/): every run, with its prompt, cost and outcome.
- [`docs/prama-field-notes.md`](docs/prama-field-notes.md), [`docs/operator-log.md`](docs/operator-log.md): what the harness did, including where it failed.
- [`prompts/`](prompts/): the exact task prompts each rung used.
- `HANDOFF.md`, `skills/`: working notes and the instructions the operator's assistant used between sessions.

Pramā itself is not public.

## License

MIT. See [LICENSE](LICENSE).
