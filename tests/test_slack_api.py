import pytest
from pydantic import SecretStr

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
