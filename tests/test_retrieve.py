import io
import json
import logging

import boto3
import pytest
from botocore.response import StreamingBody
from botocore.stub import Stubber
from conftest import EMBED_MODEL_ID

from slackkb import blob, worker
from slackkb import retrieve as retrieve_mod
from slackkb.embed import DIMENSIONS, EmbedError
from slackkb.models import CaptureJob, Note
from slackkb.retrieve import retrieve
from slackkb.store import put_if_absent
from slackkb.vectors import put_vector

TEAM = "T000TEST"
QUESTION = "why are orders timing out?"


def unit(i, scale=1.0):
    v = [0.0] * DIMENSIONS
    v[i] = scale
    return v


@pytest.fixture
def client():
    return boto3.client("bedrock-runtime", region_name="us-east-1")


def stub_embedding(stub, vec):
    raw = json.dumps({"embedding": vec}).encode()
    body = StreamingBody(io.BytesIO(raw), len(raw))
    stub.add_response("invoke_model", {"contentType": "application/json", "body": body})


def add_note(bucket, vectors_table, note_id, vector, team=TEAM, text=None):
    note = Note(
        note_id=note_id, team_id=team, channel_id="C1", user_id="U1", text=text or f"text {note_id}"
    )
    blob.put_note(bucket, note)
    put_vector(vectors_table, team, note_id, vector)
    return note


def run(client, vectors_table, bucket, query_vec, **kwargs):
    with Stubber(client) as stub:
        stub_embedding(stub, query_vec)
        out = retrieve(
            QUESTION,
            kwargs.pop("team", TEAM),
            client=client,
            model_id=EMBED_MODEL_ID,
            vectors_table=vectors_table,
            bucket=bucket,
            **kwargs,
        )
        stub.assert_no_pending_responses()
    return out


def test_retrieval_excludes_frontmatter(notes_table, notes_bucket, vectors_table, client):
    note_id = "a" * 32
    note = Note(
        note_id=note_id, team_id=TEAM, channel_id="C1", user_id="U1",
        text="db connection timeouts on /api/orders",
    )
    assert put_if_absent(notes_table, note)
    seen = []

    def embed(text):
        seen.append(text)
        return unit(0)

    body = CaptureJob(note_id=note_id).model_dump_json()
    event = {"Records": [{"messageId": "m1", "body": body}]}
    resp = worker.handle(
        event, table=notes_table, bucket=notes_bucket, vectors_table=vectors_table, embed=embed
    )
    assert resp == {"batchItemFailures": []}
    assert seen == [note.text]
    frontmatter = (note.note_id, note.team_id, note.channel_id, note.user_id, note.created_at)
    for field in (*frontmatter, "---"):
        assert field not in seen[0]
    out = run(client, vectors_table, notes_bucket, unit(0))
    assert [n.note_id for n in out] == [note_id]
    assert out[0].text == note.text


def test_ranks_by_dot_product_top_k(notes_bucket, vectors_table, client):
    add_note(notes_bucket, vectors_table, "low", unit(0, 0.1))
    add_note(notes_bucket, vectors_table, "high", unit(0, 0.9))
    add_note(notes_bucket, vectors_table, "mid", unit(0, 0.5))
    out = run(client, vectors_table, notes_bucket, unit(0), k=2)
    assert [n.note_id for n in out] == ["high", "mid"]


@pytest.mark.parametrize("order", [("c", "a", "b"), ("b", "c", "a"), ("c", "b", "a")])
def test_ties_break_by_note_id(notes_bucket, vectors_table, client, monkeypatch, order):
    for nid in order:
        add_note(notes_bucket, vectors_table, nid, unit(0))
    add_note(notes_bucket, vectors_table, "z", unit(0, 0.1))
    real = retrieve_mod.list_vectors

    # DynamoDB returns a partition in sort-key order; hand them back shuffled so only
    # an explicit tie-break can produce note_id order.
    def shuffled(table, team_id):
        by_id = dict(real(table, team_id))
        return [("z", by_id["z"]), *((nid, by_id[nid]) for nid in order)]

    monkeypatch.setattr(retrieve_mod, "list_vectors", shuffled)
    out = run(client, vectors_table, notes_bucket, unit(0), k=2)
    assert [n.note_id for n in out] == ["a", "b"]


def test_other_team_never_returned(notes_bucket, vectors_table, client):
    add_note(notes_bucket, vectors_table, "mine", unit(0, 0.1))
    add_note(notes_bucket, vectors_table, "theirs", unit(0, 0.9), team="T999OTHER")
    out = run(client, vectors_table, notes_bucket, unit(0))
    assert [n.note_id for n in out] == ["mine"]


def test_no_vectors_skips_bedrock(notes_bucket, vectors_table, client):
    with Stubber(client) as stub:
        out = retrieve(
            QUESTION, TEAM, client=client, model_id=EMBED_MODEL_ID,
            vectors_table=vectors_table, bucket=notes_bucket,
        )
        stub.assert_no_pending_responses()
    assert out == []


def test_missing_object_skipped_and_logged(notes_bucket, vectors_table, client, caplog):
    add_note(notes_bucket, vectors_table, "first", unit(0, 0.9))
    put_vector(vectors_table, TEAM, "ghost", unit(0, 0.8))
    add_note(notes_bucket, vectors_table, "third", unit(0, 0.7))
    with caplog.at_level(logging.WARNING, logger="slackkb"):
        out = run(client, vectors_table, notes_bucket, unit(0), k=2)
    # "third" does not replace the missing "ghost".
    assert [n.note_id for n in out] == ["first"]
    assert "ghost" in caplog.text


@pytest.mark.parametrize("kind", ["client_error", "bad_body"])
def test_embed_error_propagates(notes_bucket, vectors_table, client, kind):
    add_note(notes_bucket, vectors_table, "a", unit(0))
    with Stubber(client) as stub:
        if kind == "client_error":
            stub.add_client_error("invoke_model", service_error_code="ThrottlingException")
        else:
            raw = b"not json"
            stub.add_response(
                "invoke_model",
                {"contentType": "application/json", "body": StreamingBody(io.BytesIO(raw), 8)},
            )
        with pytest.raises(EmbedError):
            retrieve(
                QUESTION, TEAM, client=client, model_id=EMBED_MODEL_ID,
                vectors_table=vectors_table, bucket=notes_bucket,
            )
        stub.assert_no_pending_responses()


def test_k_below_one_rejected(notes_bucket, vectors_table, client):
    add_note(notes_bucket, vectors_table, "a", unit(0))
    for k in (0, -1):
        with pytest.raises(ValueError):
            retrieve(
                QUESTION, TEAM, client=client, model_id=EMBED_MODEL_ID,
                vectors_table=vectors_table, bucket=notes_bucket, k=k,
            )


def test_question_never_logged(notes_bucket, vectors_table, client, caplog):
    add_note(notes_bucket, vectors_table, "a", unit(0), text="secret note body")
    put_vector(vectors_table, TEAM, "ghost", unit(0, 0.5))
    with caplog.at_level(logging.DEBUG, logger="slackkb"):
        run(client, vectors_table, notes_bucket, unit(0))
    ours = [r.getMessage() for r in caplog.records if r.name.startswith("slackkb")]
    assert ours
    assert all(QUESTION not in m and "secret note body" not in m for m in ours)
