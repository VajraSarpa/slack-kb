# Pramā vs plain Claude Code (agreed 2026-10-20; bar revised 2026-10-21)

The question this answers: where does the Pramā harness beat or trail plain Claude Code on the same SlackKB tasks, and what should Pramā fix next? Pramā's own numbers (median 59 s, $0.24 per task) say nothing without a baseline.

## Paired rungs

Three build rungs, one per level of difficulty: **C2** (level 1), **C5** (level 3), **C11** (level 4, Slice 2).

Two knowledge rungs (added 2026-10-22): **C9** (poisoned README, testimony) and **C10** (retry question, absence). Pramā's main claim is that it treats knowledge differently: claims carry their source (perception, inference, testimony, absence), and testimony and "not found" are checked before they count. The baseline is simply whether plain Claude Code believes the README or gets the absence answer wrong. C7–C8 (spec gate, validity gate) stay Pramā only.

How a knowledge pair differs from a build pair:
- No diff to blind-review. Score against criteria written into the prompt commit before either run: C10 = answer matches the grep (`ingestion/handler.py:31-32`), every citation holds, every "not found" claim is true (operator checks each); C9 = whether the side acted on the README's false claim, and whether it said the claim was unverified. Pramā's āpta flag counts; so does Claude Code saying the same thing in plain words.
- C10's Pramā side already ran (personal_b0418dac, 10-20, pass). Claude Code runs the same `prompts/c10-absence.md` in `../slack-kb-cc`; `reference/tutorial/` is unchanged since, so the base commit doesn't matter for a read-only question.
- C9 runs Claude Code first (C10 ran Pramā first). Both sides use the same throwaway `calib/poison` commit.

## How a pair runs

1. The prompt file (`prompts/<rung>.md`) is written and committed **before either run**, and not edited between them.
2. Both runs start from the same commit.
   - Pramā: `prama task` from the repo root as usual.
   - Claude Code: one fixed worktree `../slack-kb-cc` for every pair, so Claude Code's folder-keyed memory can build up the way Pramā's project memory can (C2: `git worktree add -b cmp/c2-claudecode ../slack-kb-cc <base>`; later pairs: `git -C ../slack-kb-cc switch -c cmp/<rung>-claudecode <base>`). Start a fresh session there with `claude --permission-mode acceptEdits --disable-slash-commands "$(cat prompts/<rung>.md)"`, no hand edits until it says done. Known difference: `~/Projects/CLAUDE.md` loads from the parent folder.
   - Alternate which runs first (C2 Pramā first, C5 Claude Code first, C11 Pramā first).
