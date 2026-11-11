# Release checklist: making this repo public

Plan agreed 2026-11-10: make slack-kb public this month. Each gate below must be checked before the visibility flip. Claude ran the scans; history rewrite and the flip are Vajra's.

| # | Gate | State |
|---|---|---|
| 1 | Secrets scan of full history | **Clean.** gitleaks v8.21.2, 354 commits (all refs), 0 findings. |
| 2 | No AWS account id or account ARNs | **Pass (rewritten 2026-11-10).** The real id was in `samconfig.toml` and an early `reference/tutorial/docs/cicd-spec.md`. `git filter-repo --replace-text` replaced it with `123456789012` in every commit. `samconfig.toml` is untracked and ignored; `samconfig.example.toml` has placeholders. |
| 3 | No employer data or internal Slack content | **Pass.** No employer domains or internal tool names. Vajra confirmed (2026-11-10) the dev Slack workspace was his own and every test note was made up. The first scan missed two workspace ids, the escalations channel id (in `cicd-spec.md`) and the workspace domain (in `HANDOFF.md`); the same rewrite replaced them with `C0XXXXXXXXX` and `yourteam.slack.com`. |
| 4 | `reference/tutorial/` provenance | **Pass, kept.** Vajra's own April 2026 tutorial (the PDF names him as author); only the ids above changed. |
| 5 | IP terms reviewed | **Vajra, outside the repo.** |
| 6 | Re-scan after rewrite | **Clean (2026-11-10).** gitleaks v8.21.2 on the rewritten `main`: 0 findings. The 12-digit grep finds only `000000000000` and `123456789012`. No hits left for the channel id or domain. |

## Rewrite (done 2026-11-10)

`git filter-repo` on a fresh mirror clone replaces the id in every commit:

```
echo "$(aws sts get-caller-identity --profile slackkb-dev --query Account --output text)==><ACCOUNT_ID>" > /tmp/ids.txt
git filter-repo --replace-text /tmp/ids.txt
```

Done on a fresh mirror clone of `origin` (main only, 281 commits); the ids file held the account id, the channel id and the workspace domain. This changes every SHA from `b3b21a4` on (old SHAs map to new ones in the Pramā repo's `docs/slack-kb-commit-map.txt`). SHAs quoted in docs, Pramā session logs and the Pramā repo's `slack-kb-commit-map.txt` will no longer resolve against the public repo. Pushing the rewrite needs a force push to `origin`.

## Check commands

```
podman run --rm -v "$PWD":/repo:ro,Z docker.io/zricethezav/gitleaks:v8.21.2 git /repo --redact --no-banner
git log -p --all | grep -oE '\b[0-9]{12}\b' | sort -u   # only 000000000000 and 123456789012 may remain
```
