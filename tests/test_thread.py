import io
import json
import logging
import time
from datetime import UTC, datetime

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber
from conftest import EMBED_MODEL_ID
from pydantic import SecretStr

from slackkb import blob, store, thread
from slackkb.config import Settings
from slackkb.embed import DIMENSIONS, EmbedError
from slackkb.models import Note, QuestionJob, Severity
from slackkb.okf_note import OkfNote
from slackkb.qa import QaError, QaResult
from slackkb.slack_api import SlackClient
from slackkb.vectors import put_vector

TEAM = "T000TEST"
QA_MODEL_ID = "us.anthropic.claude-haiku-test"
POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"
POST_EPHEMERAL_URL = "https://slack.com/api/chat.postEphemeral"
QUESTION_MARKER = "QMARK-zebra-17"
ANSWER_MARKER = "AMARK-walrus-29"
NOTE_MARKER = "NMARK-otter-41"
LOGGER = "slackkb"


class FakeTransport:
    def __init__(self, replies=None):
        self.calls = []
        self.replies = replies or {}

    def __call__(self, url, headers, json_body):
        self.calls.append((url, dict(headers), dict(json_body)))
        return self.replies.get(url, {"ok": True})

    def posted(self, url):
        return [body for u, _, body in self.calls if u == url]


def make_job(**overrides):
    fields = {
        "event_id": "Ev1",
        "team_id": TEAM,
        "channel": "C1",
        "user": "U1",
        "thread_ts": "1700000000.000100",
        "question": "why are orders timing out?",
    }
    fields.update(overrides)
    return QuestionJob(**fields)


def record(job, message_id="m1"):
    return {"messageId": message_id, "body": job.model_dump_json()}


def make_note(note_id="n1", text="alpha", created_at="2026-11-07T00:00:00Z", channel_id="C1"):
    return OkfNote(
        note_id=note_id,
        team_id=TEAM,
        channel_id=channel_id,
        user_id="U1",
        created_at=created_at,
        text=text,
    )


def when(created_at="2026-11-07T00:00:00Z"):
    dt = datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(UTC)
    return (
        f"<!date^{int(dt.timestamp())}^{{date_short_pretty}} {{time}}"
        f"|{dt:%Y-%m-%d %H:%M} UTC>"
    )


def reply_for(notes, cited, answer="ok", severity_of=None):
    result = QaResult(answer=answer, cited_note_ids=cited)
    _, _, transport = run(
        [record(make_job())], Fakes(notes=notes, result=result), severity_of=severity_of
    )
    return transport.posted(POST_MESSAGE_URL)[0]["text"]


class Fakes:
    def __init__(self, notes=None, result=None, retrieve_exc=None, answer_exc=None):
        self.notes = [make_note()] if notes is None else notes
        self.result = result or QaResult(answer="It was alpha.", cited_note_ids=["n1"])
        self.retrieve_exc = retrieve_exc
        self.answer_exc = answer_exc
        self.retrieve_calls = []
        self.answer_calls = []

    def retrieve(self, question, team_id):
        self.retrieve_calls.append((question, team_id))
        if self.retrieve_exc is not None:
            raise self.retrieve_exc
        return self.notes

    def answer(self, question, notes):
        self.answer_calls.append((question, notes))
        if self.answer_exc is not None:
            raise self.answer_exc
        return self.result


def run(records, fakes=None, transport=None, severity_of=None):
    fakes = fakes or Fakes()
    transport = transport or FakeTransport()
    slack = SlackClient(SecretStr("xoxb-test"), transport)
    resp = thread.handle(
        {"Records": records},
        retrieve=fakes.retrieve,
        answer=fakes.answer,
        slack=slack,
        severity_of=severity_of,
    )
    return resp, fakes, transport


def warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


