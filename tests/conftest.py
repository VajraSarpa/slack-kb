import hashlib
import hmac
import json
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

SIGNING_SECRET = "test-signing-secret"
BOT_TOKEN = "xoxb-test-token"
NOTES_TABLE = "slackkb-notes-test"
CAPTURE_QUEUE = "slackkb-capture-test"
CAPTURE_DLQ = "slackkb-capture-dlq-test"
NOTES_BUCKET = "slackkb-notes-test"
VECTORS_TABLE = "slackkb-note-vectors-test"
EMBED_MODEL_ID = "amazon.titan-embed-text-v2:0"
EVENTS_TABLE = "slackkb-events-test"
QUESTION_QUEUE = "slackkb-question-test"
QUESTION_DLQ = "slackkb-question-dlq-test"
QUESTION_QUEUE_URL = f"https://sqs.us-east-1.amazonaws.com/123456789012/{QUESTION_QUEUE}"
MAX_RECEIVES = 3
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def offline_env(monkeypatch):
    """Fake AWS creds and app settings; never touch a real profile."""
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("SLACKKB_SIGNING_SECRET", SIGNING_SECRET)
    monkeypatch.setenv("SLACKKB_NOTES_TABLE", NOTES_TABLE)
    monkeypatch.setenv("SLACKKB_SLACK_BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setenv("SLACKKB_NOTES_BUCKET", NOTES_BUCKET)
    monkeypatch.setenv("SLACKKB_QA_MODEL_ID", "us.anthropic.claude-haiku-test")
    monkeypatch.setenv("SLACKKB_VECTORS_TABLE", VECTORS_TABLE)
    monkeypatch.setenv("SLACKKB_EMBED_MODEL_ID", EMBED_MODEL_ID)
    monkeypatch.setenv("SLACKKB_EVENTS_TABLE", EVENTS_TABLE)
    monkeypatch.setenv("SLACKKB_QUESTION_QUEUE_URL", QUESTION_QUEUE_URL)


@pytest.fixture
def aws():
    """One moto context shared by every AWS fixture in a test."""
    with mock_aws():
        yield


@pytest.fixture
def notes_table(aws):
    return boto3.resource("dynamodb").create_table(
        TableName=NOTES_TABLE,
        KeySchema=[{"AttributeName": "note_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "note_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )


@pytest.fixture
def notes_bucket(aws):
    """Notes bucket for OKF objects (D-014); name is in offline_env."""
    return boto3.resource("s3").create_bucket(Bucket=NOTES_BUCKET)


@pytest.fixture
def vectors_table(aws):
    """note_vectors table (D-008): PK team_id, SK note_id; name is in offline_env."""
    return boto3.resource("dynamodb").create_table(
        TableName=VECTORS_TABLE,
        KeySchema=[
            {"AttributeName": "team_id", "KeyType": "HASH"},
            {"AttributeName": "note_id", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "team_id", "AttributeType": "S"},
            {"AttributeName": "note_id", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


@pytest.fixture
def events_table(aws):
    """Events API dedup table (D-011): PK event_id, TTL on expires_at."""
    table = boto3.resource("dynamodb").create_table(
        TableName=EVENTS_TABLE,
        KeySchema=[{"AttributeName": "event_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "event_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    boto3.client("dynamodb").update_time_to_live(
        TableName=EVENTS_TABLE,
        TimeToLiveSpecification={"Enabled": True, "AttributeName": "expires_at"},
    )
    return table


@dataclass
class Queues:
    url: str
    dlq_url: str


@pytest.fixture
def capture_queue(aws, monkeypatch):
    """Capture queue with a redrive DLQ (D-004); URL exported to settings."""
    sqs = boto3.client("sqs")
    dlq_url = sqs.create_queue(QueueName=CAPTURE_DLQ)["QueueUrl"]
    dlq_arn = sqs.get_queue_attributes(
        QueueUrl=dlq_url, AttributeNames=["QueueArn"]
    )["Attributes"]["QueueArn"]
    redrive = {"deadLetterTargetArn": dlq_arn, "maxReceiveCount": str(MAX_RECEIVES)}
    url = sqs.create_queue(
        QueueName=CAPTURE_QUEUE,
        Attributes={"RedrivePolicy": json.dumps(redrive)},
    )["QueueUrl"]
    monkeypatch.setenv("SLACKKB_CAPTURE_QUEUE_URL", url)
    return Queues(url=url, dlq_url=dlq_url)


@pytest.fixture
def question_queue(aws):
    """Question queue with its own redrive DLQ (D-017); URL is in offline_env."""
    sqs = boto3.client("sqs")
    dlq_url = sqs.create_queue(QueueName=QUESTION_DLQ)["QueueUrl"]
    dlq_arn = sqs.get_queue_attributes(
        QueueUrl=dlq_url, AttributeNames=["QueueArn"]
    )["Attributes"]["QueueArn"]
    redrive = {"deadLetterTargetArn": dlq_arn, "maxReceiveCount": str(MAX_RECEIVES)}
    url = sqs.create_queue(
        QueueName=QUESTION_QUEUE,
        Attributes={"RedrivePolicy": json.dumps(redrive)},
    )["QueueUrl"]
    assert url == QUESTION_QUEUE_URL
    return Queues(url=url, dlq_url=dlq_url)


def sign(body: str, ts: int, secret: str = SIGNING_SECRET) -> str:
    base = f"v0:{ts}:{body}".encode()
    return "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()


@pytest.fixture
def slack_request():
    """Build an API Gateway proxy event for a signed /bnote request."""

    def make(*, text=None, ts=None, secret=SIGNING_SECRET, retry=None,
             lowercase_headers=False, drop=()):
        fields = json.loads((FIXTURES / "slash_bnote.json").read_text())
        if text is not None:
            fields["text"] = text
        body = urllib.parse.urlencode(fields)
        ts = int(time.time()) if ts is None else ts
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Slack-Request-Timestamp": str(ts),
            "X-Slack-Signature": sign(body, ts, secret),
        }
        if retry is not None:
            headers["X-Slack-Retry-Num"] = str(retry)
        for name in drop:
            headers.pop(name, None)
        if lowercase_headers:
            headers = {k.lower(): v for k, v in headers.items()}
        return {"headers": headers, "body": body, "isBase64Encoded": False}

    return make


@pytest.fixture
def slack_interaction():
    """Build a signed interactivity event (block_actions or view_submission).

    Slack posts these form-encoded as payload=<json>. `severity` and
    `note_id` override the fixture's view state / button value.
    """

    def make(kind, *, severity=None, note_id=None, ts=None,
             secret=SIGNING_SECRET):
        payload = json.loads((FIXTURES / f"{kind}.json").read_text())
        if kind == "block_actions" and note_id is not None:
            payload["actions"][0]["value"] = note_id
        if kind == "view_submission":
            if note_id is not None:
                payload["view"]["private_metadata"] = note_id
            if severity is not None:
                select = payload["view"]["state"]["values"]["severity"]
                select["severity_select"]["selected_option"]["value"] = severity
        body = urllib.parse.urlencode({"payload": json.dumps(payload)})
        ts = int(time.time()) if ts is None else ts
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Slack-Request-Timestamp": str(ts),
            "X-Slack-Signature": sign(body, ts, secret),
        }
        return {"headers": headers, "body": body, "isBase64Encoded": False}

    return make


_KEEP = object()


@pytest.fixture
def slack_event():
    """Build a signed Events API request (JSON body) from a fixture.

    kind is "app_mention" (an event_callback) or "url_verification".
    text/event_id/bot_id/subtype/thread_ts override the app_mention event;
    thread_ts=None removes it (a top-level mention). retry sets
    X-Slack-Retry-Num. body= sends that raw string instead (still signed).
    """

    def make(kind="app_mention", *, text=None, event_id=None, bot_id=None,
             subtype=None, thread_ts=_KEEP, retry=None, ts=None,
             secret=SIGNING_SECRET, body=None):
        payload = json.loads((FIXTURES / f"{kind}.json").read_text())
        if kind == "app_mention":
            event = payload["event"]
            if text is not None:
                event["text"] = text
            if event_id is not None:
                payload["event_id"] = event_id
            if bot_id is not None:
                event["bot_id"] = bot_id
            if subtype is not None:
                event["subtype"] = subtype
            if thread_ts is None:
                event.pop("thread_ts", None)
            elif thread_ts is not _KEEP:
                event["thread_ts"] = thread_ts
        raw = json.dumps(payload) if body is None else body
        ts = int(time.time()) if ts is None else ts
        headers = {
            "Content-Type": "application/json",
            "X-Slack-Request-Timestamp": str(ts),
            "X-Slack-Signature": sign(raw, ts, secret),
        }
        if retry is not None:
            headers["X-Slack-Retry-Num"] = str(retry)
            headers["X-Slack-Retry-Reason"] = "http_timeout"
        return {"headers": headers, "body": raw, "isBase64Encoded": False}

    return make
