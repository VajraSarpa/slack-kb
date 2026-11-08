import io
import json
import logging
import re
import time
import urllib.parse
from datetime import UTC, datetime

import boto3
import pytest
from pydantic import SecretStr

from slackkb import capture, events, modal, notify, obs, thread, worker
from slackkb.config import Settings
from slackkb.embed import DIMENSIONS, EmbedError
from slackkb.models import CaptureJob, Note, QuestionJob, note_id
from slackkb.okf_note import OkfNote
from slackkb.qa import QaResult
from slackkb.slack_api import SlackClient
from slackkb.store import get_note, put_if_absent

TEAM = "T000TEST"
NOTE_ID = note_id(TEAM, "1111.2222.abcdef")
OTHER_ID = "b" * 32
NOTE_TEXT = "db connection timeouts on /api/orders since 14:05"
RESPONSE_URL = "https://hooks.slack.invalid/commands/T000TEST/1/abc"
QUESTION = "how do we rotate the signing secret?"
RANDOM_ID = re.compile(r"^r-[0-9a-f]{16}$")
NOISY = ("botocore", "boto3", "urllib3")


@pytest.fixture(autouse=True)
def capture_queue_env(monkeypatch):
    monkeypatch.setenv("SLACKKB_CAPTURE_QUEUE_URL", "https://sqs.invalid/000000000000/q")


@pytest.fixture
def stream():
    root = logging.getLogger()
    saved = {name: logging.getLogger(name).level for name in (None, *NOISY)}
    buf = io.StringIO()
    handler = obs.configure(buf)
    yield buf
    root.removeHandler(handler)
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)


def _lines(buf):
    return [json.loads(line) for line in buf.getvalue().splitlines()]


def _from(buf, prefix):
    return [r for r in _lines(buf) if r["logger"].startswith(prefix)]


def _capture(event, table):
    return capture.handle(
        event, table=table, sqs=boto3.client("sqs"), settings=Settings(), now=int(time.time())
    )


def _modal(event, table):
    slack = SlackClient(SecretStr("xoxb-test"), lambda url, headers, body: {"ok": True})
    return modal.handle(event, table=table, slack=slack, settings=Settings(), now=int(time.time()))


def _events(event, table):
    return events.handle(
        event,
        events_table=table,
        sqs=boto3.client("sqs"),
        settings=Settings(),
        now=int(time.time()),
    )


def _put(table, nid):
    note = Note(note_id=nid, team_id=TEAM, channel_id="C1", user_id="U1", text=NOTE_TEXT)
    assert put_if_absent(table, note)


def _record(message_id, body):
    return {"messageId": message_id, "receiptHandle": "rh", "body": body}


def _job(nid):
    return CaptureJob(note_id=nid, response_url=RESPONSE_URL).model_dump_json()


def _worker(event, table, bucket, vectors):
    return worker.handle(
        event,
        table=table,
        bucket=bucket,
        vectors_table=vectors,
        embed=lambda text: [0.0] * DIMENSIONS,
    )


def _notify(event, table, bucket, vectors, post=None):
    return notify.handle(
        event,
        table=table,
        bucket=bucket,
        vectors_table=vectors,
        post=post or (lambda url, text: None),
    )


def _qjob(event_id):
    return QuestionJob(
        event_id=event_id,
        team_id=TEAM,
        channel="C1",
        user="U1",
        thread_ts="1700000000.000100",
        question=QUESTION,
    )


def _thread(records):
    slack = SlackClient(SecretStr("xoxb-test"), lambda url, headers, body: {"ok": True})
    note = OkfNote(
        note_id="n1",
        team_id=TEAM,
        channel_id="C1",
        user_id="U1",
        created_at="2026-11-07T00:00:00Z",
        text="alpha",
    )
    return thread.handle(
        {"Records": records},
        retrieve=lambda question, team_id: [note],
        answer=lambda question, notes: QaResult(answer="It was alpha.", cited_note_ids=["n1"]),
        slack=slack,
    )


def test_log_has_trace_id(stream, slack_request, notes_table, capture_queue):
    assert _capture(slack_request(), notes_table)["statusCode"] == 200
    (item,) = notes_table.scan()["Items"]
    stored = get_note(notes_table, item["note_id"])
    lines = _from(stream, "slackkb.capture")
    assert lines
    assert all(r["trace_id"] == stored.note_id for r in lines)


