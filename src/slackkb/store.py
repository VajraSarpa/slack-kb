"""DynamoDB access for notes. The only module that talks to DynamoDB.

The caller passes the boto3 Table in; nothing is created at import time.
"""

from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from slackkb.models import Note, NoteStatus, Severity


def put_if_absent(table: Any, note: Note) -> bool:
    """Write the note only if its note_id is new. True if written, False on duplicate."""
    try:
        table.put_item(
            Item=note.model_dump(mode="json"),
            ConditionExpression="attribute_not_exists(note_id)",
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise
    return True


def get_note(table: Any, note_id: str) -> Note | None:
    """Return the stored note, or None if there is no item with that note_id."""
    item = table.get_item(Key={"note_id": note_id}).get("Item")
    if item is None:
        return None
    return Note.model_validate(item)


class StoreError(Exception):
    """A DynamoDB call failed; the message names only the botocore error class."""


def delete_if_captured(table: Any, note_id: str) -> bool:
    """D-015: delete the note only if it exists and its status is CAPTURED.

    True if deleted, False if there is no item or it is in another status
    (left unchanged). Raises StoreError on any other botocore error.
    """
    try:
        table.delete_item(
            Key={"note_id": note_id},
            ConditionExpression="attribute_exists(note_id) AND #status = :captured",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":captured": NoteStatus.CAPTURED.value},
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise StoreError("ClientError") from None
    except BotoCoreError as exc:
        raise StoreError(type(exc).__name__) from None
    return True


class NoteNotFoundError(LookupError):
    """No note with that note_id exists."""


def transition_status(
    table: Any,
    note_id: str,
    to: NoteStatus,
    *,
    expected: NoteStatus = NoteStatus.CAPTURED,
) -> bool:
    """D-009: set status to `to` only if it is currently `expected`.

    True if updated, False if the note is in another status (left unchanged).
    Raises NoteNotFoundError if there is no such note.
    """
    try:
        table.update_item(
            Key={"note_id": note_id},
            UpdateExpression="SET #status = :to",
            ConditionExpression="attribute_exists(note_id) AND #status = :expected",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":to": to.value, ":expected": expected.value},
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
        item = table.get_item(Key={"note_id": note_id}, ProjectionExpression="note_id")
        if "Item" not in item:
            raise NoteNotFoundError(note_id) from None
        return False
    return True


def set_severity(table: Any, note_id: str, severity: Severity) -> None:
    """Set the note's severity only; status and every other attribute are untouched (D-009).

    Raises NoteNotFoundError if there is no such note.
    """
    try:
        table.update_item(
            Key={"note_id": note_id},
            UpdateExpression="SET severity = :severity",
            ConditionExpression="attribute_exists(note_id)",
            ExpressionAttributeValues={":severity": severity.value},
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            raise NoteNotFoundError(note_id) from None
        raise
