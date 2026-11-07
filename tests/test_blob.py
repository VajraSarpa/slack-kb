import pytest
from botocore.exceptions import ClientError

from slackkb import blob
from slackkb.models import Note
from slackkb.okf_note import object_key, to_markdown


def _note(text="hello ünï\n---\nworld"):
    return Note(note_id="a" * 32, team_id="T1", channel_id="C1", user_id="U1", text=text)


def test_put_then_get_round_trips(notes_bucket):
    note = _note()
    assert blob.put_note(notes_bucket, note) is None
    obj = notes_bucket.Object(object_key(note))
    assert obj.content_type == "text/markdown; charset=utf-8"
    assert obj.get()["Body"].read() == to_markdown(note).encode("utf-8")
    got = blob.get_note(notes_bucket, "T1", "a" * 32)
    assert got is not None
    assert (got.note_id, got.team_id, got.channel_id, got.user_id) == ("a" * 32, "T1", "C1", "U1")
    assert got.created_at == note.created_at
    assert got.text == note.text


def test_get_missing_returns_none(notes_bucket):
    assert blob.get_note(notes_bucket, "T1", "b" * 32) is None


def test_get_other_s3_errors_propagate(aws):
    import boto3

    missing_bucket = boto3.resource("s3").Bucket("no-such-bucket")
    with pytest.raises(ClientError):
        blob.get_note(missing_bucket, "T1", "a" * 32)


def test_delete_removes_object(notes_bucket):
    blob.put_note(notes_bucket, _note())
    assert blob.delete_note(notes_bucket, "T1", "a" * 32) is None
    assert blob.get_note(notes_bucket, "T1", "a" * 32) is None
    assert list(notes_bucket.objects.all()) == []


def test_delete_missing_key_is_fine(notes_bucket):
    assert blob.delete_note(notes_bucket, "T1", "z" * 32) is None


def test_delete_other_s3_errors_propagate(aws):
    import boto3

    missing_bucket = boto3.resource("s3").Bucket("no-such-bucket")
    with pytest.raises(ClientError):
        blob.delete_note(missing_bucket, "T1", "a" * 32)


def test_put_get_delete_share_one_key_helper(notes_bucket, monkeypatch):
    monkeypatch.setattr(blob, "_key", lambda team_id, note_id: "elsewhere/x.md")
    blob.put_note(notes_bucket, _note())
    assert [o.key for o in notes_bucket.objects.all()] == ["elsewhere/x.md"]
    assert blob.get_note(notes_bucket, "T1", "a" * 32) is not None
    blob.delete_note(notes_bucket, "T1", "a" * 32)
    assert list(notes_bucket.objects.all()) == []


def test_blob_keys_come_from_okf_note_key_for(notes_bucket):
    n = _note()
    blob.put_note(notes_bucket, n)
    assert [o.key for o in notes_bucket.objects.all()] == [object_key(n)]


def test_put_overwrites(notes_bucket):
    blob.put_note(notes_bucket, _note("first"))
    blob.put_note(notes_bucket, _note("second"))
    assert blob.get_note(notes_bucket, "T1", "a" * 32).text == "second"
    assert len(list(notes_bucket.objects.all())) == 1
