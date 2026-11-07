"""The only module that talks to S3 (Slice 4, D-014). The caller passes the Bucket in."""

from typing import Any

from botocore.exceptions import ClientError

from slackkb.models import Note
from slackkb.okf_note import OkfNote, from_markdown, to_markdown

CONTENT_TYPE = "text/markdown; charset=utf-8"
_MISSING = {"NoSuchKey", "404", "NotFound"}


def _key(team_id: str, note_id: str) -> str:
    return f"notes/{team_id}/{note_id}.md"


def put_note(bucket: Any, note: Note) -> None:
    """Write the note as an OKF Markdown object; an overwrite is fine."""
    bucket.Object(_key(note.team_id, note.note_id)).put(
        Body=to_markdown(note).encode("utf-8"), ContentType=CONTENT_TYPE
    )


def delete_note(bucket: Any, team_id: str, note_id: str) -> None:
    """Remove a note's object; a missing key is not an error (D-014)."""
    bucket.Object(_key(team_id, note_id)).delete()


def get_note(bucket: Any, team_id: str, note_id: str) -> OkfNote | None:
    """Read a note back; None if the key does not exist."""
    key = _key(team_id, note_id)
    try:
        body = bucket.Object(key).get()["Body"].read()
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in _MISSING:
            return None
        raise
    return from_markdown(body.decode("utf-8"))