def test_reply_posts_in_thread_ts():
    job = make_job()
    resp, fakes, transport = run([record(job)])
    assert resp == {"batchItemFailures": []}
    assert fakes.retrieve_calls == [("why are orders timing out?", TEAM)]
    assert fakes.answer_calls == [("why are orders timing out?", fakes.notes)]
    assert transport.calls[0][0] == POST_MESSAGE_URL
    assert len(transport.calls) == 1
    assert transport.calls[0][2] == {
        "channel": "C1",
        "thread_ts": "1700000000.000100",
        "text": f"It was alpha.\n\nNotes:\n• {when()} in <#C1>",
    }


def test_slack_escape():
    assert thread.slack_escape("<!channel> & <@U1>") == "&lt;!channel&gt; &amp; &lt;@U1&gt;"
    assert thread.slack_escape("&lt;") == "&amp;lt;"


def embedding_response(vec):
    raw = json.dumps({"embedding": vec}).encode()
    return {"contentType": "application/json", "body": StreamingBody(io.BytesIO(raw), len(raw))}


def test_real_retrieve_wired(notes_bucket, vectors_table):
    note_id = "a" * 32
    note = Note(
        note_id=note_id, team_id=TEAM, channel_id="C1", user_id="U1", text="db timeouts on orders"
    )
    blob.put_note(notes_bucket, note)
    vec = [0.0] * DIMENSIONS
    vec[0] = 1.0
    put_vector(vectors_table, TEAM, note_id, vec)

    settings = Settings(capture_queue_url="https://sqs.us-east-1.amazonaws.com/1/q")
    bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")
    retrieve, answer = thread.bind(
        settings, bedrock=bedrock, vectors_table=vectors_table, bucket=notes_bucket
    )
    job = make_job()
    converse_out = {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": "t1",
                            "name": "answer",
                            "input": {"answer": "Use <b> & pool", "cited_note_ids": [note_id]},
                        }
                    }
                ],
            }
        },
        "stopReason": "tool_use",
        "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
        "metrics": {"latencyMs": 1},
    }
    transport = FakeTransport()
    slack = SlackClient(SecretStr("xoxb-test"), transport)
    with Stubber(bedrock) as stub:
        stub.add_response(
            "invoke_model",
            embedding_response(vec),
            {
                "modelId": EMBED_MODEL_ID,
                "contentType": "application/json",
                "accept": "application/json",
                "body": json.dumps(
                    {"inputText": job.question, "dimensions": DIMENSIONS, "normalize": True}
                ),
            },
        )
        stub.add_response(
            "converse",
            converse_out,
            {
                "modelId": QA_MODEL_ID,
                "system": ANY,
                "messages": ANY,
                "toolConfig": ANY,
                "inferenceConfig": {"maxTokens": 1024},
            },
        )
        resp = thread.handle(
            {"Records": [record(job)]}, retrieve=retrieve, answer=answer, slack=slack
        )
        stub.assert_no_pending_responses()
    assert resp == {"batchItemFailures": []}
    assert transport.posted(POST_MESSAGE_URL) == [
        {
            "channel": "C1",
            "thread_ts": "1700000000.000100",
            "text": (
                "Use &lt;b&gt; &amp; pool\n\nNotes:\n"
                f"• {when(note.created_at)} in <#C1>"
            ),
        }
    ]


def test_no_notes_reply_names_query():
    fakes = Fakes(notes=[])
    resp, fakes, transport = run([record(make_job())], fakes)
    assert resp == {"batchItemFailures": []}
    assert fakes.answer_calls == []
    assert transport.posted(POST_MESSAGE_URL) == [
        {
            "channel": "C1",
            "thread_ts": "1700000000.000100",
            "text": 'No notes match "why are orders timing out?".',
        }
    ]


def test_no_notes_query_escaped():
    job = make_job(question="<!channel> & <@U1>")
    _, _, transport = run([record(job)], Fakes(notes=[]))
    assert transport.posted(POST_MESSAGE_URL)[0]["text"] == (
        'No notes match "&lt;!channel&gt; &amp; &lt;@U1&gt;".'
    )


def test_answer_escaped():
    result = QaResult(answer="<!here> a & b", cited_note_ids=["n1"])
    _, _, transport = run([record(make_job())], Fakes(result=result))
    assert transport.posted(POST_MESSAGE_URL)[0]["text"] == (
        f"&lt;!here&gt; a &amp; b\n\nNotes:\n• {when()} in <#C1>"
    )


