"""Events API dedup claims (D-011). The only module that touches the events table.

The caller passes the DynamoDB Table in; nothing is created at import time.
"""

from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

CLAIM_TTL_SECONDS = 3600


class DedupError(Exception):
    """The events table could not be read or written. The message names only the error class."""


def claim(table: Any, event_id: str, now: int) -> bool:
    """Claim event_id; True if newly claimed, False if it was already claimed."""
    try:
        table.put_item(
            Item={"event_id": event_id, "expires_at": now + CLAIM_TTL_SECONDS},
            ConditionExpression="attribute_not_exists(event_id)",
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise DedupError(type(exc).__name__) from exc
    except BotoCoreError as exc:
        raise DedupError(type(exc).__name__) from exc
    return True


def release(table: Any, event_id: str) -> None:
    """Delete the claim on event_id; a missing item is not an error."""
    try:
        table.delete_item(Key={"event_id": event_id})
    except (ClientError, BotoCoreError) as exc:
        raise DedupError(type(exc).__name__) from exc
