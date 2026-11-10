# Harness changes from the SlackKB run (exit review, 2026-11-09)

One change per line. Each cites ledger rows by session id (`docs/task-ledger.md`). "Made" = merged in Prama during the run, with the branch. "Open" = proposed from evidence, not decided. The plan's starting points (slow checks, misclassified tiers, noisy spec-gate questions, OKF notes the agent kept needing) come first in each list where they apply.

## Made (in Prama `main`, reinstalled)

### Slow checks
- Traced mutants rerun only the changed test modules: 1026 s → 52 s on the 2b replay (`v3/traced-fast`). Rows: 56f4ef9d.
- Mutation budget spread over files and lines, every tried mutant logged (`v3/mutate-log`). Rows: a1e679e6.

### Misclassified tiers and write gating
- Shell commands that write files are logged as T1 writes and checked against scope (`fix/command-writes`). Rows: a3a6a180, b9a5284d.
- `--scope` is enforced, not just advice (`fix/scope`). Rows: 6c24565c (pre-run note), a3a6a180.

### Spec gate
- The gate runs before any worktree in `prama task`; Clarification exits 3, Rejection exits 4 (`fix/spec-gate`). Rows: 9b9c7f62, a4dc45a8.
- A goal that cites a `D-###` found neither in memory nor in DECISIONS.md stops with a Clarification (`v3/spec-cites`). Rows: 32b0de36, 4216ca65.
- The gate drops a check the shell can't parse (`v3/spec-check-shell`) or one that reads as English (`v3/prose-check`); a failed check's retry sees its output. Rows: 664906d3.
- A check that can't run (parse error, exit 127 on a missing program) stops the session on that attempt (`v3/check-cant-run`). Rows: 664906d3.

### Verification
- The sandbox binds the worktree's `src` where the editable `.pth` points (`fix/editable-worktree`). Rows: 6c24565c.
- `red_check`: new tests must fail on base (`fix/red-green`); it also logs the failing count and ids, and a wrong "N failed" claim is logged as `claim_miscount` (`v3/red-count`, `v3/red-count-log`). Rows: a3a6a180, 9cd39c31.
- `--mutate`: break changed lines and FLAG a survivor (`v3/mutation-check`). Rows: 601d2df4, 3a52171f (found offline), then live on 150aed83, 6cbec5fd, 150f0a7c, 182a6b1b, bfd73104, baf320ab.
- Tests-only diffs get traced mutants, files with matching names first (`v3/tests-only-red`). Rows: 56f4ef9d.
- An inference claim needs at least one evidence id, at verify the same as in eval (`fix/claim-rule`). Rows: 509380bc, 4a2f7ff2.

### Reviewer
- A task run without `--review` says "not reviewed; `prama apply` reviews" instead of a bare PASS (`fix/review-line`). Rows: b0d5049b.
- The in-loop reviewer (`--review`, used on every Sārathi slice after C3/C4 showed untested requirements reaching ready) sees the spec, and a spec-mandated behavior becomes a `spec:` finding, not a FLAG (`v3/review-spec`). Rows: 509380bc, 6845bfac, b0643eb9, a1e679e6.
- The reviewer asks whether each test fails without its guard (`v3/review-guard`). Rows: 601d2df4.
- Reviewer prompt lines: a round-trip test can't pin a format (`v3/roundtrip-line`); a `spec:` finding doesn't cover the workaround it forced (`v3/spec-workaround`). Rows: 19c4442c, 5b27c049.

### Āpta guard
- `suspected_injection` on the read itself, plus an `injection_check` against claims (`v3/apta-patterns`, `v3/apta-claims`). Rows: 41e8389e, 9a89ab99.
- Claude Code's Edit payload (`originalFile`) is no longer scanned as tool output (`v3/hook-edit-raw`). Rows: 9a89ab99, 6e469aa3.

### Apply and memory
- `prama apply --accept-flag` lands a review-FLAGged session after rerunning checks and review; the human still says y (`v3/accept-flag`). Rows: 08178cb0, 968bbbfd, 1712bfec, bfd73104, baf320ab.
- A refused or declined apply is logged (`v3/apply-log`). Rows: 09196b00, 42fb7364.
- `prama memory import` offers an UPDATE when a decision's line changed (`v3/mem-update`). Rows: f1bfaeb7, a59275d2.
- A memory proposal that restates a settled decision gets a note (`v3/mem-dup`). Rows: 7f96efd4.
- The Sārathi apply review logs the real model name (`v3/apply-model`). Rows: 08178cb0.

### Plumbing
- Key spend cap is its own failure kind, with a pre-flight check (`fix/key-budget`). Rows: f2e468b4.
- A transient model error resumes the conversation instead of restarting it (`fix/resume-history`). Rows: b9a5284d.
- Commit subjects use the goal, not the literal `GOAL` header (`fix/commit-subject`). Rows: b0d5049b, 877cd35a, 5c4058da.
- `prama clean` is per repo (`fix/clean-repo`); `ask` records its answer and cost (`fix/ask-record`); `project init` writes the lockfile field (`fix/project-init`); a check whose first program is missing in the sandbox (`uv run …`) fails fast before any model call (`fix/check-preflight`); no pydantic-ai banner (`fix/no-banner`). Rows: cf139733, b0418dac, 6c24565c, 509380bc.

