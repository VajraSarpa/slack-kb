import base64
import json
import logging
import time

import boto3
import pytest
from botocore.exceptions import ClientError
from conftest import SIGNING_SECRET

from slackkb import events
from slackkb.config import Settings
from slackkb.events import handle

EXPECTED_JOB = {
    "event_id": "Ev000TEST0001",
    "team_id": "T000TEST",
    "channel": "C000TEST",
    "user": "U000TEST",
    "thread_ts": "1762600000.000100",
    "question": "how do we rotate the signing secret?",
}


@pytest.fixture(autouse=True)
def capture_queue_env(monkeypatch):
    monkeypatch.setenv("SLACKKB_CAPTURE_QUEUE_URL", "https://example.invalid/capture")


class FailingSqs:
    def send_message(self, **kwargs):
        raise ClientError({"Error": {"Code": "ServiceUnavailable", "Message": "x"}}, "SendMessage")


def _handle(event, events_table, sqs=None, now=None):
    now = int(time.time()) if now is None else now
    sqs = boto3.client("sqs") if sqs is None else sqs
    return handle(event, events_table=events_table, sqs=sqs, settings=Settings(), now=now)


def _messages(queue):
    sqs = boto3.client("sqs")
    out = []
    while True:
        got = sqs.receive_message(QueueUrl=queue.url, MaxNumberOfMessages=10).get("Messages", [])
        if not got:
            return out
        out.extend(got)
        for m in got:
            sqs.delete_message(QueueUrl=queue.url, ReceiptHandle=m["ReceiptHandle"])


def _claims(table):
    return table.scan()["Items"]


def _nothing_done(resp, status, table, queue):
    assert resp["statusCode"] == status
    assert _claims(table) == []
    assert _messages(queue) == []


def test_retry_is_deduplicated(slack_event, events_table, question_queue, caplog):
    first = _handle(slack_event(), events_table)
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="slackkb"):
        second = _handle(slack_event(retry=1), events_table)
    assert first["statusCode"] == 200
    assert second["statusCode"] == 200
    assert len(_messages(question_queue)) == 1
    infos = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any("Ev000TEST0001" in m and "duplicate" in m for m in infos)


def test_enqueue_failure_releases_claim_and_retry_recovers(
    slack_event, events_table, question_queue
):
    first = _handle(slack_event(), events_table, sqs=FailingSqs())
    assert first["statusCode"] == 500
    assert _claims(events_table) == []
    retry = _handle(slack_event(retry=1), events_table)
    assert retry["statusCode"] == 200
    assert len(_messages(question_queue)) == 1


def test_release_failure_still_500_and_logged(
    slack_event, events_table, question_queue, monkeypatch, caplog
):
    def boom(table, event_id):
        raise events.DedupError("ClientError")

    monkeypatch.setattr(events, "release", boom)
    with caplog.at_level(logging.WARNING, logger="slackkb"):
        resp = _handle(slack_event(), events_table, sqs=FailingSqs())
    assert resp["statusCode"] == 500
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("Ev000TEST0001" in w and "release" in w.lower() for w in warnings)


def test_claim_failure_returns_500_sends_nothing(
    slack_event, events_table, question_queue, monkeypatch
):
    def boom(table, event_id, now):
        raise events.DedupError("ClientError")

    monkeypatch.setattr(events, "claim", boom)
    resp = _handle(slack_event(), events_table)
    _nothing_done(resp, 500, events_table, question_queue)


def test_job_body_exact(slack_event, events_table, question_queue):
    _handle(slack_event(), events_table)
    messages = _messages(question_queue)
    assert [json.loads(m["Body"]) for m in messages] == [EXPECTED_JOB]


def test_top_level_mention_uses_ts(slack_event, events_table, question_queue):
    resp = _handle(slack_event(thread_ts=None), events_table)
    assert resp["statusCode"] == 200
    (message,) = _messages(question_queue)
    assert json.loads(message["Body"]) == {**EXPECTED_JOB, "thread_ts": "1762600000.000200"}


def test_mention_tokens_removed(slack_event, events_table, question_queue):
    text = "<@U0BOTTEST> hey <@U0OTHER1|alice> how <@U0BOTTEST|bot>  do we deploy?"
    _handle(slack_event(text=text), events_table)
    (message,) = _messages(question_queue)
    question = json.loads(message["Body"])["question"]
    assert "<@" not in question
    assert question.split() == ["hey", "how", "do", "we", "deploy?"]
    assert question == question.strip()


def test_empty_question_does_nothing(slack_event, events_table, question_queue):
    for text in ("<@U0BOTTEST>", "  <@U0BOTTEST|bot>  <@U0X>  "):
        resp = _handle(slack_event(text=text), events_table)
        _nothing_done(resp, 200, events_table, question_queue)


@pytest.mark.parametrize("extra", [{"bot_id": "B000TEST"}, {"subtype": "bot_message"}])
def test_bot_and_subtype_events_ignored(slack_event, events_table, question_queue, extra):
    resp = _handle(slack_event(**extra), events_table)
    _nothing_done(resp, 200, events_table, question_queue)


FIELD_PATHS = [
    ["event_id"],
    ["team_id"],
    ["event", "channel"],
    ["event", "user"],
    ["event", "ts"],
    ["event", "text"],
]


