# Operator log

What the operator (Claude Code, `prama-fieldtest` skill) did around each Pramā run: preflight, commands, workarounds, manual checks, judgment calls. Pramā's own behavior goes in `prama-field-notes.md`; run results go in `task-ledger.md`.

Tags: `[workaround]`, `[manual verification]`, `[judgment]`, `[operator step Pramā should own]`, `[deferred to Vajra]`.

## 2026-10-15 — Step 6 audit (A0)
Logged after the fact; times approximate (local).
- ~04:45 built `prompts/00-audit.md` from the first-prompt file + 2 DEFECTS additions (retries surface, long-lived IAM keys). [judgment: placed after "Error paths"]
- ~04:45 did not run `prama ask` myself: permission prompts are `ask` and it spends Vajra's credit. [judgment]
- ~04:48 `prama ask` crashed: `profiles/personal.yaml` not found from the tool install → `--profile ~/Projects/Prama/profiles/personal.yaml`. [workaround]
- ~04:50 ValidationError `sandbox: bwrap` → installed tool older than Prama source (faa4f2e) → Vajra reinstalled. [workaround]
- ~04:52 missing `OPENROUTER_API_KEY` → export line from Prama HANDOFF. [workaround]
- 04:54 run 1 (`personal_3eac2d4a`) answered; answer text not in JSONL or report. [operator step Pramā should own]
- 04:57 run 2 (`personal_cf139733`) with `| tee docs/audit-A0.md`. [workaround]
- ~05:05 spot-checked 3 citations: `ingestion/handler.py:31-33`, `routing/handler.py:79,119`, `template.yaml:175,215` — all held. Also confirmed conftest has `notes_table`, `sign`, `slack_request`. [manual verification]
- ~05:05 traced duplicate `obs_eb82569d8230` to content-hash ids (two empty searches). [manual verification; field note]
- ~05:10 cost not recoverable from Pramā; ledger cost left TBD. [deferred to Vajra: OpenRouter dashboard]
- ~05:20 drafted `docs/SLICES.md` at Vajra's explicit request; 3 open items left for him. [deferred to Vajra]
