import boto3
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from slackkb.models import Note, NoteStatus
from slackkb.store import StoreError, delete_if_captured, get_note, put_if_absent


def make_note(**overrides) -> Note:
    fields = {
        "note_id": "a" * 32,
        "team_id": "T1",
        "channel_id": "C1",
        "user_id": "U1",
        "text": "first report",
    }
    fields.update(overrides)
    return Note(**fields)


def test_put_if_absent_writes(notes_table):
    note = make_note()
    assert put_if_absent(notes_table, note) is True
    item = notes_table.get_item(Key={"note_id": note.note_id}).get("Item")
    assert item is not None
    assert item["text"] == "first report"


def test_put_if_absent_false_on_duplicate(notes_table):
    first = make_note()
    second = make_note(text="second report", user_id="U2")
    assert put_if_absent(notes_table, first) is True
    assert put_if_absent(notes_table, second) is False
    # the first item is unchanged
    assert get_note(notes_table, first.note_id) == first
    assert notes_table.scan()["Count"] == 1


def test_store_round_trips_note(notes_table):
    note = make_note(severity="HIGH")
    assert get_note(notes_table, note.note_id) is None
    assert put_if_absent(notes_table, note) is True
    assert get_note(notes_table, note.note_id) == note


def test_put_if_absent_propagates_other_errors(notes_table):
    missing = boto3.resource("dynamodb").Table("no-such-table")
    with pytest.raises(ClientError) as exc:
        put_if_absent(missing, make_note())
    assert exc.value.response["Error"]["Code"] != "ConditionalCheckFailedException"


def test_set_severity_leaves_status(notes_table):
    from slackkb.models import NoteStatus, Severity
    from slackkb.store import set_severity

    note = make_note(status=NoteStatus.ROUTED)
    assert put_if_absent(notes_table, note)
    set_severity(notes_table, note.note_id, Severity.CRITICAL)
    assert get_note(notes_table, note.note_id) == note.model_copy(
        update={"severity": Severity.CRITICAL}
    )


def test_set_severity_missing_note_raises(notes_table):
    from slackkb.models import Severity
    from slackkb.store import NoteNotFoundError, set_severity

    with pytest.raises(NoteNotFoundError):
        set_severity(notes_table, "f" * 32, Severity.HIGH)
    assert notes_table.scan()["Count"] == 0


def test_delete_if_captured_deletes_captured(notes_table):
    note = make_note()
    assert put_if_absent(notes_table, note)
    assert delete_if_captured(notes_table, note.note_id) is True
    assert get_note(notes_table, note.note_id) is None


def test_delete_if_captured_leaves_routed(notes_table):
    note = make_note(status=NoteStatus.ROUTED)
    assert put_if_absent(notes_table, note)
    assert delete_if_captured(notes_table, note.note_id) is False
    assert get_note(notes_table, note.note_id) == note


def test_delete_if_captured_false_for_missing(notes_table):
    assert delete_if_captured(notes_table, "f" * 32) is False
    assert notes_table.scan()["Count"] == 0


def test_delete_if_captured_wraps_other_errors(notes_table):
    missing = boto3.resource("dynamodb").Table("no-such-table")
    with pytest.raises(StoreError) as exc:
        delete_if_captured(missing, "a" * 32)
    assert "ClientError" in str(exc.value)
    assert "a" * 32 not in str(exc.value)


def test_delete_if_captured_wraps_botocore_errors():
    class _UnreachableTable:
        def delete_item(self, **kwargs):
            raise EndpointConnectionError(endpoint_url="https://dynamodb.invalid")

    with pytest.raises(StoreError) as exc:
        delete_if_captured(_UnreachableTable(), "a" * 32)
    assert str(exc.value) == "EndpointConnectionError"
    assert "a" * 32 not in str(exc.value)
    assert "dynamodb.invalid" not in str(exc.value)