def test_notes_line_order_and_absent_when_no_ids():
    notes = [make_note("n1", "one"), make_note("n2", "two"), make_note("n3", "three")]
    w = when()
    assert reply_for(notes, ["n3", "n1", "n2"]) == (
        f"ok\n\nNotes:\n• {w} in <#C1>\n• {w} in <#C1>\n• {w} in <#C1>"
    )
    result = QaResult(answer="ok", cited_note_ids=[])
    _, _, transport = run([record(make_job())], Fakes(result=result))
    assert transport.posted(POST_MESSAGE_URL)[0]["text"] == (
        "ok\n\nSearched 1 note for \"why are orders timing out?\"; none cited."
    )


def test_uncited_answer_names_query_and_count():
    notes = [make_note("n1", "one"), make_note("n2", "two")]
    assert reply_for(notes, [], answer="The notes don't say.") == (
        "The notes don't say.\n\n"
        "Searched 2 notes for \"why are orders timing out?\"; none cited."
    )


def test_uncited_one_note_is_singular():
    text = reply_for([make_note()], [])
    assert text.endswith('Searched 1 note for "why are orders timing out?"; none cited.')
    assert "1 notes" not in text


def test_uncited_query_escaped():
    job = make_job(question="<!channel> & <@U1>")
    result = QaResult(answer="ok", cited_note_ids=[])
    _, _, transport = run([record(job)], Fakes(notes=[make_note()], result=result))
    assert transport.posted(POST_MESSAGE_URL)[0]["text"].endswith(
        'Searched 1 note for "&lt;!channel&gt; &amp; &lt;@U1&gt;"; none cited.'
    )


def test_uncited_answer_logged(caplog):
    notes = [make_note("n1", "one"), make_note("n2", "two")]
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        reply_for(notes, [])
    infos = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    matching = [m for m in infos if "answer cited no notes" in m]
    assert len(matching) == 1
    assert "event_id=Ev1" in matching[0]
    assert "notes=2" in matching[0]
    assert warnings(caplog) == []

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        reply_for(notes, ["n1"])
    assert not any("answer cited no notes" in r.getMessage() for r in caplog.records)


def info_messages(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]


def test_uncited_log_uses_job_event_id(caplog):
    notes = [make_note("n1", "one"), make_note("n2", "two")]
    result = QaResult(answer="ok", cited_note_ids=[])
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        run([record(make_job(event_id="Ev42"))], Fakes(notes=notes, result=result))
    matching = [m for m in info_messages(caplog) if "answer cited no notes" in m]
    assert len(matching) == 1
    assert "event_id=Ev42" in matching[0]
    assert "Ev1" not in matching[0]
    assert matching[0] == "answer cited no notes, event_id=Ev42 notes=2"


def test_question_answered_logged(caplog):
    notes = [make_note("n1", "one"), make_note("n2", "two")]
    result = QaResult(answer="ok", cited_note_ids=["n1"])
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        run([record(make_job(event_id="Ev42"))], Fakes(notes=notes, result=result))
    matching = [m for m in info_messages(caplog) if "question answered" in m]
    assert len(matching) == 1
    assert "event_id=Ev42" in matching[0]
    assert "notes=2" in matching[0]
    assert matching[0] == "question answered, event_id=Ev42 notes=2"


def test_question_answered_logged_when_no_notes(caplog):
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        run([record(make_job(event_id="Ev42"))], Fakes(notes=[]))
    matching = [m for m in info_messages(caplog) if "question answered" in m]
    assert len(matching) == 1
    assert "event_id=Ev42" in matching[0]
    assert "notes=0" in matching[0]
    assert matching[0] == "question answered, event_id=Ev42 notes=0"


def test_cited_answer_has_no_searched_line():
    assert "Searched" not in reply_for([make_note()], ["n1"])


