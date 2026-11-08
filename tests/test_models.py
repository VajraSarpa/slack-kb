import json
from datetime import datetime, timedelta

import pytest
from conftest import FIXTURES
from pydantic import ValidationError

from slackkb.models import CaptureRequest, Note, NoteStatus, QuestionJob, Severity


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


def test_note_text_none_only_when_routed():
    for status in (NoteStatus.CAPTURED, NoteStatus.FAILED):
        with pytest.raises(ValidationError):
            _note(text=None, status=status)
    assert _note(text=None, status=NoteStatus.ROUTED).text is None
    assert _note(text="x", status=NoteStatus.ROUTED).text == "x"


def test_question_job_rejects_empty_and_extra():
    fields = {
        "event_id": "Ev000TEST0001",
        "team_id": "T000TEST",
        "channel": "C000TEST",
        "user": "U000TEST",
        "thread_ts": "1762600000.000100",
        "question": "why?",
    }
    assert QuestionJob(**fields).question == "why?"
    for name in fields:
        with pytest.raises(ValidationError):
            QuestionJob(**{**fields, name: ""})
        missing = {k: v for k, v in fields.items() if k != name}
        with pytest.raises(ValidationError):
            QuestionJob(**missing)
    with pytest.raises(ValidationError):
        QuestionJob(**fields, extra="x")