def test_trace_id_none_outside_trace():
    assert obs.trace_id() is None


def test_trace_random_restores_on_exit():
    with obs.trace():
        outer = obs.trace_id()
        assert RANDOM_ID.match(outer)
        with obs.trace():
            inner = obs.trace_id()
            assert RANDOM_ID.match(inner)
            assert inner != outer
        assert obs.trace_id() == outer
    assert obs.trace_id() is None
    with pytest.raises(RuntimeError):
        with obs.trace():
            raise RuntimeError("boom")
    assert obs.trace_id() is None


def test_bind_accepts_valid_and_ignores_invalid():
    with obs.trace():
        assert obs.bind("Ev123_ab-C") is None
        assert obs.trace_id() == "Ev123_ab-C"
        assert obs.bind("a" * 64) is None
        assert obs.trace_id() == "a" * 64
        for bad in (123, None, "", "a" * 65, "a b", "a\nb", "a/b"):
            assert obs.bind(bad) is None
            assert obs.trace_id() == "a" * 64


def test_configure_levels_and_single_handler():
    root = logging.getLogger()
    saved = {name: logging.getLogger(name).level for name in (None, *NOISY)}
    first = obs.configure(io.StringIO())
    second = obs.configure(io.StringIO())
    try:
        assert first is not second
        assert first not in root.handlers
        ours = [h for h in root.handlers if h.formatter is second.formatter]
        assert ours == [second]
        assert type(second.formatter).__module__ == obs.__name__
        assert sum(1 for h in root.handlers if type(h.formatter).__module__ == obs.__name__) == 1
        assert root.level == logging.INFO
        for name in NOISY:
            assert logging.getLogger(name).level == logging.WARNING
    finally:
        root.removeHandler(second)
        for name, level in saved.items():
            logging.getLogger(name).setLevel(level)