def test_citation_shows_date_channel_and_severity():
    created = "2026-11-09T20:12:21.514Z"
    epoch = int(datetime(2026, 11, 9, 20, 12, 21, tzinfo=UTC).timestamp())
    note = make_note("n1", "short text", created, channel_id="C0ABC123")
    text = reply_for([note], ["n1"], severity_of=lambda note_id: "MEDIUM")
    assert text.endswith(
        f"\n\nNotes:\n• <!date^{epoch}^{{date_short_pretty}} {{time}}|2026-11-09 20:12 UTC>"
        " in <#C0ABC123> · MEDIUM"
    )


def test_note_text_not_in_reply():
    text = reply_for([make_note("n1", "SECRET-PHRASE-42")], ["n1"])
    assert "SECRET-PHRASE-42" not in text


@pytest.mark.parametrize("channel_id", ["C1>x", ""])
def test_odd_channel_id_is_left_out(channel_id):
    text = reply_for([make_note("n1", channel_id=channel_id)], ["n1"])
    assert text == f"ok\n\nNotes:\n• {when()}"
    assert " in " not in text


def test_unparseable_date_is_escaped():
    text = reply_for([make_note("n1", created_at="<!channel> & co")], ["n1"])
    assert text == "ok\n\nNotes:\n• &lt;!channel&gt; &amp; co in <#C1>"


def test_overflowing_date_falls_back():
    created = "0001-01-01T00:00:00+01:00"
    text = reply_for([make_note("n1", created_at=created)], ["n1"])
    assert text == f"ok\n\nNotes:\n• {created} in <#C1>"


def test_note_id_in_answer_is_replaced():
    notes = [make_note("n1", "one"), make_note("n2", "two")]
    text = reply_for(
        notes, ["n1"], answer="See n1 & <n2> and n10, xn1, n1_b; n1."
    )
    assert text == (
        "See a saved note &amp; &lt;a saved note&gt; and n10, xn1, n1_b; a saved note."
        f"\n\nNotes:\n• {when()} in <#C1>"
    )


def test_ungiven_id_left_alone():
    text = reply_for([make_note("n1")], ["n1"], answer="n9 and n1")
    assert text.startswith("n9 and a saved note\n\nNotes:")


def test_answer_kept_when_no_note_ids():
    result = QaResult(answer="a < b", cited_note_ids=[])
    assert thread._reply_text(result, []) == "a &lt; b"
    assert thread._reply_text(result, [make_note("")]) == "a &lt; b"


def test_longer_id_replaced_whole_when_shorter_id_is_its_prefix():
    notes = [make_note("n1", "one"), make_note("n1.x", "two")]
    text = reply_for(notes, [], answer="see n1.x and n1.")
    assert text == (
        "see a saved note and a saved note.\n\n"
        "Searched 2 notes for \"why are orders timing out?\"; none cited."
    )


def test_replaced_id_logged_once(caplog):
    notes = [make_note("n1", "one"), make_note("n2", "two")]
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        reply_for(notes, ["n1"], answer="n1 then n1 and n2")
    logged = [m for m in warnings(caplog) if "note id in answer" in m]
    assert len(logged) == 2
    assert sum("n1" in m for m in logged) == 1
    assert sum("n2" in m for m in logged) == 1
    assert len(warnings(caplog)) == 2

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        reply_for(notes, ["n1"], answer="no ids here")
    assert warnings(caplog) == []


def _raises(note_id):
    raise RuntimeError("lookup down")


@pytest.mark.parametrize("severity_of", [_raises, lambda note_id: None])
def test_severity_lookup_failure_still_answers(severity_of, caplog):
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        text = reply_for([make_note("n1")], ["n1"], severity_of=severity_of)
    assert text == f"ok\n\nNotes:\n• {when()} in <#C1>"
    assert " · " not in text
    logged = warnings(caplog)
    assert len(logged) == 1
    assert "n1" in logged[0]


def test_no_severity_of_means_no_severity_part(caplog):
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        text = reply_for([make_note("n1")], ["n1"])
    assert text == f"ok\n\nNotes:\n• {when()} in <#C1>"
    assert " · " not in text
    assert warnings(caplog) == []


