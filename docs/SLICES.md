# SLICES

Written in Step 7 from the audit (`docs/audit-A0.md`), following the plan's slice map. "A0 #n" refers to the audit's DEFECTS table. Final gate for every slice: `uv run pytest` (the full suite).

| # | Goal | Files in scope | Acceptance check | Depends on |
|---|------|----------------|------------------|------------|
| 1 | `/bnote` verified, acked, stored. Verify the signature before parsing; body is form-encoded (A0 #5). Conditional put on `note_id` (D-006). | `models`, `slack_verify`, `store`, `config`, `capture` | `uv run pytest tests/test_capture.py::test_retry_does_not_duplicate` | – |
| 2 | Ack fast; the worker consumes SQS. Status CAPTURED → ROUTED, or FAILED after the DLQ (D-009). | `capture`, `queue`, `worker`, `config` | `uv run pytest tests/test_worker.py::test_ack_before_processing` | 1 |
| 2b | A note that goes FAILED after the DLQ tells its user via `response_url` (D-010). | `models`, `capture` (job carries `response_url`), `notify`, `slack_api` (fake) | `uv run pytest tests/test_notify.py::test_failed_note_notifies_user` | 2, D-018 |
| 3 | Severity modal (`views.open` + `view_submission`). Severity checked against the OKF enum. Opens from a "Set severity" button in the `/bnote` ack; needs a bot token (D-013). | `modal`, `slack_api` (fake), `capture` (button only), `store`, `config` | `uv run pytest tests/test_modal.py::test_modal_submission_updates_severity` | 2, D-013 |
| 4 | Worker writes the note to S3 as OKF: content in S3, mutable state in DynamoDB (D-014). Write S3, then CAPTURED → ROUTED. | `worker`, `blob`, `okf_note`, `config` | `uv run pytest tests/test_okf_note.py::test_note_round_trips_as_okf` | 2, D-014 |
| 5 | Bedrock answer from retrieved notes, fake client. Untrusted text delimited, not `.replace()`-substituted (A0 #4). | `llm`, `qa` | `uv run pytest tests/test_qa.py::test_answer_cites_note_ids` | 4 |
| 6 | Embeddings + retrieval with the store chosen in D-008 (DynamoDB `note_vectors`). The worker writes the note's vector between S3 and ROUTED. `retrieve` is built here; Slice 7 wires it into `events`. | `embed`, `vectors`, `retrieve`, `worker`, `config` | `uv run pytest tests/test_retrieve.py::test_retrieval_excludes_frontmatter` | 4, D-008 |
| 7a | Events API ingress for @-mentions (D-017). Verify, then answer `url_verification`; ignore bot_id/subtype events; dedup retries on `event_id` instead of dropping them (A0 #2, D-011); enqueue a QuestionJob to its own queue; enqueue failure releases the claim and returns 500. | `events`, `dedup`, `queue`, `models`, `config` | `uv run pytest tests/test_events.py::test_retry_is_deduplicated` | 5, 6, D-011, D-017 |
| 7b | Question worker: the real `retrieve` (Slice 6) and `answer_question` (Slice 5), reply in the thread by channel + `thread_ts` (A0 #7); "no results" reply names the query (D-008); QaError → ephemeral (D-016). | `thread`, `slack_api` | `uv run pytest tests/test_thread.py::test_reply_posts_in_thread_ts` | 7a |
| 8a | Lambda entry points and secrets (D-020): `entry.py`, one handler per Lambda; secrets by ARN at cold start; both secrets optional in Settings, `MissingSecret` at use (amends D-007). | `entry`, `config` (+ the secret checks in `capture`, `modal`, `events`, `thread`) | `uv run pytest tests/test_entry.py::test_capture_handler_loads_only_its_secret` | 1–9b |
| 8b | SAM template: least-privilege IAM, Secrets Manager, DLQ (D-004, D-008, D-018, D-020). Human-authored `infra/` (D-005). | `infra/template.yaml` | `cfn-lint infra/template.yaml` | 8a |
| 8c | Tests for the template; Pramā may write them (D-005). | `tests/test_infra.py` | `cfn-lint infra/template.yaml && uv run pytest tests/test_infra.py::test_no_wildcard_iam` | 8b |
| 8d | First deploy with the `slackkb-dev` SSO profile; pin D-012's model ID. Vajra only. | – | `sam deploy` succeeds; a `/bnote` round trip in the dev workspace | 8c |
| 9a | Correlation IDs and structured logs (D-019): trace = note_id / event_id, JSON lines, `obs.configure()`. | `obs` (+ the trace calls in `capture`, `modal`, `events`, `worker`, `thread`, `notify`) | `uv run pytest tests/test_obs.py::test_log_has_trace_id` | 2, D-019 |
| 9b | Token spend (D-019): one INFO line per Bedrock call with token counts. | `llm`, `embed` | `uv run pytest tests/test_llm.py::test_converse_usage_logged` | 9a |

Paths are under `src/slackkb/` unless shown otherwise.
