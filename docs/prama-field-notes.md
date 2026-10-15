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