def test_severity_lookup_reads_notes_table(notes_table):
    note_id = "b" * 32
    store.put_if_absent(
        notes_table,
        Note(note_id=note_id, team_id=TEAM, channel_id="C1", user_id="U1", text="x"),
    )
    store.set_severity(notes_table, note_id, Severity.HIGH)
    lookup = thread.severity_lookup(notes_table)
    assert lookup(note_id) == "HIGH"
    assert lookup("c" * 32) is None


def test_citation_accepts_plus_zero_offset():
    z = reply_for([make_note("n1", "t", "2026-11-09T20:12:21.514Z")], ["n1"])
    plus = reply_for([make_note("n1", "t", "2026-11-09T20:12:21.514+00:00")], ["n1"])
    assert z == plus
    assert "<!date^" in plus


def test_citation_without_offset_is_utc_whatever_local_zone(monkeypatch):
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    try:
        naive = reply_for([make_note("n1", "t", "2026-11-09T20:12:21.514")], ["n1"])
        z = reply_for([make_note("n1", "t", "2026-11-09T20:12:21.514Z")], ["n1"])
    finally:
        monkeypatch.undo()
        time.tzset()
    assert naive == z
    assert "|2026-11-09 20:12 UTC>" in naive


def test_citation_with_other_offset_is_converted_to_utc():
    z = reply_for([make_note("n1", "t", "2026-11-09T20:12:21.514Z")], ["n1"])
    plus2 = reply_for([make_note("n1", "t", "2026-11-09T22:12:21.514+02:00")], ["n1"])
    assert plus2 == z


def test_citations_keep_cited_order():
    notes = [
        make_note("n1", channel_id="C1"),
        make_note("n2", channel_id="C2"),
        make_note("n3", channel_id="C3"),
    ]
    lines = reply_for(notes, ["n3", "n1", "n2"]).split("\n• ")[1:]
    assert [line.split(" in ", 1)[1] for line in lines] == ["<#C3>", "<#C1>", "<#C2>"]


def test_unparseable_date_and_missing_note():
    notes = [make_note("n1", "alpha", "yesterday")]
    assert reply_for(notes, ["n1", "<n9>"]) == (
        "ok\n\nNotes:\n• yesterday in <#C1>\n• &lt;n9&gt;"
    )


def test_qa_error_posts_ephemeral_and_succeeds(caplog):
    fakes = Fakes(answer_exc=QaError("language model call failed"))
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        resp, _, transport = run([record(make_job(event_id="EvQA"))], fakes)
    assert resp == {"batchItemFailures": []}
    assert transport.posted(POST_MESSAGE_URL) == []
    assert transport.posted(POST_EPHEMERAL_URL) == [
        {
            "channel": "C1",
            "user": "U1",
            "thread_ts": "1700000000.000100",
            "text": "Sorry, I couldn't answer that. Please try again.",
        }
    ]
    assert any("EvQA" in w for w in warnings(caplog))


def test_answer_called_once_with_question_and_retrieved_notes():
    notes = [make_note("n2", "beta"), make_note("n1", "alpha")]
    job = make_job(question="which note?")
    _, fakes, _ = run([record(job)], Fakes(notes=notes))
    assert len(fakes.answer_calls) == 1
    question, passed = fakes.answer_calls[0]
    assert question == "which note?"
    assert passed is notes


def client_error():
    return ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"}}, "Converse")


@pytest.mark.parametrize(
    ("kind", "class_name"),
    [
        ("embed", "EmbedError"),
        ("botocore", "ClientError"),
        ("post_not_ok", "SlackApiError"),
        ("ephemeral_fails", "SlackApiError"),
    ],
)
def test_failures_are_batch_items(kind, class_name, caplog):
    fakes = Fakes()
    transport = FakeTransport()
    if kind == "embed":
        fakes = Fakes(retrieve_exc=EmbedError("x"))
    elif kind == "botocore":
        fakes = Fakes(answer_exc=client_error())
    elif kind == "post_not_ok":
        transport = FakeTransport({POST_MESSAGE_URL: {"ok": False, "error": "ratelimited"}})
    else:
        fakes = Fakes(answer_exc=QaError("x"))
        transport = FakeTransport({POST_EPHEMERAL_URL: {"ok": False, "error": "not_in_channel"}})
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        resp, _, _ = run([record(make_job(event_id="EvF"), "mF")], fakes, transport)
    assert resp == {"batchItemFailures": [{"itemIdentifier": "mF"}]}
    assert any(class_name in w and "EvF" in w for w in warnings(caplog))


