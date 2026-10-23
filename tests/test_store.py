import boto3
import pytest
from botocore.exceptions import ClientError

from slackkb.models import Note
from slackkb.store import get_note, put_if_absent


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
