import hashlib
import hmac
import json
import time
import urllib.parse
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

SIGNING_SECRET = "test-signing-secret"
NOTES_TABLE = "slackkb-notes-test"
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


@pytest.fixture
def notes_table():
    with mock_aws():
        table = boto3.resource("dynamodb").create_table(
            TableName=NOTES_TABLE,
            KeySchema=[{"AttributeName": "note_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "note_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield table


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
