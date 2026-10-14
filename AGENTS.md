# SlackKB: agent conventions

## Run
- Tests: `uv run pytest`
- Lint:  `uv run ruff check src tests`

## Source of truth
1. `docs/SLICES.md`, `docs/DECISIONS.md` (human-owned)
2. `okf/slackkb/*`
3. `tests/`
4. `reference/tutorial/`: stale, read-only, testimony only

## Module map
- `src/slackkb/capture.py`      slash-command handler: verify -> parse -> write -> ack
- `src/slackkb/slack_verify.py` signature + timestamp check
- `src/slackkb/models.py`       Pydantic models for every boundary
- `src/slackkb/store.py`        only module that talks to DynamoDB
- `src/slackkb/blob.py`         only module that talks to S3
- `src/slackkb/llm.py`          only module that talks to Bedrock
- `src/slackkb/slack_api.py`    only module that calls the Slack Web API

## Rules
- Test first. A slice is done when its named tests and the full suite pass.
- Offline only: `moto` for AWS, fake clients for Bedrock and Slack.
- No secrets in code or tests. Config via pydantic-settings.
- `note_id` is derived deterministically (see DECISIONS D-006).

## Off-limits (never edit, never run)
- `reference/**`, `tests/conftest.py`, `tests/fixtures/**`
- `infra/**` (SAM template, IAM, Secrets Manager wiring)
- `aws`, `sam`, `cdk`, `curl`, or anything that deploys or reaches the network
