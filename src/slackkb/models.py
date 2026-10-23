"""Pydantic models for every boundary (Slice 1, rung C1)."""

import hashlib
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Severity(str, Enum):  # noqa: UP042
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class NoteStatus(str, Enum):  # noqa: UP042
    CAPTURED = "CAPTURED"


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
    text: str
    severity: Severity = Severity.LOW
    created_at: str = Field(default_factory=_utc_now_iso)
    status: NoteStatus = NoteStatus.CAPTURED


class CaptureRequest(BaseModel):
    """Slash-command form fields capture needs; other fields are ignored."""

    model_config = ConfigDict(extra="ignore")

    team_id: str
    channel_id: str
    user_id: str
    command: str
    text: str
    trigger_id: str
