import json
import hashlib
import hmac
import time
import boto3
import logging
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Module-level clients — reused across warm invocations
secrets_client = boto3.client('secretsmanager')
lambda_client = boto3.client('lambda')

_secrets_cache = {}


def get_secret(secret_arn):
    if secret_arn not in _secrets_cache:
        response = secrets_client.get_secret_value(SecretId=secret_arn)
        _secrets_cache[secret_arn] = response['SecretString']
    return _secrets_cache[secret_arn]


def handler(event, context):
    # Normalize headers to lowercase for cross-environment compatibility
    headers = {k.lower(): v for k, v in (event.get('headers') or {}).items()}

    # Ignore Slack retries — prevents duplicate incident creation
    if headers.get('x-slack-retry-num') or headers.get('x-slack-retry-reason') == 'http_timeout':
        logger.info('Slack retry detected — ignoring to prevent duplicate processing')
        return {'statusCode': 200, 'body': ''}

    body_str = event.get('body', '')
    body = json.loads(body_str) if isinstance(body_str, str) else body_str

    # Handle Slack URL verification challenge (synchronous — no auth check needed)
    if body.get('type') == 'url_verification':
        logger.info('Handling URL verification challenge')
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'challenge': body['challenge']})
        }

    # Validate Slack signature on all other requests
    signing_secret = get_secret(os.environ['SLACK_SIGNING_SECRET_ARN'])
    timestamp = headers.get('x-slack-request-timestamp', '')
    signature = headers.get('x-slack-signature', '')

    if not validate_signature(signing_secret, timestamp, signature, body_str):
        logger.warning('Invalid Slack signature — rejecting request')
        return {'statusCode': 401, 'body': 'Unauthorized'}

    # Extract the Slack event
    slack_event = body.get('event', {})
    event_type = slack_event.get('type', '')

    # Only handle regular user messages; skip bot messages, edits, deletions
    if event_type != 'message' or slack_event.get('subtype') or slack_event.get('bot_id'):
        return {'statusCode': 200, 'body': ''}

    text = slack_event.get('text', '')
    ts = slack_event.get('ts', '')
    thread_ts = slack_event.get('thread_ts')

    is_thread_reply = bool(thread_ts and thread_ts != ts)
    # Match literal "#log" or Slack's channel-mention format <#CHANNELID|log>
    is_log_message = '#log' in text.lower() or '|log>' in text.lower()

    if is_thread_reply:
        logger.info(f'Routing thread reply (thread_ts={thread_ts}) to conversation Lambda')
        invoke_lambda_async(os.environ['CONVERSATION_FUNCTION_NAME'], body)
    elif is_log_message:
        logger.info(f'Routing #log message (ts={ts}) to routing Lambda')
        invoke_lambda_async(os.environ['ROUTING_FUNCTION_NAME'], body)
    else:
        logger.info('Message is neither a #log nor a thread reply — ignoring')

    # Always return 200 to Slack within the 3-second window
    return {'statusCode': 200, 'body': ''}


def validate_signature(signing_secret, timestamp, signature, body):
    if not timestamp or not signature:
        return False
    try:
        if abs(time.time() - int(timestamp)) > 300:
            logger.warning('Timestamp too old — possible replay attack')
            return False
    except ValueError:
        return False

    sig_basestring = f'v0:{timestamp}:{body}'
    computed = 'v0=' + hmac.new(
        signing_secret.encode('utf-8'),
        sig_basestring.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(computed, signature)


def invoke_lambda_async(function_name, payload):
    try:
        lambda_client.invoke(
            FunctionName=function_name,
            InvocationType='Event',  # Fire-and-forget; failures go to DLQ
            Payload=json.dumps(payload).encode('utf-8')
        )
    except Exception as e:
        logger.error(f'Failed to invoke {function_name}: {e}')
        raise
