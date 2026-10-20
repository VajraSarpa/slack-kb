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

## 2026-10-17 — Preflight before C1
- preflight: HANDOFF "last substantive" says `5c9268e`, but `cc246b0` (skill + operator log) is substantive too → fix at close. [judgment]
- preflight: install receipt Oct 15 04:52 vs Prama head `32fa8a4` (Oct 15 23:29); 7 code commits since (sandbox, worktree, agent, session, acp) → asked Vajra to reinstall. [workaround; Pramā doesn't warn on a stale install]
- preflight: `~/.prama/projects/slack-kb.yaml` missing → needs `prama project init` + hand edit + `prama prepare` before any `task` with checks. Drafted contents for Vajra; he writes the file ("Only you edit this file"). [deferred to Vajra]
- preflight: `OPENROUTER_API_KEY` can't be confirmed from operator shell; Vajra exports it in his. [judgment]
- preflight: SLICES.md 3 open items still present; they gate Slice 2/7, not C1. [deferred to Vajra]

## 2026-10-20 — C1 blockers
- preflight: HANDOFF says `main` in sync with origin; git shows ahead 1 (`adb50fa` unpushed). [judgment; Vajra pushes]
- preflight: install Oct 19 12:15 vs Prama head `a9d22b6` (Oct 20 12:20); code commits since: `31a4ce8` (progress lines, gate.py), `6c014a9` (`prama stats`) → asked Vajra to reinstall. Second stale install in a row. [workaround; Pramā doesn't warn on a stale install]
- preflight: profile path present; `~/.prama/projects/slack-kb.yaml` still missing; API key not visible from operator shell. [deferred to Vajra]
- 12:25 Vajra reinstalled; receipt 12:25:40 > source `a9d22b6` 12:20. Blocker 1 done.
- 12:26 read `project init --help` ("Never overwrites") and `prepare --help` ("network; T3, you approve") before asking Vajra to run them. [judgment]
- 12:30 `project init --name slack-kb` wrote `trusted: false, checks: [], setup: null`, no `lockfile` key. Verified draft against Prama source before edit: `projects.py:12` `extra="forbid"` + `lockfile` field exists; `cli.py:256` runs setup via `bash -c` with `PRAMA_ENV`; `sandbox.py:86` puts `{env}/bin` first on PATH; `pyproject.toml` dev group has pytest, pytest-socket, ruff, moto. Draft holds. [manual verification]
- 12:30 init template omits `lockfile:` though `envs.py:14` hashes it to detect a stale env; without it, a changed `uv.lock` wouldn't force re-prepare (inferred from `lock_hash`). [field note candidate]
- 12:35 Vajra saved slack-kb.yaml; loaded it with Prama's own `load_project` from the tool venv: validates, all fields as drafted. Blocker 2 done. [manual verification]
- 12:35 Vajra ran `prama prepare`, replied "ready" (output not pasted). Confirmed myself: `envs/slack-kb/82ef87d9d3b99379/.ready` at 12:35:41; pytest, moto, pytest_socket import; ruff 0.17.0. Blocker 3 done. [manual verification]
- 12:37 looked for a record of the prepare T3 approval: no file under ~/.prama (outside envs/) written after 12:34; `gate.decide` doesn't log. Reason line lost with the scrollback. [field note]
- 12:45 Vajra: C1–C6 first, SLICES.md open items before C11 (operator's recommendation). Blocker 4 done. [judgment, Vajra decided]
- 12:50 triaged 6 field notes against Prama `a9d22b6`: none fixed yet; corrected the obs-id note (args are stored in index.jsonl, id still collides). [manual verification]
- 13:00 C10 prep: ran plan's grep before the run → 6 hits, retries handled at `ingestion/handler.py:31-32`. Skill ladder + HANDOFF said expected "not found"; plan p.20 says "passes if it matches your grep". Corrected C10 row and the C7–C10 rules in skill (live + snapshot) and HANDOFF. [judgment; operator skill was wrong]
- 13:05 Vajra asked to work on C10 before C1–C6. C10 is a read-only `ask` with no code dependency, so order doesn't affect it; runs before field-note #4 (obs-id collision) is fixed, which makes it a baseline. [judgment; deviation logged in HANDOFF]
- 13:05 prompt `prompts/c10-absence.md` = plan p.20 question verbatim, joined onto one line. Changes from plan command: `prama` (tool install) instead of `uv run prama` (prama isn't a slack-kb dep); `--profile <path>` (field note #1); `| tee docs/runs/c10.md` (ask keeps no answer, field note #3). [workaround]
- 12:44 Vajra ran C10; pasted only the last line. Read the full answer from `docs/runs/c10.md` (tee) and session `personal_b0418dac`. [operator step Pramā should own: answer only exists because of tee]
- 12:50 verified against raw obs + files: (1) `handler.py:28,30-33` and 113-line count; (2) README 15/86/87 verbatim; (3) search pattern/path in `obs_a5cdc73b14c1` and its hits = answer's list; (4) absence claims: grep for event_id/idempot/attribute_not_exists/ConditionExpression/seen over whole tree incl. `.github` → only 2 KeyConditionExpression reads; (5) handler 81-113 (unread by Pramā) has nothing relevant. All held. [manual verification]
- 12:55 traced "1 hidden entry" to `.github`; read pydantic_ai_harness `_toolset.py` to confirm `search_files` prunes hidden dirs silently. [manual verification; field note]
- 13:10 read report `personal_b0418dac_report.html` (2.6 KB, 8 events): a table render of the JSONL; no answer text, cost, tokens, or search pattern (gate row shows only `path`). Nothing beyond the JSONL. [manual verification]

## 2026-10-20 — C1 (models.py)
- 13:20 built `prompts/c1-models.md` from plan p.17 C2 template + p.18 C1 row. Field list from first-prompt Slice 1 req 3 + `okf/slackkb/glossary.md`. Operator choices Vajra should review: `created_at` as str with +00:00; `NoteStatus` enum with CAPTURED only (D-009 not yet written); CaptureRequest field set taken from `slash_bnote.json`, extras ignored. [judgment; deferred to Vajra review]
- 13:20 `uv` lives only at ~/.local/bin; `sandbox.py:83` PATH excludes it, and checks run sandboxed (`wiring.py:66`). Plan's `--check "uv run pytest ..."` would fail as "command not found" (inferred). Used `python -m pytest tests/test_models.py`; dropped plan's ruff check (project file already has it); told the agent in CONTEXT that `uv` isn't on PATH (AGENTS.md says `uv run pytest`). [workaround; plan deviation]
- 13:20 `--scope` is prompt text only (`session.py:59`, `agent.py:46`); no write enforcement found. Passing `--scope` anyway; diff read must check scope by hand. [field note]
- 13:26 Vajra ran C1; read `docs/runs/c1.md` + `personal_6c24565c.jsonl`. needs_human, agent_blocked at 20:25:59. [observed]
- 13:30 confirmed `slackkb.pth` → main checkout src; in worktree: without PYTHONPATH collection error, with PYTHONPATH=src 5 passed; ruff clean either way; `git status` shows only the 2 in-scope files. Read the full diff. [manual verification]
- 13:34 tested workaround without touching files: `pytest -o pythonpath=src` in the worktree → 5 passed; with src first on sys.path, `slackkb.models` resolves to the worktree file. Recommending Vajra add `pythonpath = ["src"]` to pyproject and rerun C1. [manual verification; workaround pending Vajra]
- 13:45 session close: HANDOFF rewritten for a fresh session (State/Runs/open defects/Next/Carry-overs); C1 check deviation added to Deviations. Uncommitted work listed in commit command to Vajra. [judgment]

## 2026-10-20 (later) — C1 rerun prep
- preflight: git = handoff (`da79aec`, clean, tracks origin); install 12:25 vs Prama `a9d22b6` 12:20 → current; profile and `~/.prama/projects/slack-kb.yaml` present; API key: Vajra to confirm in his shell. [manual verification]
- `~/.prama/worktrees/` holds 17 worktrees, not only `personal_6c24565c`. Cleanup (Next 5) needs `prama clean --help` read first. [observed; field note candidate: worktrees accumulate]
- Vajra reviewed C1 choice 1: `created_at` stays str (+00:00). [deferred to Vajra → decided]
- Vajra reviewed C1 choice 2: `NoteStatus` = CAPTURED only; ROUTED/FAILED wait for D-009. [deferred to Vajra → decided]
- Vajra reviewed C1 choice 3: drop `response_url` from CaptureRequest (handler never calls it, C5 carry-over); edited prompt req 4. All three C1 choices settled. [deferred to Vajra → decided]
- 20:45Z Vajra ran C1 r2 (personal_b0d5049b); read `docs/runs/c1-r2.md` + 38-line JSONL. ready_for_human, $0.2098. [observed]
- verified in the worktree with the prepared env's python: (1) full suite 5 passed, ruff clean, `slackkb.models.__file__` = worktree path; (2) `git status` = only `src/slackkb/models.py` + `tests/test_models.py` (A); (3) stripped the noqa → ruff reports 2 errors (UP042), agent's inference held; (4) `CaptureRequest` has no `response_url`, `"URGENT"` test present and passing. [manual verification]
- traced `reviewed: false` to `wiring.py:54` (`--review` only) and `cli.py:327` (apply always reviews). My handoff expectation was wrong; the review happens at `prama apply`. [judgment; field note]
- `prama apply` refused: main had uncommitted run records (ledger, field notes, operator log, `docs/runs/c1-r2.md` from tee). Committing them first. Clean-tree guard is reasonable; it means the tee output for each run has to be committed before apply. [workaround]
- 20:55Z Vajra committed records (`11622e0`), ran `prama apply personal_b0d5049b`; read `apply_review` (PASS) from the JSONL and recommended merge. Vajra merged (`430a886`), ran `uv run pytest` on main: 5 passed. [observed]
- read `prama clean --help`: dry-run by default (lists without `--yes`), `--older-than` days (default 7), never touches flagged sessions unless `--session`. Cleanup deferred to next session, dry run first. [judgment]

## 2026-10-20 (late) — worktree cleanup (Next 2)
- preflight: git = handoff (`48f609e`, clean, now in sync with origin, so the push is done); install 12:25 vs Prama `a9d22b6` 12:20 → current; profile path and project yaml present. [manual verification]
- `prama clean` (default 7 days): nothing listed. `--older-than 0`: 12 listed. 18 dirs on disk. [observed]
- mapped each worktree to its repo via `git rev-parse --git-common-dir`: 2 slack-kb, the rest rupa/Mula/v3-lab/prama-scratch. The 6 unlisted are flagged (`needs_human` / `hard_flagged` in the JSONL). [manual verification; field note]
- slack-kb's two: `b0d5049b` merged (`main..branch` empty); `6c24565c` has no commits past main, only the uncommitted run-1 models.py/test_models.py, superseded by r2 and recorded in `docs/runs/c1.md`. Recommended `--session` per id, not `--older-than 0 --yes`, so other projects' worktrees are left alone. [judgment; deferred to Vajra]
- 17:26 Vajra removed both slack-kb worktrees (`--session`). [observed: gone from ~/.prama/worktrees]
- 17:30 probed defect #1 before fixing: temp detached worktree in scratchpad, `prama.sandbox.run_sandboxed` with the slack-kb env; main's src not visible in the sandbox, import fails loudly. Corrected the field note; removed the temp worktree. [manual verification]
- 18:05 live check of the fix (temp detached worktree, removed after): binds `wt/src → slack-kb/src`; import from `/` works; `pytest -o pythonpath=` 5 passed; `git status` works. [manual verification]
- my step-1 script used a relative path; Vajra ran it from slack-kb, so the fix branch was created here. He deleted it; nothing else changed. [operator error]

## 2026-10-20 (night) — C2, Pramā side of the pair
- preflight: install 18:13:51 vs Prama `277b80a` 18:13:11 → current; profile + project yaml + env present; key: Vajra's shell. git `f37d7ce`, clean = base for both sides. [manual verification]
- prompt `prompts/c2-slack-verify.md` = plan p.17 + C1 conventions (uv-not-on-PATH, fixtures read-only, "All checks"); left out isBase64Encoded/form decoding (C5's job) and where SignatureError lives (fair test for both sides). Committed `f37d7ce` before either run. [judgment]
- command: `prama task … --check "python -m pytest tests/test_slack_verify.py" --scope "src/slackkb/slack_verify.py, tests/test_slack_verify.py" --profile <path> | tee docs/runs/c2.md`. [workaround: profile path, python -m]
- read JSONL (34 lines): all gates rule-decided, T0 reads / T1 writes / T2 commands; tests written and run before the implementation; session_end ready_for_human, $0.272096. Wall 0m39s from `prama stats`. [observed]
- verified in the worktree with the env python: 17 passed, ruff clean; `git status` = only the two scoped files (A); no logging/print in slack_verify.py. [manual verification]
- diff read notes for Vajra: base string uses the parsed int, not the raw header (harmless, same as Slack for well-formed headers); `_event()` wrapper is redundant; `test_sign_helper_matches_expected_format` tests conftest, not slackkb. 4 tests beyond the 6 required (tampered body, boundary, non-integer ts, sign helper). [judgment]
- not running apply yet: comparison step 4 wants both diffs before either merges. [judgment]
