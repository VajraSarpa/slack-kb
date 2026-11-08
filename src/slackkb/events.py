"""Events API handler for @-mentions of the bot: verify -> parse -> claim -> enqueue (Slice 7a).

The caller passes the events Table and SQS client in; all access to them goes
through dedup.py and queue.py. Answering the question is Slice 7b (D-017).
"""

import base64
import binascii
import json
import logging
import re
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from slackkb import obs
from slackkb.config import Settings
from slackkb.dedup import DedupError, claim, release
from slackkb.models import QuestionJob
from slackkb.queue import EnqueueError, send_question_job
from slackkb.slack_verify import SignatureError, verify

logger = logging.getLogger(__name__)

_MENTION_RE = re.compile(r"<@U[^>]*>")


def _response(status: int, body: str, content_type: str = "text/plain") -> dict[str, Any]:
    return {"statusCode": status, "headers": {"Content-Type": content_type}, "body": body}


def _raw_body(event: Mapping[str, Any]) -> str:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        return base64.b64decode(body, validate=True).decode()
    return body


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _handle_mention(
    payload: Mapping[str, Any], *, events_table: Any, sqs: Any, settings: Settings, now: int
) -> dict[str, Any]:
    mention = payload.get("event")
    if not isinstance(mention, dict):
        logger.warning("event bad request, invalid_fields=event")
        return _response(400, "bad request")
    if mention.get("bot_id") or mention.get("subtype"):
        return _response(200, "ok")

    top = {"event_id": payload.get("event_id"), "team_id": payload.get("team_id")}
    inner = {key: mention.get(key) for key in ("channel", "user", "ts", "text")}
    invalid = sorted(
        [k for k, v in top.items() if not _nonempty(v)]
        + [f"event.{k}" for k, v in inner.items() if not _nonempty(v)]
    )
    if invalid:
        logger.warning("event bad request, invalid_fields=%s", ",".join(invalid))
        return _response(400, "bad request")

    event_id = top["event_id"]
    obs.bind(event_id)
    question = _MENTION_RE.sub("", inner["text"]).strip()
    if not question:
        logger.info("empty question ignored, event_id=%s", event_id)
        return _response(200, "ok")

    thread_ts = mention.get("thread_ts")
    try:
        job = QuestionJob(
            event_id=event_id,
            team_id=top["team_id"],
            channel=inner["channel"],
            user=inner["user"],
            thread_ts=thread_ts if _nonempty(thread_ts) else inner["ts"],
            question=question,
        )
    except ValidationError:
        logger.warning("event bad request, event_id=%s", event_id)
        return _response(400, "bad request")

    try:
        claimed = claim(events_table, event_id, now)
    except DedupError as exc:
        logger.warning("claim failed (%s), event_id=%s", exc, event_id)
        return _response(500, "error")
    if not claimed:
        logger.info("duplicate event, event_id=%s", event_id)
        return _response(200, "ok")

    try:
        send_question_job(sqs, settings.question_queue_url, job)
    except EnqueueError as exc:
        logger.warning("enqueue failed (%s), event_id=%s", exc, event_id)
        try:
            release(events_table, event_id)
        except DedupError as release_exc:
            logger.warning("claim release failed (%s), event_id=%s", release_exc, event_id)
        return _response(500, "error")
    logger.info("question enqueued, event_id=%s", event_id)
    return _response(200, "ok")


def handle(
    event: Mapping[str, Any], *, events_table: Any, sqs: Any, settings: Settings, now: int
) -> dict:
    """Handle one API Gateway proxy event from the Slack Events API."""
    with obs.trace():
        return _handle(event, events_table=events_table, sqs=sqs, settings=settings, now=now)


def _handle(
    event: Mapping[str, Any], *, events_table: Any, sqs: Any, settings: Settings, now: int
) -> dict:
    headers = event.get("headers") or {}
    try:
        body = _raw_body(event)
        verify(headers, body, settings.signing_secret.get_secret_value(), now)
    except SignatureError as exc:
        logger.warning("events rejected, reason=%s", exc)
        return _response(401, "unauthorized")
    except (binascii.Error, UnicodeDecodeError):
        logger.warning("events rejected, reason=bad body encoding")
        return _response(401, "unauthorized")

    try:
        payload = json.loads(body)
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        logger.warning("events bad request, body is not a JSON object")
        return _response(400, "bad request")

    kind = payload.get("type")
    if kind == "url_verification":
        challenge = payload.get("challenge")
        if not isinstance(challenge, str):
            logger.warning("events bad request, invalid_fields=challenge")
            return _response(400, "bad request")
        return _response(200, challenge)
    if kind == "event_callback":
        inner = payload.get("event")
        if isinstance(inner, dict) and inner.get("type") == "app_mention":
            return _handle_mention(
                payload, events_table=events_table, sqs=sqs, settings=settings, now=now
            )
    return _response(200, "ok")
