"""Note <-> OKF Markdown, pure (Slice 4, D-014).

Frontmatter holds only immutable fields; severity and status stay in DynamoDB.
"""

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from slackkb.models import Note

DELIMITER = "---\n"


class OkfNoteError(ValueError):
    """The Markdown is not a well-formed OKF note."""


class OkfNote(BaseModel):
    """A note as stored in S3: the five frontmatter fields plus the body text."""

    model_config = ConfigDict(extra="forbid")

    note_id: str
    team_id: str
    channel_id: str
    user_id: str
    created_at: str
    text: str


class _Frontmatter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note_id: str
    team_id: str
    channel_id: str
    user_id: str
    created_at: str


def object_key(note: Note | OkfNote) -> str:
    return f"notes/{note.team_id}/{note.note_id}.md"


def to_markdown(note: Note) -> str:
    frontmatter = {
        "note_id": note.note_id,
        "team_id": note.team_id,
        "channel_id": note.channel_id,
        "user_id": note.user_id,
        "created_at": note.created_at,
    }
    return DELIMITER + yaml.safe_dump(frontmatter, sort_keys=True) + DELIMITER + note.text


def from_markdown(md: str) -> OkfNote:
    if not md.startswith(DELIMITER):
        raise OkfNoteError("missing opening delimiter")
    rest = md[len(DELIMITER) :]
    if rest.startswith(DELIMITER):
        head, body = "", rest[len(DELIMITER) :]
    else:
        end = rest.find("\n" + DELIMITER)
        if end < 0:
            raise OkfNoteError("missing closing delimiter")
        head, body = rest[: end + 1], rest[end + 1 + len(DELIMITER) :]
    try:
        data = yaml.safe_load(head)
    except yaml.YAMLError:
        raise OkfNoteError("frontmatter is not valid YAML") from None
    if not isinstance(data, dict):
        raise OkfNoteError("frontmatter is not a mapping")
    try:
        front = _Frontmatter.model_validate(data)
    except ValidationError as exc:
        raise OkfNoteError(f"invalid frontmatter: {exc.error_count()} error(s)") from None
    return OkfNote(**front.model_dump(), text=body)
