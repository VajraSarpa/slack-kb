"""Question + team -> top-k notes by dot product (Slice 6, D-008)."""

import logging
from typing import Any

from slackkb.blob import get_note
from slackkb.embed import embed_text
from slackkb.okf_note import OkfNote
from slackkb.vectors import list_vectors

logger = logging.getLogger(__name__)


def retrieve(
    question: str,
    team_id: str,
    *,
    client: Any,
    model_id: str,
    vectors_table: Any,
    bucket: Any,
    k: int = 5,
) -> list[OkfNote]:
    """Return up to k of the team's notes, best match first; text comes from S3."""
    if k < 1:
        raise ValueError("k must be at least 1")
    stored = list_vectors(vectors_table, team_id)
    if not stored:
        return []
    query = embed_text(client, model_id=model_id, text=question)
    scored = [(sum(a * b for a, b in zip(query, vec, strict=True)), nid) for nid, vec in stored]
    scored.sort(key=lambda s: (-s[0], s[1]))
    notes: list[OkfNote] = []
    for _, note_id in scored[:k]:
        note = get_note(bucket, team_id, note_id)
        if note is None:
            logger.warning("note object missing, skipped, note_id=%s", note_id)
            continue
        notes.append(note)
    return notes
