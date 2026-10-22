import time

import pytest
from conftest import SIGNING_SECRET, sign

from slackkb.slack_verify import SignatureError, verify

TS_HEADER = "X-Slack-Request-Timestamp"
SIG_HEADER = "X-Slack-Signature"


def _check(event, now=None, secret=SIGNING_SECRET):
    now = int(time.time()) if now is None else now
    verify(event["headers"], event["body"], secret, now)


def test_valid_signature_passes(slack_request):
    _check(slack_request())


def test_bad_signature_rejected(slack_request):
    with pytest.raises(SignatureError):
        _check(slack_request(secret="wrong-secret"))


def test_tampered_body_rejected(slack_request):
    event = slack_request()
    event["body"] += "&extra=1"
    with pytest.raises(SignatureError):
        _check(event)


def test_stale_timestamp_rejected(slack_request):
    now = int(time.time())
    with pytest.raises(SignatureError):
        _check(slack_request(ts=now - 301), now=now)


def test_future_timestamp_rejected(slack_request):
    now = int(time.time())
    with pytest.raises(SignatureError):
        _check(slack_request(ts=now + 301), now=now)


def test_timestamp_at_window_edge_passes(slack_request):
    now = int(time.time())
    _check(slack_request(ts=now - 300), now=now)
    _check(slack_request(ts=now + 300), now=now)


@pytest.mark.parametrize("drop", [(TS_HEADER,), (SIG_HEADER,), (TS_HEADER, SIG_HEADER)])
def test_missing_headers_rejected(slack_request, drop):
    with pytest.raises(SignatureError):
        _check(slack_request(drop=drop))


def test_non_integer_timestamp_rejected(slack_request):
    event = slack_request()
    body = event["body"]
    event["headers"][TS_HEADER] = "12.5"
    event["headers"][SIG_HEADER] = sign(body, 12)
    with pytest.raises(SignatureError):
        _check(event, now=12)


def test_lowercase_headers_accepted(slack_request):
    _check(slack_request(lowercase_headers=True))


def test_error_does_not_leak_secret_or_signature(slack_request):
    event = slack_request(secret="wrong-secret")
    with pytest.raises(SignatureError) as excinfo:
        _check(event)
    message = str(excinfo.value)
    assert SIGNING_SECRET not in message
    assert event["headers"][SIG_HEADER] not in message