## Open (Claude's proposals; none decided)

### Slow checks
1. Diff-basis `--mutate` still reruns every project check per mutant (≈3.5–5 min per attempt; 2 × 3.5 min of a 17-minute run). Run only the tests that import the mutated module, the way the traced basis does. Rows: 150f0a7c, f1bfaeb7, 08178cb0.

### Misclassified tiers
2. None of the tiers caused harm. Of 1,475 gate decisions in the slack-kb logs (T0 459, T1 614, T2 401, T4 1 deny, T3 0), the only questionable one is `rm -rf` of `__pycache__` at T2, three times, always inside the worktree. No change; listed so the 0 T3 count is read correctly: no task ever tried the network, so the T3 boundary was never tested here. Rows: ca90ad61, 601d2df4, 150f0a7c.

### Spec gate
3. The gate asked no noisy questions (one live Clarification, correct). Its noise is in the checks it writes: it left DONE WHEN's `cfn-lint` out of the checks. Make every command-shaped DONE WHEN line a check, or log it as dropped. Rows: 9e08772b. **Built 2026-11-09 on Prama `v3/done-when-checks`, merged `f70c4ca`; evidence in Prama `docs/v3-log.md`.**
4. Lint the prompt for requirements that name no test. This was the most common single cause of a FLAG: 9 rows trace to a requirement in Claude's prompt with no named test, or with a test value that can't fail. Before any attempt, the gate lists each REQUIREMENT with no matching TESTS line, as a Clarification or a warning. Rows: 45be297d, 08178cb0, 951da5c8, 09196b00, 5b27c049, 968bbbfd, 1712bfec, bfd73104, baf320ab. **Built 2026-11-09 on Prama `v3/spec-untested` (as a warning: a stop fired on 15/24 clean goals in the replay), not merged; evidence in Prama `docs/v3-log.md`.**

### Reviewer
5. Severity drift: one unchanged issue rated minor, then major, then major, and once that alone decided a hard flag. When review N raises a major on lines review N−1 rated minor and attempt N left unchanged, log `severity_drift`. Rows: 1712bfec, 19c4442c, 968bbbfd. **Built 2026-11-09 on Prama `v3/severity-drift`, not merged; evidence in Prama `docs/v3-log.md`.**
6. The reviewer rates untested handling of a value that can only come from an enum as a major. Score a prompt line on the seeded sets under the run rule before landing it. Rows: baf320ab.
7. Two attempts hard-flag fixable test gaps. Five of the nine hard flags were landed with `--accept-flag` on green, 0-survivor diffs whose majors were test-only, and the operator confirmed each as correct code. Options: keep `--accept-flag` (one human command) or add a `ready_with_findings` end state. Claude's recommendation: keep it; the human read is the point. Rows: 08178cb0, 968bbbfd, 1712bfec, bfd73104, baf320ab.

### Verification
8. A tests-only run over a non-Python subject (YAML) gets no automatic red evidence: 0 traced files, 0 mutants. Let the tracer follow files the tests open, and mutate those lines; or have the claim check mark a "failed before" claim with no attached run as unbacked. Rows: 1712bfec, 9e08772b.

### Āpta guard
9. The injection detector fired on the project's own DECISIONS.md ("the system prompt is a fixed constant"), and `apply` then needed `--accept-findings` on clean work. Skip the scan for hits in human-owned spec files of a trusted project, and attach the hit's path and line. Rows: b71ecc5d. **Built 2026-11-09 on Prama `v3/own-spec`, merged `e9e56c6`; evidence in Prama `docs/v3-log.md`.**
10. The original poisoned-README test is still untested on an organic read: in three runs (both drivers and Claude Code) no side ever opened the README. Rows: 85e3fad9, a02d84ab.

### OKF notes the agent kept needing
11. None found. Pramā offered one memory proposal in the whole run, and it duplicated d-018 (7f96efd4, declined). The two lessons carried by hand were carried by the harness's check list instead (4f6c24dd). The missing-decision stops (32b0de36, 4216ca65) were the operator's: the decision wasn't committed. No change. Memory's measurable effect was the in-run `memory_check` events, with 0 violations on slices.

### Measurement
12. The hand-kept ledger missed a run: `personal_1cc03ac2` (8a-1 first run, ready attempt 1, $0.38 notional), found only by diffing the session logs against the ledger in this review. Generate ledger rows from the logs (`prama stats --repo … --ledger`) and keep only the disposition and cause columns by hand. Rows: 1cc03ac2, 42fb7364. **Built 2026-11-09 on Prama `v3/ledger`, not merged; evidence in Prama `docs/v3-log.md`.**
13. On Sārathi the notional cost cap ($2.00) stopped a working run before its last review, and nothing was spent. Cap Sārathi runs by share of the 5-hour window, not notional USD. Rows: 45be297d.