def test_json_line_exact_shape(stream):
    log = logging.getLogger("test_obs.shape")
    captured = []

    class Tap(logging.Handler):
        def emit(self, record):
            captured.append(record)

    tap = Tap()
    logging.getLogger().addHandler(tap)
    try:
        with obs.trace():
            obs.bind("abc")
            log.info("x %s", "y")
        log.info("outside")
    finally:
        logging.getLogger().removeHandler(tap)
    inside, outside = _lines(stream)
    assert set(inside) == {"ts", "level", "logger", "msg", "trace_id"}
    assert inside["msg"] == "x y"
    assert inside["level"] == "INFO"
    assert inside["logger"] == "test_obs.shape"
    assert inside["trace_id"] == "abc"
    assert re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$", inside["ts"])
    parsed = datetime.strptime(inside["ts"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    assert abs(parsed.timestamp() - captured[0].created) < 0.001 + 1e-6
    assert outside["trace_id"] is None
    assert len(stream.getvalue().splitlines()) == 2


def test_trace_id_taken_when_record_is_made(stream):
    (handler,) = [
        h for h in logging.getLogger().handlers if isinstance(h.formatter, obs.JsonFormatter)
    ]
    with obs.trace():
        obs.bind("made-here")
        record = logging.getLogger("test_obs.made").makeRecord(
            "test_obs.made", logging.INFO, __file__, 1, "m", (), None
        )
    with obs.trace():
        obs.bind("formatted-here")
        line = json.loads(handler.format(record))
    assert line["trace_id"] == "made-here"


def test_exc_is_class_name_only(stream):
    logging.getLogger("test_obs.exc").warning("w", exc_info=ValueError("hidden-detail"))
    (line,) = _lines(stream)
    assert line["exc"] == "ValueError"
    assert "hidden-detail" not in stream.getvalue()
    assert "Traceback" not in stream.getvalue()


def test_rejected_request_has_random_trace(stream, slack_request, notes_table, capture_queue):
    assert _capture(slack_request(secret="wrong"), notes_table)["statusCode"] == 401
    lines = _from(stream, "slackkb.capture")
    assert lines
    assert all(RANDOM_ID.match(r["trace_id"]) for r in lines)


def test_modal_lines_carry_note_id(stream, slack_interaction, notes_table):
    _put(notes_table, NOTE_ID)
    _modal(slack_interaction("block_actions", note_id=NOTE_ID), notes_table)
    first = _from(stream, "slackkb.modal")
    assert first
    assert all(r["trace_id"] == NOTE_ID for r in first)
    stream.truncate(0)
    stream.seek(0)
    _modal(slack_interaction("view_submission", severity="HIGH", note_id=NOTE_ID), notes_table)
    second = _from(stream, "slackkb.modal")
    assert second
    assert all(r["trace_id"] == NOTE_ID for r in second)
    stream.truncate(0)
    stream.seek(0)
    _modal(slack_interaction("block_actions", note_id="../x y"), notes_table)
    third = _from(stream, "slackkb.modal")
    assert third
    assert all(RANDOM_ID.match(r["trace_id"]) for r in third)


def test_events_lines_carry_event_id(stream, slack_event, events_table, question_queue):
    event = slack_event(event_id="EvTrace1")
    assert _events(event, events_table)["statusCode"] == 200
    lines = _from(stream, "slackkb.events")
    assert lines
    assert all(r["trace_id"] == "EvTrace1" for r in lines)


def test_worker_records_get_their_own_trace(stream, notes_table, notes_bucket, vectors_table):
    _put(notes_table, NOTE_ID)
    _put(notes_table, OTHER_ID)
    event = {
        "Records": [
            _record("m1", _job(NOTE_ID)),
            _record("m2", "not json"),
            _record("m3", _job(OTHER_ID)),
        ]
    }
    _worker(event, notes_table, notes_bucket, vectors_table)
    lines = _from(stream, "slackkb.worker")
    by_message = {}
    for r in lines:
        mid = re.search(r"message_id=(\w+)", r["msg"]).group(1)
        by_message.setdefault(mid, []).append(r["trace_id"])
    assert set(by_message) == {"m1", "m2", "m3"}
    assert set(by_message["m1"]) == {NOTE_ID}
    assert set(by_message["m3"]) == {OTHER_ID}
    assert all(RANDOM_ID.match(t) for t in by_message["m2"])


def test_notify_lines_carry_note_id(stream, notes_table, notes_bucket, vectors_table):
    _put(notes_table, NOTE_ID)
    posts = []
    _notify(
        {"Records": [_record("m1", _job(NOTE_ID))]},
        notes_table,
        notes_bucket,
        vectors_table,
        post=lambda url, text: posts.append((url, text)),
    )
    assert posts
    lines = _from(stream, "slackkb.notify")
    assert lines
    assert all(r["trace_id"] == NOTE_ID for r in lines)


def test_notify_records_get_their_own_trace(stream, notes_table, notes_bucket, vectors_table):
    _put(notes_table, NOTE_ID)
    _put(notes_table, OTHER_ID)
    seen = []
    event = {
        "Records": [
            _record("m1", _job(NOTE_ID)),
            _record("m2", "not json"),
            _record("m3", _job(OTHER_ID)),
        ]
    }
    _notify(
        event,
        notes_table,
        notes_bucket,
        vectors_table,
        post=lambda url, text: seen.append(obs.trace_id()),
    )
    assert seen == [NOTE_ID, OTHER_ID]
    by_message = {}
    for r in _from(stream, "slackkb.notify"):
        mid = re.search(r"message_id=(\w+)", r["msg"]).group(1)
        by_message.setdefault(mid, []).append(r["trace_id"])
    assert set(by_message) == {"m1", "m2", "m3"}
    assert set(by_message["m1"]) == {NOTE_ID}
    assert set(by_message["m3"]) == {OTHER_ID}
    (random_id,) = by_message["m2"]
    assert RANDOM_ID.match(random_id)
    assert obs.trace_id() is None


def test_thread_lines_carry_event_id(stream):
    records = [
        _record("m1", _qjob("EvOne").model_dump_json()),
        _record("m2", _qjob("EvTwo").model_dump_json()),
    ]
    assert _thread(records) == {"batchItemFailures": []}
    lines = _from(stream, "slackkb.thread")
    for event_id in ("EvOne", "EvTwo"):
        mine = [r for r in lines if f"event_id={event_id}" in r["msg"]]
        assert mine
        assert all(r["trace_id"] == event_id for r in mine)
    assert {r["trace_id"] for r in lines} == {"EvOne", "EvTwo"}


def test_thread_records_get_their_own_trace(stream):
    seen = []
    slack = SlackClient(
        SecretStr("xoxb-test"),
        lambda url, headers, body: seen.append(("post", obs.trace_id())) or {"ok": True},
    )

    def retrieve(question, team_id):
        seen.append(("retrieve", obs.trace_id()))
        return []

    records = [
        _record("m1", _qjob("EvOne").model_dump_json()),
        _record("m2", "not json"),
        _record("m3", _qjob("EvTwo").model_dump_json()),
    ]
    thread.handle(
        {"Records": records},
        retrieve=retrieve,
        answer=lambda question, notes: QaResult(answer="unused", cited_note_ids=[]),
        slack=slack,
    )
    retrieved = [t for kind, t in seen if kind == "retrieve"]
    assert retrieved == ["EvOne", "EvTwo"]
    assert {t for _, t in seen} == {"EvOne", "EvTwo"}
    (unparsable,) = [r for r in _from(stream, "slackkb.thread") if "message_id=m2" in r["msg"]]
    assert RANDOM_ID.match(unparsable["trace_id"])
    assert obs.trace_id() is None


def test_trace_cleared_after_handlers(
    slack_request,
    slack_interaction,
    slack_event,
    notes_table,
    notes_bucket,
    vectors_table,
    events_table,
    capture_queue,
    question_queue,
):
    _capture(slack_request(), notes_table)
    assert obs.trace_id() is None
    _modal(slack_interaction("block_actions"), notes_table)
    assert obs.trace_id() is None
    _events(slack_event(), events_table)
    assert obs.trace_id() is None
    event = {"Records": [_record("m1", _job(NOTE_ID))]}
    _worker(event, notes_table, notes_bucket, vectors_table)
    assert obs.trace_id() is None
    _notify(event, notes_table, notes_bucket, vectors_table)
    assert obs.trace_id() is None
    _thread([_record("m1", _qjob("EvOne").model_dump_json())])
    assert obs.trace_id() is None
    with pytest.raises(KeyError):
        _worker({"Records": [{"body": _job(NOTE_ID)}]}, notes_table, notes_bucket, vectors_table)
    assert obs.trace_id() is None


def test_json_lines_never_carry_text_or_url(
    stream,
    slack_request,
    slack_event,
    notes_table,
    notes_bucket,
    vectors_table,
    events_table,
    capture_queue,
    question_queue,
):
    request = slack_request(text=NOTE_TEXT)
    sent = urllib.parse.parse_qs(request["body"])
    (sent_text,) = sent["text"]
    (sent_url,) = sent["response_url"]
    assert sent_text == NOTE_TEXT
    assert _capture(request, notes_table)["statusCode"] == 200
    (item,) = notes_table.scan()["Items"]
    assert item["text"] == sent_text

    sqs = boto3.client("sqs")
    (msg,) = sqs.receive_message(QueueUrl=capture_queue.url)["Messages"]
    job = CaptureJob.model_validate_json(msg["Body"])
    assert job.response_url == sent_url
    event = {"Records": [_record("m1", msg["Body"]), _record("m2", "not json")]}
    _worker(event, notes_table, notes_bucket, vectors_table)
    _put(notes_table, OTHER_ID)
    other_job = job.model_copy(update={"note_id": OTHER_ID}).model_dump_json()
    failing = {"Records": [_record("m3", other_job)]}

    def embed_fails(text):
        raise EmbedError("embed down")

    worker.handle(
        failing,
        table=notes_table,
        bucket=notes_bucket,
        vectors_table=vectors_table,
        embed=embed_fails,
    )
    event["Records"].append(failing["Records"][0])
    posted = []
    _notify(
        event,
        notes_table,
        notes_bucket,
        vectors_table,
        post=lambda url, text: posted.append(url),
    )
    assert posted == [sent_url]

    assert _events(slack_event(text=f"<@U1> {QUESTION}"), events_table)["statusCode"] == 200
    (qmsg,) = sqs.receive_message(QueueUrl=question_queue.url)["Messages"]
    assert QuestionJob.model_validate_json(qmsg["Body"]).question == QUESTION
    _thread([_record("q1", qmsg["Body"])])

    out = stream.getvalue()
    assert out
    for secret in (sent_text, QUESTION, sent_url):
        assert secret not in out
