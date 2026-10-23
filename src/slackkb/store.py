"""DynamoDB access for notes. The only module that talks to DynamoDB.

The caller passes the boto3 Table in; nothing is created at import time.
"""

from typing import Any

from botocore.exceptions import ClientError

from slackkb.models import Note


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
