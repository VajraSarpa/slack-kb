import json
import os
import uuid
import boto3
import logging
import urllib.request
import urllib.error
from datetime import datetime, timezone

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Module-level clients — reused across warm invocations
secrets_client = boto3.client('secretsmanager')
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
sns_client = boto3.client('sns')

_secrets_cache = {}
HANDLER_DIR = os.path.dirname(os.path.abspath(__file__))

SEVERITY_EMOJI = {
    'Low': ':white_circle:',
    'Medium': ':large_yellow_circle:',
    'High': ':large_orange_circle:',
    'Critical': ':red_circle:'
}


def get_secret(secret_arn):
    if secret_arn not in _secrets_cache:
        response = secrets_client.get_secret_value(SecretId=secret_arn)
        _secrets_cache[secret_arn] = response['SecretString']
    return _secrets_cache[secret_arn]


def load_config():
    with open(os.path.join(HANDLER_DIR, 'escalation_config.json'), 'r') as f:
        return json.load(f)


def parse_memo(text):
    """Split message on 'memo:' delimiter. Returns (log_text, memo_text or None)."""
    lower = text.lower()
    idx = lower.find('memo:')
    if idx == -1:
        return text.strip(), None
    log_text = text[:idx].strip()
    memo_text = text[idx + 5:].strip()
    return log_text, memo_text if memo_text else None


def handler(event, context):
    logger.info('Routing Lambda invoked')

    slack_event = event.get('event', {})
    raw_message = slack_event.get('text', '')
    channel = slack_event.get('channel', '')
    thread_ts = slack_event.get('ts', '')  # Original message ts becomes the thread_ts anchor
    user = slack_event.get('user', 'unknown')
    timestamp = datetime.now(timezone.utc).isoformat()

    config = load_config()
    entity_context = config['poc_entity_defaults']['context']

    # Parse memo delimiter — log_text is the operational content, memo_text is leadership context
    log_text, memo_text = parse_memo(raw_message)
    has_memo = memo_text is not None
    if has_memo:
        logger.info(f'Memo detected in message — memo_text length={len(memo_text)}')

    # Call Claude to extract structured record fields (structured from log_text only)
    structured = structure_record(log_text or raw_message, entity_context, user)
    extracted_entity = structured.get('entity')
    entity_id = extracted_entity if extracted_entity else 'unknown'
    logger.info(f"Claude structured record: entity={entity_id}, severity={structured['severity']}, category={structured['category']}")

    # Generate record ID
    record_id = f"REC-{uuid.uuid4().hex[:8].upper()}"

    # Build markdown note and write to S3
    note_content = build_markdown_note(
        record_id, timestamp, entity_id, entity_context,
        user, structured, raw_message, thread_ts, memo_text
    )
    bucket = os.environ['RECORDS_BUCKET']
    s3_key = f"records/{record_id}.md"
    s3_client.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=note_content.encode('utf-8'),
        ContentType='text/markdown'
    )
    note_url = f"s3://{bucket}/{s3_key}"
    logger.info(f"Note written to {note_url}")

    # Write metadata to DynamoDB
    table = dynamodb.Table(os.environ['RECORDS_TABLE'])
    item = {
        'record_id': record_id,
        'timestamp': timestamp,
        'entity_id': entity_id,
        'context': entity_context,
        'severity': structured['severity'],
        'category': structured['category'],
        'description': structured['description'],
        'tags': structured.get('tags', []),
        'reported_by': user,
        'thread_ts': thread_ts,
        'channel': channel,
        'note_url': note_url,
        'status': 'Open',
        'raw_message': raw_message,
        'has_memo': has_memo
    }
    if has_memo:
        item['memo_text'] = memo_text
        item['memo_author'] = user
    table.put_item(Item=item)
    logger.info(f"Metadata written to DynamoDB: {record_id}")

    # Post structured summary to the original Slack thread
    slack_token = get_secret(os.environ['SLACK_BOT_TOKEN_ARN'])
    summary = format_slack_summary(record_id, structured, entity_id, entity_context, has_memo)
    post_to_slack(slack_token, channel, summary, thread_ts=thread_ts)

    # Escalation routing
    severity = structured['severity']
    escalation_config = config['escalation_thresholds']

    if severity in escalation_config['slack_escalations']:
        escalations_channel = os.environ['ESCALATIONS_CHANNEL_ID']
        escalation_msg = format_escalation_message(record_id, structured, entity_id, entity_context, channel, thread_ts)
        post_to_slack(slack_token, escalations_channel, escalation_msg)
        logger.info(f"Escalation posted to {escalations_channel}")

    if severity in escalation_config['sns_notification']:
        sns_client.publish(
            TopicArn=os.environ['ESCALATION_TOPIC_ARN'],
            Subject=f"[CRITICAL] Slack KB Alert: {record_id} — {entity_id}",
            Message=format_sns_message(record_id, structured, entity_id, entity_context)
        )
        logger.info(f"SNS notification sent for {record_id}")

    logger.info(f"Record {record_id} fully processed")


