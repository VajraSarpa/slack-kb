import logging
import struct

from boto3.dynamodb.types import Binary

from slackkb import vectors
from slackkb.embed import DIMENSIONS


def vec(seed):
    return [seed + i / 1000 for i in range(DIMENSIONS)]


def f32(v):
    return list(struct.unpack(f"<{len(v)}f", struct.pack(f"<{len(v)}f", *v)))


def test_put_then_list_round_trips(vectors_table):
    vectors.put_vector(vectors_table, "T1", "n1", vec(0.1))
    item = vectors_table.get_item(Key={"team_id": "T1", "note_id": "n1"})["Item"]
    assert isinstance(item["vector"], Binary)
    assert len(bytes(item["vector"])) == 4 * DIMENSIONS
    assert vectors.list_vectors(vectors_table, "T1") == [("n1", f32(vec(0.1)))]


def test_put_overwrites(vectors_table):
    vectors.put_vector(vectors_table, "T1", "n1", vec(0.1))
    vectors.put_vector(vectors_table, "T1", "n1", vec(0.2))
    assert vectors.list_vectors(vectors_table, "T1") == [("n1", f32(vec(0.2)))]


def test_list_reads_one_partition_only(vectors_table):
    vectors.put_vector(vectors_table, "T1", "n1", vec(0.1))
    vectors.put_vector(vectors_table, "T2", "n2", vec(0.2))
    assert [n for n, _ in vectors.list_vectors(vectors_table, "T1")] == ["n1"]
    assert vectors.list_vectors(vectors_table, "T3") == []


def test_list_follows_pagination():
    pages = [
        {"Items": [{"note_id": "a", "vector": struct.pack(f"<{DIMENSIONS}f", *vec(1))}],
         "LastEvaluatedKey": {"team_id": "T1", "note_id": "a"}},
        {"Items": [{"note_id": "b", "vector": struct.pack(f"<{DIMENSIONS}f", *vec(2))}]},
    ]
    calls = []

    class Table:
        def query(self, **kwargs):
            calls.append(kwargs)
            return pages[len(calls) - 1]

    out = vectors.list_vectors(Table(), "T1")
    assert [n for n, _ in out] == ["a", "b"]
    assert "ExclusiveStartKey" not in calls[0]
    assert calls[1]["ExclusiveStartKey"] == {"team_id": "T1", "note_id": "a"}


def test_bad_vector_item_skipped_and_logged(vectors_table, caplog):
    vectors.put_vector(vectors_table, "T1", "good", vec(0.1))
    vectors_table.put_item(Item={"team_id": "T1", "note_id": "short", "vector": b"\x00" * 8})
    vectors_table.put_item(Item={"team_id": "T1", "note_id": "novec"})
    with caplog.at_level(logging.WARNING, logger="slackkb"):
        out = vectors.list_vectors(vectors_table, "T1")
    assert [n for n, _ in out] == ["good"]
    text = caplog.text
    assert "short" in text and "novec" in text


def test_delete_removes_and_missing_is_ok(vectors_table):
    vectors.delete_vector(vectors_table, "T1", "nope")
    vectors.put_vector(vectors_table, "T1", "n1", vec(0.1))
    vectors.delete_vector(vectors_table, "T1", "n1")
    assert vectors.list_vectors(vectors_table, "T1") == []


def test_delete_missing_is_ok(vectors_table):
    vectors.delete_vector(vectors_table, "T1", "never-existed")
