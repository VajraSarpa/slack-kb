# Slack KB v2 — GitHub / CI/CD Spec

**Date:** 2026-04-28

---

## What Already Exists

The CI/CD scaffold is complete inside the repo. Nothing needs to be designed — only wired up.

| Artifact | Path | Status |
|---|---|---|
| GitHub Actions workflow | `.github/workflows/deploy.yml` | Exists — 2 bugs (see below) |
| CloudFormation template | `infrastructure/cloudformation/template.yaml` | Exists — ready |
| Manual deploy script | `scripts/deploy.sh` | Exists — ready |
| Lambda source | `lambda/ingestion/`, `routing/`, `conversation/` | Exists — v1 code |
| Prompts | `prompts/` | Exists — includes `memo_reasoning.txt` |

---

## Bugs to Fix Before First Deploy

### Bug 1 — Wrong region in deploy.yml

`deploy.yml` hardcodes `AWS_REGION: us-east-1`. The live infrastructure is in `us-east-2`.

**Fix:** Change line 9 of `.github/workflows/deploy.yml`:
```yaml
AWS_REGION: us-east-2
```

### Bug 2 — deploy.yml doesn't copy memo_reasoning.txt

`deploy.sh` correctly copies `prompts/memo_reasoning.txt` into the conversation package.
`deploy.yml` only copies `conversation.txt` — it misses `memo_reasoning.txt`.

**Fix:** In the "Package and upload Lambda functions" step of `deploy.yml`, change:
```yaml
            if [ "$fn" = "conversation" ]; then
              cp prompts/conversation.txt $TMP_DIR/
            fi
```
to:
```yaml
            if [ "$fn" = "conversation" ]; then
              cp prompts/conversation.txt $TMP_DIR/
              cp prompts/memo_reasoning.txt $TMP_DIR/
            fi
```

---

## One-Time Setup Steps (in order)

### Step 1 — Create GitHub repo

Create a private repo on GitHub (e.g. `slack-kb`). Initialize without a README — the local code will be pushed as-is.

### Step 2 — Create the OIDC IAM role

GitHub Actions uses OIDC to authenticate with AWS — no static credentials stored in GitHub. This role needs to be created once in your `dev` account.

Create a trust policy file at `/tmp/github-oidc-trust.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::000000000000:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:YOUR_GITHUB_USERNAME/slack-kb:*"
        }
      }
    }
  ]
}
```

Then run (via aws-vault):

```
aws-vault exec dev -- aws iam create-role --role-name skb-github-deploy --assume-role-policy-document file:///tmp/github-oidc-trust.json
```

Attach a deploy policy (CloudFormation, Lambda, S3, IAM, CloudWatch Logs, API Gateway):

```
aws-vault exec dev -- aws iam attach-role-policy --role-name skb-github-deploy --policy-arn arn:aws:iam::aws:policy/PowerUserAccess
```

> **Note:** PowerUserAccess is broad but appropriate for a private dev account running CloudFormation with `CAPABILITY_NAMED_IAM`. Scope it down later if needed.

Also register the GitHub OIDC provider if not already present:

```
aws-vault exec dev -- aws iam create-openid-connect-provider --url https://token.actions.githubusercontent.com --client-id-list sts.amazonaws.com --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

### Step 3 — Get the existing Secrets Manager ARNs

The v1 secrets already exist. Retrieve their ARNs:

```
aws-vault exec dev -- aws secretsmanager list-secrets --region us-east-2 --query "SecretList[?contains(Name,'skb')].[Name,ARN]" --output table
```

### Step 4 — Add GitHub Actions secrets

In the GitHub repo → Settings → Secrets and variables → Actions, add:

| Secret name | Value |
|---|---|
| `AWS_ROLE_ARN` | ARN of `skb-github-deploy` role (from Step 2) |
| `SLACK_SIGNING_SECRET_ARN` | From Step 3 |
| `SLACK_BOT_TOKEN_ARN` | From Step 3 |
| `ANTHROPIC_API_KEY_ARN` | From Step 3 |
| `SLACK_ESCALATIONS_CHANNEL_ID` | `C0XXXXXXXXX` |
| `SNS_ESCALATION_EMAIL` | Your escalation email |

### Step 5 — Push to GitHub

From `/home/vajrasarpa/Home_Vault/Slack_KB_Project/slack-kb/`:

```
git init && git add . && git commit -m "Initial commit — Slack KB v1" && git remote add origin git@github.com:YOUR_GITHUB_USERNAME/slack-kb.git && git push -u origin main
```

---

## How It Works After Setup

Push to `main` → GitHub Actions triggers automatically:

1. Checks out code
2. Assumes `skb-github-deploy` role via OIDC (no credentials stored)
3. Packages each Lambda + its dependencies into a zip
4. Uploads zips to `s3://skb-deploy-000000000000/lambda/`
5. Runs `cloudformation deploy` (creates or updates the stack)
6. Force-updates each Lambda's code from S3 (catches code-only changes)
7. Prints the Slack Events endpoint

You can also trigger manually from the Actions tab (`workflow_dispatch`).

---

## v2 Changes (Bedrock migration — make before first deploy)

The CloudFormation template currently wires the `AnthropicApiKeyArn` secret into the routing and conversation Lambdas. For v2, these functions should call Claude via **Bedrock** (IAM-native, no API key).

Changes needed:

1. **Remove `AnthropicApiKeyArn` parameter** from `template.yaml` and both Lambda env var blocks
2. **Add `bedrock:InvokeModel` permission** to `RoutingLambdaRole` and `ConversationLambdaRole` for the inference profile ARN:
   ```
   arn:aws:bedrock:us-east-2::foundation-model/us.anthropic.claude-haiku-4-5-20251001-v1:0
   ```
3. **Add memo DynamoDB attributes** to the `RecordsTable` schema:
   - `has_memo` (Boolean)
   - `memo_text` (String)
   - `memo_author` (String)
4. **Update Lambda handler code** to use `boto3.client('bedrock-runtime')` instead of the `anthropic` SDK

The `memo_reasoning.txt` prompt already exists in `prompts/` — it just needs to be called from the conversation handler.

---

## Summary

| Task | Effort |
|---|---|
| Fix 2 bugs in deploy.yml | 5 min |
| Create GitHub repo | 2 min |
| Create OIDC IAM role | 10 min |
| Get secret ARNs | 2 min |
| Add GitHub secrets | 5 min |
| Push code | 2 min |
| Make v2 Bedrock changes | ~1–2 hours (code + template) |
