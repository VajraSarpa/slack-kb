"""SQS batch handler: CaptureJob -> note ROUTED (Slice 2, D-009).

The caller passes the DynamoDB Table in; all access to it goes through store.py.
Failed records are reported individually so SQS redelivers only those (D-004).
"""

import logging
from collections.abc import Callable, Mapping
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError

from slackkb import obs
from slackkb.blob import delete_note, put_note
from slackkb.embed import EmbedError
from slackkb.models import CaptureJob, Note, NoteStatus
from slackkb.store import NoteNotFoundError, get_note, route_note
from slackkb.vectors import VectorError, delete_vector, put_vector

logger = logging.getLogger(__name__)


def _remove_object(bucket: Any, note: Note, message_id: str, vectors_table: Any) -> bool:
    """A FAILED note has no S3 object or vector (D-014). False if a delete failed: SQS retries."""
    try:
        delete_note(bucket, note.team_id, note.note_id)
    except (ClientError, BotoCoreError) as exc:
        logger.warning(
            "blob delete error %s, note_id=%s message_id=%s",
            type(exc).__name__,
            note.note_id,
            message_id,
        )
        return False
    try:
        delete_vector(vectors_table, note.team_id, note.note_id)
    except (ClientError, BotoCoreError) as exc:
        logger.warning(
            "vector delete error %s, note_id=%s message_id=%s",
            type(exc).__name__,
            note.note_id,
            message_id,
        )
        return False
    return True


def _process(
    record: Mapping[str, Any],
    table: Any,
    bucket: Any,
    vectors_table: Any,
    embed: Callable[[str], list[float]],
) -> bool:
    """Write one record's note to S3 and its vector, then route it. True on success."""
    message_id = record["messageId"]
    try:
        job = CaptureJob.model_validate_json(record.get("body") or "")
    except ValidationError:
        logger.warning("unparsable capture job, message_id=%s", message_id)
        return False
    obs.bind(job.note_id)
    try:
        note = get_note(table, job.note_id)
        if note is None:
            raise NoteNotFoundError(job.note_id)
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
    if note.status is NoteStatus.FAILED:
        if not _remove_object(bucket, note, message_id, vectors_table):
            return False
        logger.info("note failed, no object, note_id=%s message_id=%s", note.note_id, message_id)
        return True
    if note.status is NoteStatus.ROUTED:
        logger.info(
            "note already routed, nothing written, note_id=%s message_id=%s",
            note.note_id,
            message_id,
        )
        return True
    try:
        put_note(bucket, note)
    except (ClientError, BotoCoreError) as exc:
        logger.warning(
            "blob error %s, note_id=%s message_id=%s",
            type(exc).__name__,
            job.note_id,
            message_id,
        )
        return False
    try:
        put_vector(vectors_table, note.team_id, note.note_id, embed(note.text or ""))
    except (EmbedError, VectorError, ClientError, BotoCoreError) as exc:
        logger.warning(
            "vector error %s, note_id=%s message_id=%s",
            type(exc).__name__,
            note.note_id,
            message_id,
        )
        return False
    try:
        routed = route_note(table, job.note_id)
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
    if routed:
        logger.info("note routed, note_id=%s message_id=%s", job.note_id, message_id)
        return True
    return _resolve_lost_race(table, bucket, note, message_id, vectors_table)


def _resolve_lost_race(
    table: Any, bucket: Any, note: Note, message_id: str, vectors_table: Any
) -> bool:
    """The status changed while the object was being written: settle it from the stored status."""
    try:
        current = get_note(table, note.note_id)
    except (ClientError, BotoCoreError) as exc:
        logger.warning(
            "store error %s on re-read, note_id=%s message_id=%s",
            type(exc).__name__,
            note.note_id,
            message_id,
        )
        return False
    if current is None:
        logger.warning(
            "note gone after write, note_id=%s message_id=%s", note.note_id, message_id
        )
        return False
    if current.status is NoteStatus.ROUTED:
        logger.info(
            "note routed by another delivery, note_id=%s message_id=%s", note.note_id, message_id
        )
        return True
    if current.status is NoteStatus.FAILED:
        if not _remove_object(bucket, note, message_id, vectors_table):
            return False
        logger.warning(
            "note failed while writing, object removed, note_id=%s message_id=%s",
            note.note_id,
            message_id,
        )
        return True
    logger.warning(
        "note status %s after lost race, note_id=%s message_id=%s",
        current.status.value,
        note.note_id,
        message_id,
    )
    return False


def handle(
    event: Mapping[str, Any],
    *,
    table: Any,
    bucket: Any,
    vectors_table: Any,
    embed: Callable[[str], list[float]],
) -> dict:
    """Handle one SQS Lambda event; return the partial batch response.

    embed maps a note's text to its vector; the Lambda entry point binds embed_text to a
    Bedrock client and model id. Both arguments are required: no note is ROUTED without
    its vector (D-008).
    """
    failures = []
    for record in event.get("Records") or []:
        with obs.trace():
            try:
                ok = _process(record, table, bucket, vectors_table, embed)
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
