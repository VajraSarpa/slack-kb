import urllib.error

import pytest
from pydantic import SecretStr

from slackkb import slack_api
from slackkb.slack_api import SlackApiError, SlackClient

TOKEN = "xoxb-secret-token-value"


class FakeTransport:
    def __init__(self, reply=None, exc=None):
        self.calls = []
        self.reply = {"ok": True} if reply is None else reply
        self.exc = exc

    def __call__(self, url, headers, json_body):
        self.calls.append((url, dict(headers), dict(json_body)))
        if self.exc is not None:
            raise self.exc
        return self.reply


def _client(transport):
    return SlackClient(SecretStr(TOKEN), transport)


def _post(client, method):
    if method == "message":
        client.chat_post_message("C1", "1700000000.000100", "hello")
    else:
        client.chat_post_ephemeral("C1", "U1", "1700000000.000100", "hello")


def test_chat_post_message_request():
    transport = FakeTransport()
    _client(transport).chat_post_message("C1", "1700000000.000100", "hello")
    assert transport.calls == [
        (
            "https://slack.com/api/chat.postMessage",
            {"Authorization": f"Bearer {TOKEN}"},
            {"channel": "C1", "thread_ts": "1700000000.000100", "text": "hello"},
        )
    ]


def test_chat_post_ephemeral_request():
    transport = FakeTransport()
    _client(transport).chat_post_ephemeral("C1", "U1", "1700000000.000100", "hello")
    assert transport.calls == [
        (
            "https://slack.com/api/chat.postEphemeral",
            {"Authorization": f"Bearer {TOKEN}"},
            {
                "channel": "C1",
                "user": "U1",
                "thread_ts": "1700000000.000100",
                "text": "hello",
            },
        )
    ]


@pytest.mark.parametrize("method", ["message", "ephemeral"])
@pytest.mark.parametrize(
    "transport",
    [
        FakeTransport(reply={"ok": False, "error": "channel_not_found"}),
        FakeTransport(exc=RuntimeError(f"boom {TOKEN}")),
    ],
    ids=["ok-false", "transport-exception"],
)
def test_chat_errors_raise_without_token(method, transport):
    with pytest.raises(SlackApiError) as info:
        _post(_client(transport), method)
    assert TOKEN not in str(info.value)
    assert TOKEN not in repr(info.value)
    assert TOKEN not in repr(_client(transport))


class _FakeResponse:
    def read(self):
        return b'{"ok": true}'

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_urlopen(monkeypatch):
    seen = []

    def fake(request, timeout=None):
        seen.append((request, timeout))
        return _FakeResponse()

    monkeypatch.setattr("slackkb.slack_api.urllib.request.urlopen", fake)
    return seen


def test_make_transport_passes_timeout(monkeypatch):
    seen = _fake_urlopen(monkeypatch)
    reply = slack_api.make_urllib_transport(7.25)("https://slack.com/api/x", {}, {})
    assert reply == {"ok": True}
    assert [timeout for _, timeout in seen] == [7.25]


def test_default_transport_timeout_is_2_5(monkeypatch):
    seen = _fake_urlopen(monkeypatch)
    slack_api.urllib_transport("https://slack.com/api/x", {}, {})
    SlackClient(SecretStr(TOKEN)).chat_post_message("C1", "1.1", "hi")
    assert [timeout for _, timeout in seen] == [2.5, 2.5]


def test_make_transport_request_shape(monkeypatch):
    seen = _fake_urlopen(monkeypatch)
    slack_api.make_urllib_transport(3.0)(
        "https://slack.com/api/chat.postMessage",
        {"Authorization": "Bearer abc"},
        {"channel": "C1", "text": "hi"},
    )
    request, _ = seen[0]
    assert request.full_url == "https://slack.com/api/chat.postMessage"
    assert request.get_method() == "POST"
    assert request.data == b'{"channel": "C1", "text": "hi"}'
    assert request.get_header("Content-type") == "application/json; charset=utf-8"
    assert request.get_header("Authorization") == "Bearer abc"


