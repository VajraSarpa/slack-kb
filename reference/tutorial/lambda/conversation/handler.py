import json
import os
import boto3
import logging
import urllib.request
import urllib.error
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Module-level clients — reused across warm invocations
secrets_client = boto3.client('secretsmanager')
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

_secrets_cache = {}
HANDLER_DIR = os.path.dirname(os.path.abspath(__file__))

MEMO_RELEVANCE_THRESHOLD = 7


def get_secret(secret_arn):
    if secret_arn not in _secrets_cache:
        response = secrets_client.get_secret_value(SecretId=secret_arn)
        _secrets_cache[secret_arn] = response['SecretString']
    return _secrets_cache[secret_arn]


def handler(event, context):
    logger.info('Conversation Lambda invoked')

    slack_event = event.get('event', {})
    thread_ts = slack_event.get('thread_ts')
    channel = slack_event.get('channel', '')
    user_text = slack_event.get('text', '')

    if not thread_ts:
        logger.info('No thread_ts in event — skipping')
        return

    table = dynamodb.Table(os.environ['RECORDS_TABLE'])

    # Look up the record by thread_ts via GSI
    response = table.query(
        IndexName='thread_ts-index',
        KeyConditionExpression=Key('thread_ts').eq(thread_ts)
    )
    items = response.get('Items', [])

    if not items:
        logger.info(f'No record found for thread_ts={thread_ts} — not a tracked thread')
        return

    record = items[0]
    record_id = record['record_id']
    entity_id = record['entity_id']
    logger.info(f'Found record {record_id} for thread_ts={thread_ts}')

    # Fetch the full markdown note from S3
    bucket = os.environ['RECORDS_BUCKET']
    s3_key = f"records/{record_id}.md"
    note_obj = s3_client.get_object(Bucket=bucket, Key=s3_key)
    record_note = note_obj['Body'].read().decode('utf-8')

    # Get entity history — last 10 records for this entity, excluding current
    history_response = table.query(
        IndexName='entity_id-timestamp-index',
        KeyConditionExpression=Key('entity_id').eq(entity_id),
        ScanIndexForward=False,
        Limit=10
    )
    history_items = [h for h in history_response.get('Items', []) if h['record_id'] != record_id]

    entity_history = format_entity_history(history_items[:5])

    # Pre-pass: score memo relevance and detect drift across current record + history
    memo_context = run_memo_pre_pass(record, history_items[:5], user_text)

    # Response pass: build prompt with memo context injected as privileged tier
    prompt = load_conversation_prompt(
        record_note=record_note,
        entity_id=entity_id,
        history_count=len(history_items),
        entity_history=entity_history,
        user_question=user_text,
        memo_context=memo_context
    )

    # Call Claude
    claude_response = ask_claude(prompt)
    logger.info(f'Claude response generated for record {record_id}')

    # Post Claude's response back to the Slack thread
    slack_token = get_secret(os.environ['SLACK_BOT_TOKEN_ARN'])
    post_to_slack(slack_token, channel, claude_response, thread_ts=thread_ts)
    logger.info(f'Conversation response posted for record {record_id}')


def run_memo_pre_pass(current_record, history_items, user_question):
    """
    Two-pass memo layer:
    1. Collect all records (current + history) that have a memo.
    2. Call Haiku with memo_reasoning prompt to score relevance and detect drift.
    3. Return formatted memo context string for injection into the response prompt.
    Returns empty string if no memos exist or none score above threshold.
    """
    import anthropic

    # Collect memo candidates from current record and history
    candidates = []
    all_records = [current_record] + list(history_items)
    for r in all_records:
        if r.get('has_memo') and r.get('memo_text'):
            date = r.get('timestamp', '')[:10]
            candidates.append(
                f"record_id: {r['record_id']}\n"
                f"date: {date}\n"
                f"entity: {r.get('entity_id', 'unknown')}\n"
                f"log_summary: {r.get('description', '')}\n"
                f"memo: {r['memo_text']}"
            )

    if not candidates:
        return ''

    memo_candidates_str = '\n\n---\n\n'.join(candidates)

    with open(os.path.join(HANDLER_DIR, 'memo_reasoning.txt'), 'r') as f:
        template = f.read()

    prompt = template \
        .replace('{user_question}', user_question) \
        .replace('{memo_candidates}', memo_candidates_str)

    api_key = get_secret(os.environ['ANTHROPIC_API_KEY_ARN'])
    client = anthropic.Anthropic(api_key=api_key)

    message = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=512,
        messages=[{'role': 'user', 'content': prompt}]
    )

    try:
        raw = message.content[0].text.strip()
        if raw.startswith('```'):
            lines = raw.split('\n')
            raw = '\n'.join(lines[1:-1] if lines[-1].strip() == '```' else lines[1:])
        result = json.loads(raw)
    except (json.JSONDecodeError, IndexError) as e:
        logger.error(f'Failed to parse memo reasoning response: {e}')
        return ''

    high_scoring = [
        m for m in result.get('scored_memos', [])
        if m.get('score', 0) >= MEMO_RELEVANCE_THRESHOLD
    ]

    if not high_scoring:
        return ''

    # Build a record_id lookup for memo text
    record_lookup = {r['record_id']: r for r in all_records}

    lines = ['## Leadership Memos (relevant to this query)\n']
    for m in high_scoring:
        rec = record_lookup.get(m['record_id'], {})
        memo_text = rec.get('memo_text', '')
        date = rec.get('timestamp', '')[:10]
        lines.append(f"[{date}] {m['record_id']}: {memo_text}")
        lines.append(f"  Insight: {m.get('insight', '')}")
        if m.get('drift_detected') and m.get('drift_note'):
            lines.append(f"  ⚠️ Drift detected: {m['drift_note']}")
        lines.append('')

    return '\n'.join(lines)


def format_entity_history(history_items):
    if not history_items:
        return 'No previous records found for this entity.'
    lines = []
    for h in history_items:
        date = h.get('timestamp', '')[:10]
        severity = h.get('severity', '')
        category = h.get('category', '')
        description = h.get('description', '')[:120]
        lines.append(f"- [{date}] {severity} — {category}: {description}")
    return '\n'.join(lines)


def load_conversation_prompt(record_note, entity_id, history_count, entity_history, user_question, memo_context=''):
    with open(os.path.join(HANDLER_DIR, 'conversation.txt'), 'r') as f:
        template = f.read()
    return template \
        .replace('{record_note}', record_note) \
        .replace('{entity_id}', entity_id) \
        .replace('{history_count}', str(history_count)) \
        .replace('{entity_history}', entity_history) \
        .replace('{memo_context}', memo_context) \
        .replace('{user_question}', user_question)


def ask_claude(prompt):
    import anthropic

    api_key = get_secret(os.environ['ANTHROPIC_API_KEY_ARN'])
    client = anthropic.Anthropic(api_key=api_key)

    message = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=1024,
        messages=[{'role': 'user', 'content': prompt}]
    )
    return message.content[0].text


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
