"""/bnote capture handler: verify -> parse -> write CAPTURED -> enqueue -> ack (Slice 2).

The caller passes the DynamoDB Table and SQS client in; all access to them goes
through store.py and queue.py. Processing happens in worker.py (D-004).
"""

import base64
import binascii
import json
import logging
import urllib.parse
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from slackkb.config import Settings
from slackkb.models import CaptureJob, CaptureRequest, Note, note_id
from slackkb.queue import EnqueueError, send_capture_job
from slackkb.slack_verify import SignatureError, verify
from slackkb.store import StoreError, delete_if_captured, put_if_absent

logger = logging.getLogger(__name__)

ACK_TEXT = "Noted. Your report has been captured."
USAGE_TEXT = "Usage: /bnote <what happened>"
RETRY_TEXT = "Sorry, we couldn't process your report, please try again."


def _response(status: int, body: str, content_type: str) -> dict[str, Any]:
    return {"statusCode": status, "headers": {"Content-Type": content_type}, "body": body}


def _ephemeral(text: str) -> dict[str, Any]:
    body = json.dumps({"response_type": "ephemeral", "text": text})
    return _response(200, body, "application/json")


def _ack(note_id: str) -> dict[str, Any]:
    """The ack: same text, plus a section and a "Set severity" button (D-013)."""
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": ACK_TEXT}},
        {
            "type": "actions",
            "block_id": "note_actions",
            "elements": [
                {
                    "type": "button",
                    "action_id": "set_severity",
                    "text": {"type": "plain_text", "text": "Set severity"},
                    "value": note_id,
                }
            ],
        },
    ]
    body = json.dumps({"response_type": "ephemeral", "text": ACK_TEXT, "blocks": blocks})
    return _response(200, body, "application/json")


def _raw_body(event: Mapping[str, Any]) -> str:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        return base64.b64decode(body, validate=True).decode()
    return body


def handle(
    event: Mapping[str, Any], *, table: Any, sqs: Any, settings: Settings, now: int
) -> dict:
    """Handle one API Gateway proxy event for /bnote and return the proxy response."""
    headers = event.get("headers") or {}
    try:
        body = _raw_body(event)
        verify(headers, body, settings.signing_secret.get_secret_value(), now)
    except SignatureError as exc:
        logger.warning("capture rejected, reason=%s", exc)
        return _response(401, "unauthorized", "text/plain")
    except (binascii.Error, UnicodeDecodeError):
        logger.warning("capture rejected, reason=bad body encoding")
        return _response(401, "unauthorized", "text/plain")

    fields = dict(urllib.parse.parse_qsl(body, keep_blank_values=True))
    try:
        request = CaptureRequest.model_validate(fields)
    except ValidationError as exc:
        invalid = sorted({".".join(str(part) for part in e["loc"]) for e in exc.errors()})
        logger.warning("capture bad request, invalid_fields=%s", ",".join(invalid))
        return _response(400, "bad request", "text/plain")

    if not request.text.strip():
        logger.info(
            "empty capture, usage reply sent, team_id=%s user_id=%s",
            request.team_id,
            request.user_id,
        )
        return _ephemeral(USAGE_TEXT)

    note = Note(
        note_id=note_id(request.team_id, request.trigger_id),
        team_id=request.team_id,
        channel_id=request.channel_id,
        user_id=request.user_id,
        text=request.text,
    )
    if not put_if_absent(table, note):
        logger.info("duplicate capture, note_id=%s", note.note_id)
        return _ack(note.note_id)
    try:
        job = CaptureJob(note_id=note.note_id, response_url=request.response_url)
        send_capture_job(sqs, settings.capture_queue_url, job)
    except EnqueueError as exc:
        logger.warning("enqueue failed (%s), note_id=%s", exc, note.note_id)
        try:
            deleted = delete_if_captured(table, note.note_id)
        except StoreError as delete_exc:
            logger.warning("note delete failed (%s), note_id=%s", delete_exc, note.note_id)
        else:
            if not deleted:
                logger.warning("note not deleted, not captured or gone, note_id=%s", note.note_id)
        return _ephemeral(RETRY_TEXT)
    logger.info("note captured, note_id=%s", note.note_id)
    return _ack(note.note_id)
