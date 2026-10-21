# Pramā vs plain Claude Code (agreed 2026-10-20; bar revised 2026-10-21)

The question this answers: where does the Pramā harness beat or trail plain Claude Code on the same SlackKB tasks, and what should Pramā fix next? Pramā's own numbers (median 59 s, $0.24 per task) say nothing without a baseline.

## Paired rungs

Three build rungs, one per level of difficulty: **C2** (level 1), **C5** (level 3), **C11** (level 4, Slice 2). C7–C10 test harness behavior (spec gate, validity gate, āpta, absence) and have no meaningful baseline, so they run through Pramā only.

## How a pair runs

1. The prompt file (`prompts/<rung>.md`) is written and committed **before either run**, and not edited between them.
2. Both runs start from the same commit.
   - Pramā: `prama task` from the repo root as usual.
   - Claude Code: one fixed worktree `../slack-kb-cc` for every pair, so Claude Code's folder-keyed memory can build up the way Pramā's project memory can (C2: `git worktree add -b cmp/c2-claudecode ../slack-kb-cc <base>`; later pairs: `git -C ../slack-kb-cc switch -c cmp/<rung>-claudecode <base>`). Start a fresh session there with `claude --permission-mode acceptEdits --disable-slash-commands "$(cat prompts/<rung>.md)"`, no hand edits until it says done. Known difference: `~/Projects/CLAUDE.md` loads from the parent folder.
   - Alternate which runs first (C2 Pramā first, C5 Claude Code first, C11 Pramā first).
3. Record for each side: wall time, cost (Pramā from `prama stats`; Claude Code from `/cost`, notional if on subscription, and say so), attempts or turns, **interventions** (each time Vajra had to approve, answer, or fix something), checks pass/fail.
4. Blind review: a fresh Claude session gets both diffs labeled A and B (no names) plus the prompt, and lists defects in each. Vajra keeps the key.
5. One side merges (the better one, by Vajra's call). The other stays on a branch `cmp/<rung>-<side>` for scoring.
6. Any defect found later in that code is traced back and added to the row.

## Results

| rung | side | wall | cost | attempts/turns | interventions | checks | blind-review defects | later defects | merged |
|------|------|------|------|----------------|---------------|--------|----------------------|---------------|--------|
| C2 | Pramā (personal_ca90ad61) | 0m39s | $0.2721 | 1 attempt, 15 tool calls | 0 | 3/3 pass | pending | — | pending |

## Bar and review (Nov 11, 2026)

Pramā is the main project; this comparison steers its work, it doesn't decide whether it survives. Its claim is an accurate, reliable coding agent with good memory. Speed and cost are recorded but are not part of the bar.

1. **Accurate** (paired rungs C2, C5, C11). No worse than Claude Code on checks and blind-review defects, **and** either fewer interventions or a real catch Claude Code missed (gate stop, āpta flag, correct "not found", reviewer catch), as logged in `prama-field-notes.md`.
2. **Reliable** (every build rung and slice, from the ledger).
   - At least 80% of build tasks reach `ready_for_human` on attempt 1, not counting attempts lost to a harness defect already logged before the run.
   - Zero false "done": no session reports ready while its diff is empty, out of scope, or failing a check rerun by the operator.
   - Blocking harness defects found in Phase 2 are fewer than in Phase 1.
3. **Memory** (every rung from C3). Any lesson the operator has to write into a prompt's CONTEXT more than once is a memory candidate (table below). By Nov 11, at least half of the candidates are stored and recalled on a later run with the prompt line removed, and no recalled memory is wrong (a stale or false memory counts against the bar).

On Nov 11 the results go in `docs/verdict.md`. For each place Pramā fell short, record the cause in the code and turn it into an item for the next round of Pramā work. A shortfall is a result, not a reason to stop.

## Lessons (memory candidates)

| lesson | first carried by hand | proposed by Pramā (session) | stored | prompt line dropped at | recalled / repeated / not stored |
|--------|----------------------|-----------------------------|--------|------------------------|----------------------------------|
| `uv` not on sandbox PATH; use `python -m` | C1 | — | no | — | not stored |
| fixtures + conftest read-only | C1 | — | no | — | not stored |
