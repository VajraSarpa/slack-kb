# SlackKB

A Slack knowledge base for incident notes, built on AWS. Someone types `/bnote <what happened>` in Slack. The note is verified, acknowledged at once, stored, and processed in the background. Later slices make the notes searchable and answer questions about them in Slack threads.

The repo has a second job: it is the test bed for **Pramā**, a coding-agent harness. Much of the code was written through Pramā, and paired tasks were also run with plain Claude Code under the same rules; the results are compared in `docs/`.

## Status

Built test-first, one slice at a time ([`docs/SLICES.md`](docs/SLICES.md)). The suite runs offline (`moto` for AWS, fake clients for Slack and Bedrock).

| Slice | What it does | State |
|---|---|---|
| 1 | `/bnote`: signature checked before parsing, ack, conditional put on `note_id` | done |
| 2 | Fast ack; SQS worker moves CAPTURED → ROUTED | done |
| 3 | Severity modal from a "Set severity" button | done |
| 2b | A note that fails after the DLQ tells its user | not started |
| 4 | Note written to S3 as OKF markdown; mutable state stays in DynamoDB | not started |
| 5–7 | Bedrock answers, retrieval, thread replies via the Events API | not started |
| 8–9 | SAM template (least-privilege IAM, Secrets Manager, DLQ), observability | not started |

Nothing here is deployed yet, and `infra/` is empty.

## How it works

```
Slack /bnote ──► capture (Lambda) ──► DynamoDB  (note, status CAPTURED)
                     │  verify signature, ack in < 3 s
                     └──► SQS ──► worker (Lambda) ──► status ROUTED
                           └── DLQ after repeated failures ──► FAILED (2b)
Slack button ──► modal (Lambda) ──► views.open / view_submission ──► severity
```

Each AWS or Slack boundary has exactly one module: `store.py` (DynamoDB), `queue.py` (SQS), `slack_api.py` (Slack Web API), `slack_verify.py` (request signatures). Later slices add `blob.py` (S3) and `llm.py` (Bedrock). Clients are passed in, never created at import. Settings come from `SLACKKB_`-prefixed environment variables via pydantic-settings.

## Run it

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest
uv run ruff check src tests
```

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
