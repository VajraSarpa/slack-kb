"""Pydantic models for every boundary (Slice 1, rung C1)."""

import hashlib
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Severity(str, Enum):  # noqa: UP042
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class NoteStatus(str, Enum):  # noqa: UP042
    CAPTURED = "CAPTURED"
    ROUTED = "ROUTED"
    FAILED = "FAILED"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def note_id(team_id: str, trigger_id: str) -> str:
    """D-006: sha256 of team_id:trigger_id, first 32 hex chars."""
    return hashlib.sha256(f"{team_id}:{trigger_id}".encode()).hexdigest()[:32]


class Note(BaseModel):
    """One captured report. note_id is a plain str here; derivation is rung C6 (D-006)."""

    note_id: str
    team_id: str
    channel_id: str
    user_id: str
    text: str | None = None
    severity: Severity = Severity.LOW
    created_at: str = Field(default_factory=_utc_now_iso)
    status: NoteStatus = NoteStatus.CAPTURED

    @model_validator(mode="after")
    def _text_required_unless_routed(self) -> "Note":
        """D-014: only a ROUTED note may have no text (S3 holds the only copy)."""
        if self.text is None and self.status is not NoteStatus.ROUTED:
            raise ValueError("text may be None only when status is ROUTED")
        return self


class CaptureRequest(BaseModel):
    """Slash-command form fields capture needs; other fields are ignored."""

    model_config = ConfigDict(extra="ignore")

    team_id: str
    channel_id: str
    user_id: str
    command: str
    text: str
    trigger_id: str


class CaptureJob(BaseModel):
    """SQS message body from capture to the worker (Slice 2, D-004)."""

    note_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class QuestionJob(BaseModel):
    """SQS message body from the events handler to the question worker (D-017)."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1)
    team_id: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    user: str = Field(min_length=1)
    thread_ts: str = Field(min_length=1)
    question: str = Field(min_length=1)