def structure_record(raw_message, context, reported_by):
    import anthropic

    with open(os.path.join(HANDLER_DIR, 'structure_incident.txt'), 'r') as f:
        prompt_template = f.read()

    prompt = prompt_template \
        .replace('{raw_message}', raw_message) \
        .replace('{context}', context) \
        .replace('{reported_by}', reported_by)

    api_key = get_secret(os.environ['ANTHROPIC_API_KEY_ARN'])
    client = anthropic.Anthropic(api_key=api_key)

    message = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=512,
        messages=[{'role': 'user', 'content': prompt}]
    )

    return extract_json(message.content[0].text)


def extract_json(text):
    """Parse JSON from Claude's response, stripping markdown fencing if present."""
    text = text.strip()
    if text.startswith('```'):
        lines = text.split('\n')
        start = 1
        end = len(lines)
        for i in range(len(lines) - 1, 0, -1):
            if lines[i].strip() == '```':
                end = i
                break
        text = '\n'.join(lines[start:end])
    logger.info(f"Claude raw response: {text}")
    return json.loads(text.strip())


def build_markdown_note(record_id, timestamp, entity_id, context, reported_by, structured, raw_message, thread_ts, memo_text=None):
    tags_str = ', '.join(structured.get('tags', []))
    memo_section = f"\n## Memo\n\n> {memo_text}\n" if memo_text else ''
    return f"""# Record: {record_id}

**Timestamp:** {timestamp}
**Entity:** {entity_id} — {context}
**Reported by:** {reported_by}
**Severity:** {structured['severity']}
**Category:** {structured['category']}
**Status:** Open
**Tags:** {tags_str}
**Slack Thread:** {thread_ts}
{f'**Has Memo:** Yes' if memo_text else ''}

## Description

{structured['description']}
{memo_section}
## Raw Message

> {raw_message}

---
*Generated by Slack KB*
"""


def format_slack_summary(record_id, structured, entity_id, context, has_memo=False):
    severity = structured['severity']
    emoji = SEVERITY_EMOJI.get(severity, ':white_circle:')
    tags = ' '.join(f'`{t}`' for t in structured.get('tags', []))
    memo_line = '\n:pushpin: *Memo attached* — leadership context stored.\n' if has_memo else ''
    return (
        f":memo: *Record logged* — `{record_id}`\n\n"
        f"*Severity:* {emoji} {severity}\n"
        f"*Category:* {structured['category']}\n"
        f"*Entity:* {entity_id} — {context}\n\n"
        f"*Summary:* {structured['description']}\n\n"
        f"*Tags:* {tags}\n"
        f"{memo_line}\n"
        f"_Reply in this thread to ask Claude about this record._"
    )


def format_escalation_message(record_id, structured, entity_id, context, channel, thread_ts):
    severity = structured['severity']
    emoji = SEVERITY_EMOJI.get(severity, ':white_circle:')
    return (
        f"{emoji} *ESCALATION — {severity}* — `{record_id}`\n\n"
        f"*Entity:* {entity_id} — {context}\n"
        f"*Category:* {structured['category']}\n"
        f"*Summary:* {structured['description']}\n\n"
        f"_Channel:_ <#{channel}> | Thread: `{thread_ts}`"
    )


def format_sns_message(record_id, structured, entity_id, context):
    return (
        f"CRITICAL ALERT\n\n"
        f"Record ID: {record_id}\n"
        f"Entity: {entity_id}\n"
        f"Category: {structured['category']}\n"
        f"Summary: {structured['description']}\n"
        f"Tags: {', '.join(structured.get('tags', []))}\n"
    )


def post_to_slack(token, channel, text, thread_ts=None):
    url = 'https://slack.com/api/chat.postMessage'
    payload = {'channel': channel, 'text': text}
    if thread_ts:
        payload['thread_ts'] = thread_ts

    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode('utf-8'))
            if not result.get('ok'):
                logger.error(f"Slack API error: {result.get('error')}")
            return result
    except urllib.error.URLError as e:
        logger.error(f"Failed to post to Slack: {e}")
        raise
