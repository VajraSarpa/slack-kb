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
