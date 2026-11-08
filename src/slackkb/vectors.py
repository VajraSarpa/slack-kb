"""The only module that touches the note_vectors table (Slice 6, D-008).

The caller passes the Table in. Vectors are packed little-endian float32 bytes.
"""

import logging
import math
import struct
from typing import Any

from boto3.dynamodb.conditions import Key

from slackkb.embed import DIMENSIONS, FLOAT32_MAX

logger = logging.getLogger(__name__)

_FORMAT = f"<{DIMENSIONS}f"
_SIZE = struct.calcsize(_FORMAT)


class VectorError(ValueError):
    """The vector cannot be stored as DIMENSIONS little-endian float32 values."""


def _pack(vector: list[float]) -> bytes:
    try:
        values = [float(x) for x in vector]
    except (TypeError, ValueError, OverflowError) as exc:
        raise VectorError("vector holds a value that is not a number") from exc
    if len(values) != DIMENSIONS:
        raise VectorError(f"vector is not {DIMENSIONS} values")
    if not all(math.isfinite(x) and abs(x) <= FLOAT32_MAX for x in values):
        raise VectorError("vector holds a value that is not a finite float32")
    return struct.pack(_FORMAT, *values)


def put_vector(table: Any, team_id: str, note_id: str, vector: list[float]) -> None:
    """Write a note's vector; an overwrite is fine. Raises VectorError before any write."""
    data = _pack(vector)
    table.put_item(Item={"team_id": team_id, "note_id": note_id, "vector": data})


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
