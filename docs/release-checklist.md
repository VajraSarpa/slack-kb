# Release checklist: making this repo public

Plan agreed 2026-11-10: make slack-kb public this month. Each gate below must be checked before the visibility flip. Claude ran the scans; history rewrite and the flip are Vajra's.

| # | Gate | State (2026-11-10) |
|---|---|---|
| 1 | Secrets scan of full history | **Clean.** gitleaks v8.21.2, 354 commits (all refs), 0 findings. |
| 2 | No AWS account id or account ARNs | **Fails until history is rewritten.** The real account id appears in `samconfig.toml` (added `508dbd4`) and in an early `reference/tutorial/docs/cicd-spec.md` (`b3b21a4`, later replaced with `000000000000`). On `release-prep`, `samconfig.toml` is untracked and ignored, and `samconfig.example.toml` has placeholders. History still holds the id, so a rewrite is needed (below). |
| 3 | No employer data or internal Slack content | **No hits found.** No grep hits on employer domains, internal tool names, or Slack team/user ids. `amazon.*` hits are only Bedrock model ids. Vajra to confirm that the dev Slack workspace and any test notes were personal. |
| 4 | `reference/tutorial/` provenance | **Vajra to confirm.** Code from the April 2026 hand-built tutorial. Confirm it is his own work, or drop it from history if it came from licensed material. |
| 5 | IP terms reviewed | **Vajra, outside the repo.** |
| 6 | Re-scan after rewrite | Run gitleaks and the account-id grep again on the rewritten history. |

## Rewrite (after 4 is settled)

`git filter-repo` on a fresh mirror clone replaces the id in every commit:

```
echo "$(aws sts get-caller-identity --profile slackkb-dev --query Account --output text)==><ACCOUNT_ID>" > /tmp/ids.txt
git filter-repo --replace-text /tmp/ids.txt
```

This changes every SHA from `b3b21a4` on. SHAs quoted in docs, Pramā session logs and the Pramā repo's `slack-kb-commit-map.txt` will no longer resolve against the public repo. Pushing the rewrite needs a force push to `origin`.

## Check commands

```
podman run --rm -v "$PWD":/repo:ro,Z docker.io/zricethezav/gitleaks:v8.21.2 git /repo --redact --no-banner
git log -p --all | grep -oE '\b[0-9]{12}\b' | sort -u   # only 000000000000 and 123456789012 may remain
```