@pytest.mark.parametrize("body", ["not json", json.dumps({"event_id": "Ev1"})])
def test_bad_body_is_batch_item(body, caplog):
    fakes = Fakes()
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        resp, fakes, transport = run([{"messageId": "mBad", "body": body}], fakes)
    assert resp == {"batchItemFailures": [{"itemIdentifier": "mBad"}]}
    assert fakes.retrieve_calls == []
    assert transport.calls == []
    assert any("mBad" in w for w in warnings(caplog))


def test_batch_continues_after_failure():
    first = make_job(event_id="Ev1", question="first?")
    second = make_job(event_id="Ev2", question="second?", channel="C2")

    class Flaky(Fakes):
        def retrieve(self, question, team_id):
            if question == "first?":
                raise EmbedError("x")
            return super().retrieve(question, team_id)

    resp, fakes, transport = run([record(first, "m1"), record(second, "m2")], Flaky())
    assert resp == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    assert [b["channel"] for b in transport.posted(POST_MESSAGE_URL)] == ["C2"]


def test_success_logs_event_id_and_count(caplog):
    notes = [make_note("n1"), make_note("n2"), make_note("n3")]
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        run([record(make_job(event_id="EvOK"))], Fakes(notes=notes))
    infos = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any("EvOK" in m and "notes=3" in m for m in infos)


def test_text_never_logged(caplog):
    question = f"{QUESTION_MARKER} what?"
    notes = [make_note("n1", f"text {NOTE_MARKER}")]
    result = QaResult(answer=f"{ANSWER_MARKER} yes", cited_note_ids=["n1"])
    scenarios = [
        Fakes(notes=notes, result=result),
        Fakes(notes=[]),
        Fakes(notes=notes, answer_exc=QaError(f"{ANSWER_MARKER} {NOTE_MARKER}")),
        Fakes(notes=notes, answer_exc=client_error()),
        Fakes(retrieve_exc=EmbedError(f"{QUESTION_MARKER}")),
    ]
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        for fakes in scenarios:
            run([record(make_job(question=question))], fakes)
        run(
            [record(make_job(question=question))],
            Fakes(notes=notes, result=result),
            FakeTransport({POST_MESSAGE_URL: {"ok": False, "error": "x"}}),
        )
    assert caplog.records
    text = caplog.text + " ".join(str(r.args) for r in caplog.records)
    for marker in (QUESTION_MARKER, ANSWER_MARKER, NOTE_MARKER):
        assert marker not in text


class _FakeSlackResponse:
    def read(self):
        return b'{"ok": true}'

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_slack_client_uses_10s_timeout(monkeypatch):
    seen = []

    def fake_urlopen(request, timeout=None):
        seen.append((request, timeout))
        return _FakeSlackResponse()

    monkeypatch.setattr("slackkb.slack_api.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setenv(
        "SLACKKB_CAPTURE_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/1/capture-test"
    )
    thread.slack_client(Settings()).chat_post_message("C1", "1700000000.000100", "hi")
    assert len(seen) == 1
    request, timeout = seen[0]
    assert timeout == 10.0
    assert thread.SLACK_TIMEOUT_SECONDS == 10.0
    assert request.get_header("Authorization") == "Bearer xoxb-test-token"


def test_slack_client_repr_hides_token(monkeypatch):
    monkeypatch.setenv(
        "SLACKKB_CAPTURE_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/1/capture-test"
    )
    client = thread.slack_client(Settings())
    assert isinstance(client, SlackClient)
    assert "xoxb-test-token" not in repr(client)
