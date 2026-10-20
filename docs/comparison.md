# Pramā vs plain Claude Code (agreed 2026-10-20)

The question this answers: where does the Pramā harness beat or trail plain Claude Code on the same SlackKB tasks, and what should Pramā fix next? Pramā's own numbers (median 59 s, $0.24 per task) say nothing without a baseline.

## Paired rungs

Three build rungs, one per level of difficulty: **C2** (level 1), **C5** (level 3), **C11** (level 4, Slice 2). C7–C10 test harness behavior (spec gate, validity gate, āpta, absence) and have no meaningful baseline, so they run through Pramā only.

## How a pair runs

1. The prompt file (`prompts/<rung>.md`) is written and committed **before either run**, and not edited between them.
2. Both runs start from the same commit.
   - Pramā: `prama task` from the repo root as usual.
   - Claude Code: `git worktree add ../slack-kb-cc-<rung> <base>`, open a fresh Claude Code session there, paste the same prompt, no hand edits until it says done.
   - Alternate which runs first (C2 Pramā first, C5 Claude Code first, C11 Pramā first).
3. Record for each side: wall time, cost (Pramā from `prama stats`; Claude Code from `/cost`, notional if on subscription, and say so), attempts or turns, **interventions** (each time Vajra had to approve, answer, or fix something), checks pass/fail.
4. Blind review: a fresh Claude session gets both diffs labeled A and B (no names) plus the prompt, and lists defects in each. Vajra keeps the key.
5. One side merges (the better one, by Vajra's call). The other stays on a branch `cmp/<rung>-<side>` for scoring.
6. Any defect found later in that code is traced back and added to the row.

## Results

| rung | side | wall | cost | attempts/turns | interventions | checks | blind-review defects | later defects | merged |
|------|------|------|------|----------------|---------------|--------|----------------------|---------------|--------|

## Bar and review (Nov 11, 2026)

Pramā is the main project; this comparison steers its work, it doesn't decide whether it survives. Pramā meets the bar if, across the paired rungs, it is **no worse** than Claude Code on checks and blind-review defects, **and** either needs fewer interventions or made a real catch Claude Code missed (gate stop, āpta flag, correct "not found", reviewer catch), as logged in `prama-field-notes.md`.

On Nov 11 the results go in `docs/verdict.md`. For each place Pramā fell short, record the cause in the code and turn it into an item for the next round of Pramā work. A shortfall is a result, not a reason to stop.
