# Task ledger

One row per task run. Pull outcome, attempts, and cost from Pramā's JSONL events.

| date | task_id | level | slice | outcome | attempts | cost | disposition | cause (if not passed) |
|------|---------|-------|-------|---------|----------|------|-------------|------------------------|
| 2026-10-15 | A0 (personal_cf139733) | — | audit | pass | 2 (run 1 personal_3eac2d4a answered, text not captured) | TBD (OpenRouter dashboard; Pramā logs no cost) | kept → input to SLICES.md; saved as docs/audit-A0.md | — |
| 2026-10-20 | C10 (personal_b0418dac) | 6 | absence | pass (found `ingestion/handler.py:30-33` + `README.md:15,86,87`; matches grep; absence claims true) | 1 (3 tool calls, all T0, ~10 s) | TBD (OpenRouter dashboard; `ask` logs no cost) | kept; saved as docs/runs/c10.md | — |
| 2026-10-20 | C1 (personal_6c24565c) | 1 | 1 | needs_human (agent blocked: env imports main checkout, not worktree) | 1 (21 tool calls; no checks run, no review) | $0.3084 (session_end spent_usd) | pending Vajra | Pramā defect: prepared env has editable `slackkb.pth` → /home/vajrasarpa/Projects/slack-kb/src, so worktree tests import main. Code itself correct: 5 passed with PYTHONPATH=src (operator-verified). |
| 2026-10-20 | C1 r2 (personal_b0d5049b) | 1 | 1 | pass → ready_for_human (checks 3/3, claims PASS; review not run in task mode, runs at apply) | 1 (17 tool calls, ~31 s) | $0.2098 (session_end spent_usd) | pending Vajra diff read + `prama apply` | — (run 1 blocker worked around with pytest `pythonpath = ["src"]`, `548e2ff`) |
