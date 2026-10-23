"""SQS batch handler: CaptureJob -> note ROUTED (Slice 2, D-009).

The caller passes the DynamoDB Table in; all access to it goes through store.py.
Failed records are reported individually so SQS redelivers only those (D-004).
"""

import logging
from collections.abc import Mapping
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError

from slackkb.models import CaptureJob, NoteStatus
from slackkb.store import NoteNotFoundError, transition_status

logger = logging.getLogger(__name__)


def _process(record: Mapping[str, Any], table: Any) -> bool:
    """Route one record's note. True on success, including a note already past CAPTURED."""
    message_id = record["messageId"]
    try:
        job = CaptureJob.model_validate_json(record.get("body") or "")
    except ValidationError:
        logger.warning("unparsable capture job, message_id=%s", message_id)
        return False
    try:
        transition_status(table, job.note_id, NoteStatus.ROUTED)
    except NoteNotFoundError:
        logger.warning("note not found, note_id=%s message_id=%s", job.note_id, message_id)
        return False
    except (ClientError, BotoCoreError) as exc:
        logger.warning(
            "store error %s, note_id=%s message_id=%s",
            type(exc).__name__,
            job.note_id,
            message_id,
        )
        return False
    return True


def handle(event: Mapping[str, Any], *, table: Any) -> dict:
    """Handle one SQS Lambda event; return the partial batch response."""
    failures = [
        {"itemIdentifier": record["messageId"]}
        for record in event.get("Records") or []
        if not _process(record, table)
    ]
    return {"batchItemFailures": failures}