def _signed(slack_event, payload):
    return slack_event(body=json.dumps(payload))


@pytest.mark.parametrize("path", FIELD_PATHS, ids=lambda p: ".".join(p))
@pytest.mark.parametrize("mode", ["missing", "empty", "not_string"])
def test_missing_fields_400(slack_event, events_table, question_queue, path, mode):
    payload = json.loads(slack_event()["body"])
    target = payload
    for key in path[:-1]:
        target = target[key]
    if mode == "missing":
        target.pop(path[-1])
    elif mode == "empty":
        target[path[-1]] = ""
    else:
        target[path[-1]] = 123
    resp = _handle(_signed(slack_event, payload), events_table)
    _nothing_done(resp, 400, events_table, question_queue)


def test_bad_signature_401_before_parse(slack_event, events_table, question_queue, caplog):
    now = int(time.time())
    cases = [
        (slack_event(body="not json", secret="wrong-secret"), "signature mismatch"),
        (slack_event(secret="wrong-secret"), "signature mismatch"),
        (slack_event(ts=now - 3600), "timestamp outside allowed window"),
    ]
    for event, reason in cases:
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="slackkb"):
            resp = _handle(event, events_table, now=now)
        _nothing_done(resp, 401, events_table, question_queue)
        assert resp["body"] == "unauthorized"
        assert SIGNING_SECRET not in resp["body"]
        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any(reason in w for w in warnings)


def test_bad_base64_body_401(slack_event, events_table, question_queue, caplog):
    event = slack_event()
    event["isBase64Encoded"] = True
    event["body"] = "!!!not base64!!!"
    with caplog.at_level(logging.WARNING, logger="slackkb"):
        resp = _handle(event, events_table)
    _nothing_done(resp, 401, events_table, question_queue)
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("encoding" in w for w in warnings)


def test_base64_body_is_verified_and_handled(slack_event, events_table, question_queue):
    event = slack_event()
    event["body"] = base64.b64encode(event["body"].encode()).decode()
    event["isBase64Encoded"] = True
    assert _handle(event, events_table)["statusCode"] == 200
    assert len(_messages(question_queue)) == 1


@pytest.mark.parametrize("body", ["not json", "[1, 2]", '"text"', "null"])
def test_not_json_object_400(slack_event, events_table, question_queue, body):
    resp = _handle(slack_event(body=body), events_table)
    _nothing_done(resp, 400, events_table, question_queue)


def test_url_verification_returns_challenge(slack_event, events_table, question_queue):
    resp = _handle(slack_event("url_verification"), events_table)
    payload = json.loads(slack_event("url_verification")["body"])
    assert resp["statusCode"] == 200
    assert resp["body"] == payload["challenge"]
    assert resp["headers"]["Content-Type"] == "text/plain"
    assert _claims(events_table) == []
    assert _messages(question_queue) == []


def test_url_verification_needs_signature(slack_event, events_table, question_queue):
    resp = _handle(slack_event("url_verification", secret="wrong-secret"), events_table)
    assert resp["statusCode"] == 401
    payload = json.loads(slack_event("url_verification")["body"])
    assert payload["challenge"] not in resp["body"]


@pytest.mark.parametrize("challenge", [None, 123, ["x"]])
def test_url_verification_bad_challenge_400(slack_event, events_table, question_queue, challenge):
    payload = json.loads(slack_event("url_verification")["body"])
    if challenge is None:
        payload.pop("challenge")
    else:
        payload["challenge"] = challenge
    resp = _handle(_signed(slack_event, payload), events_table)
    assert resp["statusCode"] == 400


def test_other_events_ignored(slack_event, events_table, question_queue):
    payload = json.loads(slack_event()["body"])
    payload["event"]["type"] = "message"
    resp = _handle(_signed(slack_event, payload), events_table)
    _nothing_done(resp, 200, events_table, question_queue)

    payload = json.loads(slack_event()["body"])
    payload["type"] = "app_rate_limited"
    resp = _handle(_signed(slack_event, payload), events_table)
    _nothing_done(resp, 200, events_table, question_queue)


def test_question_never_logged(slack_event, events_table, question_queue, monkeypatch, caplog):
    text = "<@U0BOTTEST> please explain zebra-pangolin-quux"
    secret_words = ("zebra-pangolin-quux", text)

    def run():
        _handle(slack_event(text=text, event_id="EvA"), events_table)  # success
        _handle(slack_event(text=text, event_id="EvA", retry=1), events_table)  # duplicate
        _handle(slack_event(text=text, event_id="EvB"), events_table, sqs=FailingSqs())
        real_release = events.release

        def boom(table, event_id):
            raise events.DedupError("ClientError")

        monkeypatch.setattr(events, "release", boom)
        _handle(slack_event(text=text, event_id="EvC"), events_table, sqs=FailingSqs())
        monkeypatch.setattr(events, "release", real_release)

    with caplog.at_level(logging.DEBUG, logger="slackkb"):
        run()
    assert caplog.records
    for record in caplog.records:
        rendered = record.getMessage() + " " + str(record.exc_info)
        for word in secret_words:
            assert word not in rendered
    assert any("EvA" in r.getMessage() for r in caplog.records)
