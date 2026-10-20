import json
from datetime import datetime, timedelta

import pytest
from conftest import FIXTURES
from pydantic import ValidationError

from slackkb.models import CaptureRequest, Note, NoteStatus, Severity


def _note(**overrides):
    fields = {
        "note_id": "n" * 32,
        "team_id": "T000TEST",
        "channel_id": "C000TEST",
        "user_id": "U000TEST",
        "text": "db connection timeouts",
    }
    fields.update(overrides)
    return Note(**fields)


def test_note_defaults_low_and_captured():
    note = _note()
    assert note.severity is Severity.LOW
    assert note.status is NoteStatus.CAPTURED
    assert [s.value for s in Severity] == ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


def test_note_model_rejects_unknown_severity():
    with pytest.raises(ValidationError):
        _note(severity="URGENT")


def test_created_at_is_utc_iso():
    created = _note().created_at
    assert isinstance(created, str)
    assert created.endswith("+00:00")
    assert datetime.fromisoformat(created).utcoffset() == timedelta(0)


def test_capture_request_ignores_extra_form_fields():
    fields = json.loads((FIXTURES / "slash_bnote.json").read_text())
    req = CaptureRequest(**fields)
    assert req.command == "/bnote"
    assert req.trigger_id == "1111.2222.abcdef"
    assert not hasattr(req, "response_url")
