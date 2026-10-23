"""Severity modal: block_actions (open the modal) and view_submission (set severity).

D-013. All DynamoDB access goes through store.py and all Slack Web API calls through
slack_api.py. Never logs note text, secrets, or Slack callback URLs.
"""

import base64
import binascii
import json
import logging
import urllib.parse
from collections.abc import Mapping
from typing import Any

from slackkb.config import Settings
from slackkb.models import Severity
from slackkb.slack_api import SlackApiError, SlackClient
from slackkb.slack_verify import SignatureError, verify
from slackkb.store import NoteNotFoundError, get_note, set_severity

logger = logging.getLogger(__name__)

ACTION_ID = "set_severity"
CALLBACK_ID = "severity_modal"
BLOCK_ID = "severity"
SELECT_ACTION_ID = "severity_select"
NOT_FOUND_TEXT = "That note could not be found."
BAD_SEVERITY_TEXT = "Choose one of: " + ", ".join(s.value for s in Severity) + "."


def _response(status: int, body: str, content_type: str = "text/plain") -> dict[str, Any]:
    return {"statusCode": status, "headers": {"Content-Type": content_type}, "body": body}


def _empty() -> dict[str, Any]:
    return _response(200, "")


def _errors(message: str) -> dict[str, Any]:
    body = json.dumps({"response_action": "errors", "errors": {BLOCK_ID: message}})
    return _response(200, body, "application/json")


def _raw_body(event: Mapping[str, Any]) -> str:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        return base64.b64decode(body, validate=True).decode()
    return body


def _get(obj: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(obj, Mapping):
            return None
        obj = obj.get(key)
    return obj


def _view(note_id: str, current: Severity) -> dict[str, Any]:
    options = [
        {"text": {"type": "plain_text", "text": s.value}, "value": s.value} for s in Severity
    ]
    initial = {"text": {"type": "plain_text", "text": current.value}, "value": current.value}
    return {
        "type": "modal",
        "callback_id": CALLBACK_ID,
        "private_metadata": note_id,
        "title": {"type": "plain_text", "text": "Set severity"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": BLOCK_ID,
                "label": {"type": "plain_text", "text": "Severity"},
                "element": {
                    "type": "static_select",
                    "action_id": SELECT_ACTION_ID,
                    "options": options,
                    "initial_option": initial,
                },
            }
        ],
    }


def _block_actions(payload: Mapping[str, Any], table: Any, slack: SlackClient) -> dict[str, Any]:
    actions = payload.get("actions")
    action = actions[0] if isinstance(actions, list) and actions else None
    if _get(action, "action_id") != ACTION_ID:
        return _empty()
    note_id = _get(action, "value")
    trigger_id = payload.get("trigger_id")
    team_id = _get(payload, "team", "id")
    if not isinstance(note_id, str) or not isinstance(trigger_id, str) or not note_id:
        return _empty()
    note = get_note(table, note_id)
    if note is None or team_id is None or note.team_id != team_id:
        return _empty()
    try:
        slack.views_open(trigger_id, _view(note.note_id, note.severity))
    except SlackApiError as exc:
        logger.warning("views.open failed (%s), note_id=%s", exc, note.note_id)
    return _empty()


def _view_submission(payload: Mapping[str, Any], table: Any) -> dict[str, Any]:
    if _get(payload, "view", "callback_id") != CALLBACK_ID:
        return _response(400, "bad request")
    note_id = _get(payload, "view", "private_metadata")
    value = _get(
        payload, "view", "state", "values", BLOCK_ID, SELECT_ACTION_ID, "selected_option", "value"
    )
    try:
        severity = Severity(value)
    except ValueError:
        return _errors(BAD_SEVERITY_TEXT)
    if not isinstance(note_id, str) or not note_id:
        return _errors(NOT_FOUND_TEXT)
    note = get_note(table, note_id)
    team_id = _get(payload, "team", "id")
    if note is None or team_id is None or note.team_id != team_id:
        return _errors(NOT_FOUND_TEXT)
    try:
        set_severity(table, note_id, severity)
    except NoteNotFoundError:
        return _errors(NOT_FOUND_TEXT)
    return _empty()


def handle(
    event: Mapping[str, Any], *, table: Any, slack: SlackClient, settings: Settings, now: int
) -> dict:
    """Handle one API Gateway proxy event for Slack interactivity and return the response."""
    headers = event.get("headers") or {}
    try:
        body = _raw_body(event)
        verify(headers, body, settings.signing_secret.get_secret_value(), now)
    except (SignatureError, binascii.Error, UnicodeDecodeError):
        return _response(401, "unauthorized")

    fields = dict(urllib.parse.parse_qsl(body, keep_blank_values=True))
    try:
        payload = json.loads(fields["payload"])
    except (KeyError, ValueError):
        return _response(400, "bad request")
    if not isinstance(payload, dict):
        return _response(400, "bad request")

    kind = payload.get("type")
    if kind == "block_actions":
        return _block_actions(payload, table, slack)
    if kind == "view_submission":
        return _view_submission(payload, table)
    return _response(400, "bad request")
