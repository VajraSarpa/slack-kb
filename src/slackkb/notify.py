"""Capture-DLQ batch handler: a note whose job gave up is FAILED and the user is told (D-018).

The caller passes the DynamoDB Tables, the Bucket and the `post` callable in; all access
goes through store.py, blob.py, vectors.py and slack_api.py. Records that must be retried
are reported individually so SQS redelivers only those. Neither the response_url nor the
note text is ever logged.
"""

import logging
from collections.abc import Callable, Mapping
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError

from slackkb import obs
from slackkb.blob import delete_note
from slackkb.models import CaptureJob, NoteStatus
from slackkb.slack_api import ResponseUrlError
from slackkb.store import NoteNotFoundError, get_note, transition_status
from slackkb.vectors import delete_vector

logger = logging.getLogger(__name__)

FAILED_TEXT = "Sorry, your /bnote note couldn't be saved. Please run /bnote again."


def _process(
    record: Mapping[str, Any],
    table: Any,
    bucket: Any,
    vectors_table: Any,
    post: Callable[[str, str], None],
) -> bool:
    """Fail one DLQ record's note and tell the user. True if done, False to retry."""
    message_id = record["messageId"]
    try:
        job = CaptureJob.model_validate_json(record.get("body") or "")
    except ValidationError:
        logger.warning("unparsable capture job, message_id=%s", message_id)
        return True
    note_id = job.note_id
    obs.bind(note_id)
    try:
        moved = transition_status(table, note_id, NoteStatus.FAILED)
    except NoteNotFoundError:
        logger.warning("note not found, note_id=%s message_id=%s", note_id, message_id)
        return True
    except (ClientError, BotoCoreError) as exc:
        logger.warning(
            "store error %s, note_id=%s message_id=%s", type(exc).__name__, note_id, message_id
        )
        return False
    if moved:
        logger.info("note failed, note_id=%s message_id=%s", note_id, message_id)
    try:
        note = get_note(table, note_id)
    except (ClientError, BotoCoreError) as exc:
        logger.warning(
            "store error %s on read, note_id=%s message_id=%s",
            type(exc).__name__,
            note_id,
            message_id,
        )
        return False
    if note is None:
        logger.warning("note gone, note_id=%s message_id=%s", note_id, message_id)
        return True
    if note.status is not NoteStatus.FAILED:
        logger.info(
            "note is %s, no notice, note_id=%s message_id=%s",
            note.status.value,
            note_id,
            message_id,
        )
        return True
    return _remove_and_tell(job, note.team_id, message_id, bucket, vectors_table, post)


def _remove_and_tell(
    job: CaptureJob,
    team_id: str,
    message_id: str,
    bucket: Any,
    vectors_table: Any,
    post: Callable[[str, str], None],
) -> bool:
    """Delete the FAILED note's object and vector (D-014), then post the notice."""
    note_id = job.note_id
    try:
        delete_note(bucket, team_id, note_id)
        delete_vector(vectors_table, team_id, note_id)
    except (ClientError, BotoCoreError) as exc:
        logger.warning(
            "delete error %s, note_id=%s message_id=%s", type(exc).__name__, note_id, message_id
        )
        return False
    if job.response_url is None:
        logger.warning(
            "no reply URL, user can't be told, note_id=%s message_id=%s", note_id, message_id
        )
        return True
    try:
        post(job.response_url, FAILED_TEXT)
    except ResponseUrlError as exc:
        if exc.status is not None and 400 <= exc.status <= 499:
            logger.warning(
                "notice rejected, status=%s, note_id=%s message_id=%s",
                exc.status,
                note_id,
                message_id,
            )
            return True
        logger.warning(
            "notice failed, status=%s, note_id=%s message_id=%s", exc.status, note_id, message_id
        )
        return False
    logger.info("user notified, note_id=%s message_id=%s", note_id, message_id)
    return True


def handle(
    event: Mapping[str, Any],
    *,
    table: Any,
    bucket: Any,
    vectors_table: Any,
    post: Callable[[str, str], None],
) -> dict:
    """Handle one SQS Lambda event from the capture DLQ; return the partial batch response.

    post is called as post(response_url, FAILED_TEXT); the Lambda entry point binds it to
    slack_api.post_response_url.
    """
    failures = []
    for record in event.get("Records") or []:
        with obs.trace():
            try:
                ok = _process(record, table, bucket, vectors_table, post)
            except Exception as exc:  # D-023: fail only this record; class name only
                logger.warning(
                    "record failed, %s, message_id=%s",
                    type(exc).__name__,
                    record["messageId"],
                )
                ok = False
        if not ok:
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
