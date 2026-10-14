#!/usr/bin/env bash
# Slack KB — Manual Deployment Script (POC)
#
# Usage:
#   export SLACK_SIGNING_SECRET_ARN=arn:aws:secretsmanager:...
#   export SLACK_BOT_TOKEN_ARN=arn:aws:secretsmanager:...
#   export ANTHROPIC_API_KEY_ARN=arn:aws:secretsmanager:...
#   export SLACK_ESCALATIONS_CHANNEL_ID=C0XXXXXXX
#   export SNS_ESCALATION_EMAIL=oncall@example.com   # optional
#
#   ./scripts/deploy.sh [stack-name] [region] [deployment-bucket]
#
# Defaults:
#   stack-name:         slack-kb
#   region:             us-east-1
#   deployment-bucket:  skb-deploy-<account-id>

set -euo pipefail

STACK_NAME="${1:-slack-kb}"
AWS_REGION="${2:-us-east-1}"

# Resolve deployment bucket name, falling back to account-scoped default
if [ -n "${3:-}" ]; then
    DEPLOYMENT_BUCKET="$3"
else
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    DEPLOYMENT_BUCKET="skb-deploy-${ACCOUNT_ID}"
fi

# Validate required secret ARNs
: "${SLACK_SIGNING_SECRET_ARN:?Required env var not set}"
: "${SLACK_BOT_TOKEN_ARN:?Required env var not set}"
: "${ANTHROPIC_API_KEY_ARN:?Required env var not set}"
: "${SLACK_ESCALATIONS_CHANNEL_ID:?Required env var not set}"

SNS_ESCALATION_EMAIL="${SNS_ESCALATION_EMAIL:-}"

echo "====================================="
echo " Slack KB — Deploy"
echo "====================================="
echo " Stack:  $STACK_NAME"
echo " Region: $AWS_REGION"
echo " Bucket: $DEPLOYMENT_BUCKET"
echo "====================================="

# Create deployment bucket if it doesn't exist
aws s3 mb "s3://${DEPLOYMENT_BUCKET}" --region "$AWS_REGION" 2>/dev/null || true
aws s3api put-public-access-block \
    --bucket "$DEPLOYMENT_BUCKET" \
    --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" 2>/dev/null || true

# Package and upload each Lambda function
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

for fn in ingestion routing conversation; do
    echo ""
    echo "Packaging $fn Lambda..."
    TMP_DIR=$(mktemp -d)

    # Copy handler code
    cp -r "$PROJECT_ROOT/lambda/$fn/." "$TMP_DIR/"

    # Copy shared assets needed at runtime
    if [ "$fn" = "routing" ]; then
        cp "$PROJECT_ROOT/prompts/structure_incident.txt" "$TMP_DIR/"
        cp "$PROJECT_ROOT/config/escalation_config.json" "$TMP_DIR/"
    fi
    if [ "$fn" = "conversation" ]; then
        cp "$PROJECT_ROOT/prompts/conversation.txt" "$TMP_DIR/"
        cp "$PROJECT_ROOT/prompts/memo_reasoning.txt" "$TMP_DIR/"
    fi

    # Install Python dependencies if any
    if [ -s "$PROJECT_ROOT/lambda/$fn/requirements.txt" ]; then
        pip install -r "$PROJECT_ROOT/lambda/$fn/requirements.txt" \
            -t "$TMP_DIR/" -q --no-cache-dir
    fi

    # Zip and upload
    ZIP_PATH="/tmp/skb-${fn}.zip"
    (cd "$TMP_DIR" && zip -r "$ZIP_PATH" . -q)
    rm -rf "$TMP_DIR"

    aws s3 cp "$ZIP_PATH" "s3://${DEPLOYMENT_BUCKET}/lambda/${fn}.zip"
    echo "  Uploaded lambda/${fn}.zip"
done

# Deploy or update the CloudFormation stack
echo ""
echo "Deploying CloudFormation stack..."
aws cloudformation deploy \
    --template-file "$PROJECT_ROOT/infrastructure/cloudformation/template.yaml" \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION" \
    --parameter-overrides \
        DeploymentBucketName="$DEPLOYMENT_BUCKET" \
        SlackSigningSecretArn="$SLACK_SIGNING_SECRET_ARN" \
        SlackBotTokenArn="$SLACK_BOT_TOKEN_ARN" \
        AnthropicApiKeyArn="$ANTHROPIC_API_KEY_ARN" \
        SlackEscalationsChannelId="$SLACK_ESCALATIONS_CHANNEL_ID" \
        SnsEscalationEmail="$SNS_ESCALATION_EMAIL" \
    --capabilities CAPABILITY_NAMED_IAM \
    --no-fail-on-empty-changeset

# Force Lambda code update (catches code-only changes with no template diff)
echo ""
echo "Updating Lambda function code..."
for fn in ingestion routing conversation; do
    aws lambda update-function-code \
        --function-name "skb-${fn}" \
        --s3-bucket "$DEPLOYMENT_BUCKET" \
        --s3-key "lambda/${fn}.zip" \
        --region "$AWS_REGION" \
        --output text --query 'FunctionName' > /dev/null
    echo "  Updated skb-${fn}"
done

# Print the Slack Events endpoint
echo ""
ENDPOINT=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='SlackEventsEndpoint'].OutputValue" \
    --output text)

echo "====================================="
echo " Deploy complete."
echo ""
echo " Slack Events URL:"
echo " $ENDPOINT"
echo ""
echo " Configure this URL in your Slack App:"
echo " App settings → Event Subscriptions → Request URL"
echo "====================================="
