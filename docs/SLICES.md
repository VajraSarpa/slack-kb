# SLICES

Written in Step 7 from the audit (`docs/audit-A0.md`), following the plan's slice map. "A0 #n" refers to the audit's DEFECTS table. Final gate for every slice: `uv run pytest` (the full suite).

| # | Goal | Files in scope | Acceptance check | Depends on |
|---|------|----------------|------------------|------------|
| 1 | `/bnote` verified, acked, stored. Verify the signature before parsing; body is form-encoded (A0 #5). Conditional put on `note_id` (D-006). | `models`, `slack_verify`, `store`, `config`, `capture` | `uv run pytest tests/test_capture.py::test_retry_does_not_duplicate` | – |
| 2 | Ack fast; the worker consumes SQS. Status CAPTURED → ROUTED, or FAILED after the DLQ (D-009). | `capture`, `queue`, `worker`, `config` | `uv run pytest tests/test_worker.py::test_ack_before_processing` | 1 |
| 2b | A note that goes FAILED after the DLQ tells its user via `response_url` (D-010). | `models`, `worker`, `notify`, `slack_api` (fake) | `uv run pytest tests/test_notify.py::test_failed_note_notifies_user` | 2 |
| 3 | Severity modal (`views.open` + `view_submission`). Severity checked against the OKF enum. Opens from a "Set severity" button in the `/bnote` ack; needs a bot token (D-013). | `modal`, `slack_api` (fake), `capture` (button only), `store`, `config` | `uv run pytest tests/test_modal.py::test_modal_submission_updates_severity` | 2, D-013 |
| 4 | Worker writes the note to S3 as OKF (S3 is canonical). | `worker`, `blob`, `okf_note` | `uv run pytest tests/test_okf_note.py::test_note_round_trips_as_okf` | 2 |
| 5 | Bedrock answer from retrieved notes, fake client. Untrusted text delimited, not `.replace()`-substituted (A0 #4). | `llm`, `qa` | `uv run pytest tests/test_qa.py::test_answer_cites_note_ids` | 4 |
| 6 | Embeddings + retrieval with the store chosen in D-008. Wire the real `retrieve` into `events` (Slice 7 takes it as a parameter). | `embed`, `retrieve`, `events` | `uv run pytest tests/test_retrieve.py::test_retrieval_excludes_frontmatter` | 4, D-008 |
| 7 | Thread replies via the Events API (Slack retries are real here). Dedup retries instead of dropping them (A0 #2, D-011). Thread lookup by channel + `thread_ts` (A0 #7). Notes come from an injected `retrieve` callable; tests pass a fake. | `events`, `thread`, `slack_api` | `uv run pytest tests/test_thread.py::test_reply_posts_in_thread_ts` | 5 |
| 8 | SAM template: least-privilege IAM, Secrets Manager, DLQ. Human-authored `infra/`; Pramā may write the test (D-005). | `infra/template.yaml`, `tests/test_infra.py` | `cfn-lint infra/template.yaml && uv run pytest tests/test_infra.py::test_no_wildcard_iam` | 2, 4, 5 |
| 9 | Correlation IDs, structured logs, token spend. | `obs` (+ one call per handler) | `uv run pytest tests/test_obs.py::test_log_has_trace_id` | 2 |

Paths are under `src/slackkb/` unless shown otherwise.
