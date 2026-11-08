"""Slack Web API client. The only module that calls the Slack Web API.

The transport is injected: a callable (url, headers, json_body) -> dict. Tests pass a
fake; `urllib_transport` is the default for real use. The bot token is never logged
and never appears in exception messages or reprs.
"""

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

from pydantic import SecretStr

VIEWS_OPEN_URL = "https://slack.com/api/views.open"
CHAT_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"
CHAT_POST_EPHEMERAL_URL = "https://slack.com/api/chat.postEphemeral"
DEFAULT_TIMEOUT_SECONDS = 2.5

Transport = Callable[[str, Mapping[str, str], Mapping[str, Any]], dict]


class SlackApiError(Exception):
    """A Slack Web API call failed. Messages never carry the token."""


def make_urllib_transport(timeout: float) -> Transport:
    """A transport that POSTs json_body as JSON with the given timeout in seconds."""

    def transport(url: str, headers: Mapping[str, str], json_body: Mapping[str, Any]) -> dict:
        if not url.startswith("https://"):
            raise ValueError("only https URLs are allowed")
        request = urllib.request.Request(  # noqa: S310
            url,
            data=json.dumps(json_body).encode(),
            headers={"Content-Type": "application/json; charset=utf-8", **headers},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310
            return json.loads(resp.read().decode())

    return transport


urllib_transport: Transport = make_urllib_transport(DEFAULT_TIMEOUT_SECONDS)

RESPONSE_URL_TIMEOUT_SECONDS = 10.0

ResponseUrlTransport = Callable[[str, Mapping[str, Any]], int]


class ResponseUrlError(SlackApiError):
    """A response_url call failed. status is the HTTP status, or None if no reply came.

    Messages never carry the URL: it is a bearer secret.
    """

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def make_response_url_transport(timeout: float) -> ResponseUrlTransport:
    """A transport that POSTs json_body to a response_url and returns the HTTP status.

    No Authorization header is sent. An HTTP error status is returned, not raised; the
    reply body is not read.
    """

    def transport(url: str, json_body: Mapping[str, Any]) -> int:
        if not url.startswith("https://"):
            raise ValueError("only https URLs are allowed")
        request = urllib.request.Request(  # noqa: S310
            url,
            data=json.dumps(json_body).encode(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310
                status = getattr(resp, "status", None)
                return status if isinstance(status, int) else resp.getcode()
        except urllib.error.HTTPError as exc:
            return exc.code

    return transport


response_url_transport: ResponseUrlTransport = make_response_url_transport(
    RESPONSE_URL_TIMEOUT_SECONDS
)


def post_response_url(
    url: str, text: str, transport: ResponseUrlTransport = response_url_transport
) -> None:
    """Post an ephemeral message to a slash command's response_url.

    Returns None on a 2xx status; raises ResponseUrlError otherwise.
    """
    try:
        status = transport(url, {"response_type": "ephemeral", "text": text})
    except Exception as exc:
        raise ResponseUrlError(f"transport failed: {type(exc).__name__}") from None
    if not 200 <= status <= 299:
        raise ResponseUrlError(f"response_url returned status {status}", status)


class SlackClient:
    def __init__(self, token: SecretStr, transport: Transport = urllib_transport) -> None:
        self._token = token
        self._transport = transport

    def __repr__(self) -> str:
        return "SlackClient(token=**********)"

    def _call(self, url: str, body: Mapping[str, Any]) -> None:
        headers = {"Authorization": f"Bearer {self._token.get_secret_value()}"}
        try:
            reply = self._transport(url, headers, body)
        except Exception as exc:
            raise SlackApiError(f"transport failed: {type(exc).__name__}") from None
        if not isinstance(reply, Mapping) or reply.get("ok") is not True:
            error = reply.get("error") if isinstance(reply, Mapping) else None
            raise SlackApiError(f"slack error: {error if isinstance(error, str) else 'unknown'}")

    def views_open(self, trigger_id: str, view: Mapping[str, Any]) -> None:
        """Open a modal. Raises SlackApiError if Slack rejects it or the call fails."""
        self._call(VIEWS_OPEN_URL, {"trigger_id": trigger_id, "view": view})

    def chat_post_message(self, channel: str, thread_ts: str, text: str) -> None:
        """Post text in a thread. Raises SlackApiError if Slack rejects it or the call fails."""
        self._call(
            CHAT_POST_MESSAGE_URL, {"channel": channel, "thread_ts": thread_ts, "text": text}
        )

    def chat_post_ephemeral(self, channel: str, user: str, thread_ts: str, text: str) -> None:
        """Post text in a thread, visible only to user. Raises SlackApiError on failure."""
        self._call(
            CHAT_POST_EPHEMERAL_URL,
            {"channel": channel, "user": user, "thread_ts": thread_ts, "text": text},
        )