def test_make_transport_rejects_non_https(monkeypatch):
    seen = _fake_urlopen(monkeypatch)
    with pytest.raises(ValueError):
        slack_api.make_urllib_transport(3.0)("http://slack.com/api/x", {}, {})
    assert seen == []


RESPONSE_URL = "https://hooks.slack.invalid/commands/T000TEST/1/abc"


class _StatusResponse(_FakeResponse):
    def __init__(self, status=200, body=b"ok"):
        self.status = status
        self._body = body

    def read(self):
        return self._body


def _fake_response_urlopen(monkeypatch, status=200, body=b"ok", exc=None, http_code=None):
    seen = []

    def fake(request, timeout=None):
        seen.append((request, timeout))
        if http_code is not None:
            raise urllib.error.HTTPError(request.full_url, http_code, "msg", {}, None)
        if exc is not None:
            raise exc
        return _StatusResponse(status, body)

    monkeypatch.setattr("slackkb.slack_api.urllib.request.urlopen", fake)
    return seen


def test_post_response_url_request_shape(monkeypatch):
    seen = _fake_response_urlopen(monkeypatch, status=200)
    assert slack_api.post_response_url(RESPONSE_URL, "hello") is None
    assert len(seen) == 1
    request, timeout = seen[0]
    assert request.full_url == RESPONSE_URL
    assert request.get_method() == "POST"
    assert request.data == b'{"response_type": "ephemeral", "text": "hello"}'
    assert request.get_header("Content-type") == "application/json; charset=utf-8"
    assert not request.has_header("Authorization")
    assert timeout == 10.0
    assert slack_api.RESPONSE_URL_TIMEOUT_SECONDS == 10.0


def test_post_response_url_status_handling(monkeypatch):
    _fake_response_urlopen(monkeypatch, status=204)
    assert slack_api.post_response_url(RESPONSE_URL, "t") is None
    for code in (404, 500):
        _fake_response_urlopen(monkeypatch, http_code=code)
        with pytest.raises(slack_api.ResponseUrlError) as info:
            slack_api.post_response_url(RESPONSE_URL, "t")
        assert info.value.status == code
        assert isinstance(info.value, SlackApiError)
        assert RESPONSE_URL not in str(info.value)
    _fake_response_urlopen(monkeypatch, exc=OSError(f"boom {RESPONSE_URL}"))
    with pytest.raises(slack_api.ResponseUrlError) as info:
        slack_api.post_response_url(RESPONSE_URL, "t")
    assert info.value.status is None
    assert RESPONSE_URL not in str(info.value)
    assert RESPONSE_URL not in repr(info.value)


def test_post_response_url_non_2xx_returned_status_raises():
    for status, ok in ((199, False), (200, True), (299, True), (300, False)):
        transport = lambda url, body, status=status: status  # noqa: E731
        if ok:
            assert slack_api.post_response_url(RESPONSE_URL, "t", transport) is None
        else:
            with pytest.raises(slack_api.ResponseUrlError) as info:
                slack_api.post_response_url(RESPONSE_URL, "t", transport)
            assert info.value.status == status


def test_response_url_transport_ignores_reply_body(monkeypatch):
    _fake_response_urlopen(monkeypatch, status=200, body=b"ok")
    assert slack_api.response_url_transport(RESPONSE_URL, {"a": 1}) == 200
    _fake_response_urlopen(monkeypatch, status=200, body=b"\xff not json")
    assert slack_api.response_url_transport(RESPONSE_URL, {"a": 1}) == 200
    _fake_response_urlopen(monkeypatch, http_code=410)
    assert slack_api.response_url_transport(RESPONSE_URL, {"a": 1}) == 410


def test_response_url_transport_passes_timeout(monkeypatch):
    seen = _fake_response_urlopen(monkeypatch, status=200)
    assert slack_api.make_response_url_transport(3.5)(RESPONSE_URL, {"a": 1}) == 200
    assert len(seen) == 1
    assert seen[0][1] == 3.5


def test_response_url_transport_rejects_non_https(monkeypatch):
    seen = _fake_response_urlopen(monkeypatch)
    with pytest.raises(ValueError):
        slack_api.make_response_url_transport(10.0)("http://hooks.slack.invalid/x", {})
    assert seen == []
