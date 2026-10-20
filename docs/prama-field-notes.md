# Pramā field notes

One line per harness event. Keep separate from the task ledger.

Topics to watch:
- Spec gate: accepted, clarified, or misread
- Attempts: how many to green, why failed ones failed
- Blind reviewer: catches tests missed
- Āpta guard: tutorial comment or README flagged as instruction
- Absence guard: wrong "not found" claims
- Validity gate: which calls hit T3; whether the tier was right
- Jev shadow: where its score disagreed with your approval

- 2026-10-15 Step 6 (A0, pre-run): `prama ask` crashed before any model call. `find_profile("personal")` resolves `profiles/` via `Path(__file__).parents[2]`, which exists in the source checkout but not in the `uv tool install` site-packages, so FileNotFoundError on `.../lib/python3.14/profiles/personal.yaml`. Packaging defect: profiles are not shipped with the wheel. Workaround: `--profile ~/Projects/Prama/profiles/personal.yaml`. Fix belongs in the Prama repo.
- 2026-10-15 Step 6 (A0, pre-run): installed `prama` was older than the source (`Profile.sandbox` Literal lacked "bwrap"; source has it since faa4f2e), so loading personal.yaml raised ValidationError. Setup drift, not a harness logic bug: reinstall after every Prama source change. Fix: `uv tool install --reinstall ~/Projects/Prama`.
- 2026-10-15 Step 6 (A0, personal_3eac2d4a): `ask` session answered, but neither the JSONL nor the HTML report holds the answer text, token counts, or cost. The audit only exists in terminal scrollback; ledger cost is unrecoverable from Pramā's own records.
- 2026-10-15 Step 6 (A0): two different `search_files` calls (08:54:56) both returned "No matches found." and share one observation id, `obs_eb82569d8230`, because ids are content hashes. Gate events don't log tool args either, so the log can't show which queries/paths came back empty. Absence claims cited to that id are not replayable from the record; this matters for C10.
- 2026-10-20 C1 blockers: `prama project init` template (`cli.py:445`) writes `checks: [], setup: null` and omits `lockfile`, though `Project` has the field and `envs.py:14` hashes it into the env id. A project set up from the template alone never re-prepares when `uv.lock` changes (inferred; confirm by editing uv.lock after prepare and checking `task` raises StaleEnvError). Also: install went stale again (Oct 19 install vs Oct 20 code commits `31a4ce8`, `6c014a9`); Pramā still doesn't warn.
- 2026-10-20 C1 blockers (`prama prepare`): T3 decision (network install) was approved by Vajra at a `run it?` prompt but written nowhere. No session JSONL, no gate event, no file under ~/.prama except the env itself. A T3 approval outside `task` is unauditable; the plan wants every non-T0 decision and who decided on record.
- 2026-10-20 correction to the 2026-10-15 obs-id note: args *are* recorded, in the observation store's `index.jsonl` (`observations.py:22`, one row per call). The defect stands narrower: id is `sha256(raw)` only, so two calls with equal output share an id and `find(obs_id)` can't tell them apart; the session JSONL `observation` event (`provenance.py:52`) has no args.
- 2026-10-20 C10 (personal_b0418dac): absence task passed. Found the retry drop at `ingestion/handler.py:30-33` and README 15/86/87; every cite matches the raw obs; absence claims ("no event_id tracking, no idempotency key") true over the whole tree incl. hidden. It stated its own blind spots unprompted: read only lines 1-80 of 113, and "1 hidden entry omitted" not searched. Good behavior; this is what the absence guard should produce.
- 2026-10-20 C10: `search_files` (pydantic_ai_harness `_toolset.py`, `include_hidden` false unless `include_glob` names a dot path) prunes hidden dirs and its output (`obs_a5cdc73b14c1`) carries no "hidden omitted" notice; only `list_directory` reports it. Here `.github` had no hits, so harmless. Risk: a confident "not found" that never looked in `.github/` etc. Absence answers should name skipped hidden paths; the search result should say it skipped them.
- 2026-10-20 C10: no absence-guard or claim event in the session JSONL or the HTML report (same 8 events as a table; the search_files gate row shows `path` only, not the pattern): only gate (3× T0, decider rule), observation, session_start/end. Can't tell from the log whether the absence guard ran or the model was just careful. Same `ask` gaps as A0: no answer text, no tokens, no cost; `prama stats` covers task sessions only.
- 2026-10-20 C10: obs-id collision seen across sessions: `obs_d9ca469316a2` (list_directory reference/tutorial) has index rows from 2026-10-15 (A0) and 2026-10-20. Same args here, so benign; confirms ids are global content hashes, not per call.
