"""Slack Web API client. The only module that calls the Slack Web API.

The transport is injected: a callable (url, headers, json_body) -> dict. Tests pass a
fake; `urllib_transport` is the default for real use. The bot token is never logged
and never appears in exception messages or reprs.
"""

import json
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

from pydantic import SecretStr

VIEWS_OPEN_URL = "https://slack.com/api/views.open"
DEFAULT_TIMEOUT_SECONDS = 2.5

Transport = Callable[[str, Mapping[str, str], Mapping[str, Any]], dict]


class SlackApiError(Exception):
    """A Slack Web API call failed. Messages never carry the token."""


def urllib_transport(url: str, headers: Mapping[str, str], json_body: Mapping[str, Any]) -> dict:
    """POST json_body as JSON and return the decoded JSON reply."""
    if not url.startswith("https://"):
        raise ValueError("only https URLs are allowed")
    request = urllib.request.Request(  # noqa: S310
        url,
        data=json.dumps(json_body).encode(),
        headers={"Content-Type": "application/json; charset=utf-8", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as resp:  # noqa: S310
        return json.loads(resp.read().decode())


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
