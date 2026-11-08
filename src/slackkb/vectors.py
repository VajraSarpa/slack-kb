"""The only module that touches the note_vectors table (Slice 6, D-008).

The caller passes the Table in. Vectors are packed little-endian float32 bytes.
"""

import logging
import struct
from typing import Any

from boto3.dynamodb.conditions import Key

from slackkb.embed import DIMENSIONS

logger = logging.getLogger(__name__)

_FORMAT = f"<{DIMENSIONS}f"
_SIZE = struct.calcsize(_FORMAT)


def put_vector(table: Any, team_id: str, note_id: str, vector: list[float]) -> None:
    """Write a note's vector; an overwrite is fine."""
    table.put_item(
        Item={
            "team_id": team_id,
            "note_id": note_id,
            "vector": struct.pack(_FORMAT, *vector),
        }
    )


def _unpack(raw: Any) -> list[float] | None:
    data = bytes(getattr(raw, "value", raw))
    if len(data) != _SIZE:
        return None
    return list(struct.unpack(_FORMAT, data))


def list_vectors(table: Any, team_id: str) -> list[tuple[str, list[float]]]:
    """All of one team's vectors; items with a malformed vector are skipped."""
    out: list[tuple[str, list[float]]] = []
    kwargs: dict[str, Any] = {"KeyConditionExpression": Key("team_id").eq(team_id)}
    while True:
        resp = table.query(**kwargs)
        for item in resp.get("Items", []):
            try:
                vector = _unpack(item["vector"])
            except (KeyError, TypeError, ValueError):
                vector = None
            if vector is None:
                logger.warning("bad vector skipped, note_id=%s", item.get("note_id"))
                continue
            out.append((item["note_id"], vector))
        last = resp.get("LastEvaluatedKey")
        if not last:
            return out
        kwargs["ExclusiveStartKey"] = last


def delete_vector(table: Any, team_id: str, note_id: str) -> None:
    """Remove a note's vector; a missing item is not an error."""
    table.delete_item(Key={"team_id": team_id, "note_id": note_id})