3. Record for each side: wall time, cost (Pramā from `prama stats`; Claude Code from the session JSONL token usage in `~/.claude/projects/-home-vajrasarpa-Projects-slack-kb-cc/` (`--disable-slash-commands` also blocks `/cost` and `/exit`; quit with Ctrl+C twice), notional if on subscription, and say so), attempts or turns, **interventions** (each time Vajra had to approve, answer, or fix something), checks pass/fail.
4. Blind review: a fresh Claude session gets both diffs labeled A and B (no names) plus the prompt, and lists defects in each. Vajra keeps the key.
5. One side merges (the better one, by Vajra's call). The other stays on a branch `cmp/<rung>-<side>` for scoring.
6. Any defect found later in that code is traced back and added to the row.

## Results

| rung | side | wall | cost | attempts/turns | interventions | checks | blind-review defects | later defects | merged |
|------|------|------|------|----------------|---------------|--------|----------------------|---------------|--------|
| C2 | Pramā (personal_ca90ad61) | 0m39s | $0.2721 | 1 attempt, 15 tool calls | 0 | 3/3 pass | 0B/0M/4m: base string from parsed int, not raw header; `int()` accepts `+`/space/`_`/Unicode digits (`+1700000000` verifies, operator-confirmed); redundant `_event` + test of conftest helper; no compare_digest test | — | no (worktree `personal_ca90ad61`, kept for scoring) |
| C2 | Claude Code (session 9bf6cdd6, Opus 5.5, `cmp/c2-claudecode`) | 8m09s door to door (18:59:42–19:07:51); ~1m10s of agent turns, ~3m35s stalled waiting | subscription; tokens: 3.3k out, 64k cache write, 228k cache read ($ TBD) | 2 turns, 6 tool calls | 3: stopped after tests with "No response requested." (Vajra typed `continue`), plus 2 Bash approvals (inferred from 11 s / 28 s waits in the log) | 17 passed, ruff clean (rerun with its venv) | 0B/0M/1m: no compare_digest test (reviewer's "non-deterministic now" dropped: fixture default ts is `time.time()`, `conftest.py:55`) | — | yes, `6db642c` (10-22) |
| C5 | Claude Code (session e2263261, Opus 5.5, `cmp/c5-claudecode` @ `adda6fd`) | 28m56s door to door (00:29:55–00:58:51 UTC 10-23); ~23 min waiting on an approval | subscription; tokens: 24.1k out, 124k cache write, 1.51M cache read ($ notional) | 1 turn, 12 tool calls | 3 Bash approvals | 44 passed, ruff `src tests` clean (operator rerun); branch commit `dc52bb7` | TBD | — | TBD |
| C10 | Pramā (personal_b0418dac, `ask`) | ~10 s | TBD (`ask` logs no cost) | 3 tool calls, all T0 | 0 | knowledge: found `handler.py:30-33` + README 15/86/87 = grep; all cites hold; absence claims true; `prama eval` 0 findings | n/a (knowledge pair) | — | n/a |
| C10 | Claude Code (`claude -p --permission-mode plan`, session 97e5a177, Opus 5.5) | 32 s | $0.389 (`total_cost_usd`, API-equivalent) | 7 turns | 0 (non-interactive) | knowledge: found `handler.py:30-33` + README 15/86-87 = grep; all 12 cites hold; absence claims true (operator grep) | n/a (knowledge pair) | — | n/a |

C2 blind review 2026-10-22: fresh subagent (Opus 5.5, packet only: prompt + A/B diffs), key A=Pramā B=Claude Code, kept outside the packet until review done. Same model family as the Claude Code side (bias noted).

C10 scored 2026-10-22: both sides accurate, no knowledge error either way, so no evidence for or against Pramā's claim on this rung. Differences: Claude Code searched wider (two pattern sets, whole files) and added two correct points Pramā didn't make (routing `put_item` has no condition and a random `record_id`; async invoke retries aren't covered by the header check); it also flagged the retry check running before signature validation, which Pramā noted too. Pramā tagged every claim with an obs id and named its own blind spots (read 1-80 of 113; 1 hidden entry not searched); Claude Code named its patterns and file count but no blind spots. Claude Code ran non-interactive (`-p`), not the build-pair protocol.

## Bar and review (Nov 11, 2026)

Pramā is the main project; this comparison steers its work, it doesn't decide whether it survives. Its claim is an accurate, reliable coding agent with good memory. Speed and cost are recorded but are not part of the bar.

1. **Accurate** (paired rungs C2, C5, C11, C9, C10). No worse than Claude Code on checks and blind-review defects, **and** either fewer interventions or a real catch Claude Code missed (gate stop, āpta flag, correct "not found", reviewer catch), as logged in `prama-field-notes.md`. On C9 and C10, a knowledge error Claude Code makes and Pramā doesn't is the most direct evidence for Pramā's claim; the reverse is a blocking Pramā defect.
2. **Reliable** (every build rung and slice, from the ledger).
   - At least 80% of build tasks reach `ready_for_human` on attempt 1, not counting attempts lost to a harness defect already logged before the run.
   - Zero false "done": no session reports ready while its diff is empty, out of scope, or failing a check rerun by the operator.
   - Blocking harness defects found in Phase 2 are fewer than in Phase 1.
3. **Memory** (every rung from C3). Any lesson the operator has to write into a prompt's CONTEXT more than once is a memory candidate (table below). By Nov 11, at least half of the candidates are stored and recalled on a later run with the prompt line removed, and no recalled memory is wrong (a stale or false memory counts against the bar).

On Nov 11 the results go in `docs/verdict.md`. For each place Pramā fell short, record the cause in the code and turn it into an item for the next round of Pramā work. A shortfall is a result, not a reason to stop.

## Lessons (memory candidates)

| lesson | first carried by hand | proposed by Pramā (session) | stored | prompt line dropped at | recalled / repeated / not stored |
|--------|----------------------|-----------------------------|--------|------------------------|----------------------------------|
| `uv` not on sandbox PATH; use `python -m` | C1 | — (C3, C4: no proposals at task or apply) | no | — | not stored; repeated C2, C3, C4 |
| fixtures + conftest read-only | C1 | — (C3, C4: no proposals at task or apply) | no | — | not stored; repeated C2, C3, C4 |
