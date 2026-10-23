import ast
import json
import logging
import time
from pathlib import Path

import boto3
import pytest
from conftest import BOT_TOKEN, SIGNING_SECRET
from pydantic import SecretStr

from slackkb import capture, modal
from slackkb.config import Settings
from slackkb.models import Note, NoteStatus, Severity, note_id
from slackkb.slack_api import SlackApiError, SlackClient
from slackkb.store import get_note, put_if_absent

SRC = Path(__file__).parent.parent / "src" / "slackkb"
NOTE_ID = note_id("T000TEST", "1111.2222.abcdef")
TRIGGER_ID = "3333.4444.fedcba"
NOTE_TEXT = "db connection timeouts on /api/orders since 14:05"
VIEWS_OPEN_URL = "https://slack.com/api/views.open"


@pytest.fixture(autouse=True)
def capture_queue_env(monkeypatch):
    monkeypatch.setenv("SLACKKB_CAPTURE_QUEUE_URL", "https://sqs.invalid/000000000000/q")


class FakeTransport:
    def __init__(self, reply=None, exc=None):
        self.calls = []
        self.reply = {"ok": True} if reply is None else reply
        self.exc = exc

    def __call__(self, url, headers, json_body):
        self.calls.append((url, headers, json_body))
        if self.exc is not None:
            raise self.exc
        return self.reply


def _slack(transport):
    return SlackClient(SecretStr(BOT_TOKEN), transport)


def _handle(event, table, transport=None):
    transport = FakeTransport() if transport is None else transport
    return modal.handle(
        event, table=table, slack=_slack(transport), settings=Settings(), now=int(time.time())
    )


def _capture(slack_request, table):
    return capture.handle(
        slack_request(),
        table=table,
        sqs=boto3.client("sqs"),
        settings=Settings(),
        now=int(time.time()),
    )


def _put_other_team_note(table, nid="b" * 32):
    note = Note(note_id=nid, team_id="T999OTHER", channel_id="C1", user_id="U1", text="secret")
    assert put_if_absent(table, note)
    return nid


def _errors(resp):
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["response_action"] == "errors"
    assert set(body["errors"]) == {"severity"}
    assert body["errors"]["severity"]
    return body


def test_modal_submission_updates_severity(
    slack_request, slack_interaction, notes_table, capture_queue
):
    _capture(slack_request, notes_table)
    before = get_note(notes_table, NOTE_ID)
    assert before.severity is Severity.LOW
    resp = _handle(slack_interaction("view_submission", severity="HIGH"), notes_table)
    assert resp["statusCode"] == 200
    assert resp["body"] == ""
    after = get_note(notes_table, NOTE_ID)
    assert after.severity is Severity.HIGH
    assert after.status is NoteStatus.CAPTURED
    assert after.text == NOTE_TEXT
    assert after == before.model_copy(update={"severity": Severity.HIGH})


@pytest.mark.parametrize("duplicate", [False, True])
def test_ack_has_set_severity_button(slack_request, notes_table, capture_queue, duplicate):
    resp = _capture(slack_request, notes_table)
    if duplicate:
        resp = _capture(slack_request, notes_table)
    body = json.loads(resp["body"])
    assert body["response_type"] == "ephemeral"
    assert body["text"] == capture.ACK_TEXT
    section, actions = body["blocks"]
    assert section["type"] == "section"
    assert section["text"]["text"] == capture.ACK_TEXT
    assert actions["type"] == "actions"
    assert actions["block_id"] == "note_actions"
    (button,) = actions["elements"]
    assert button["type"] == "button"
    assert button["action_id"] == "set_severity"
    assert button["value"] == NOTE_ID


def test_retry_message_has_no_button(slack_request, notes_table, capture_queue):
    class Failing:
        def send_message(self, **kwargs):
            raise RuntimeError("boom")

    from slackkb.queue import EnqueueError  # noqa: F401

    sqs = boto3.client("sqs")
    sqs.delete_queue(QueueUrl=capture_queue.url)
    resp = capture.handle(
        slack_request(), table=notes_table, sqs=sqs, settings=Settings(), now=int(time.time())
    )
    body = json.loads(resp["body"])
    assert body == {"response_type": "ephemeral", "text": capture.RETRY_TEXT}


def test_button_opens_modal_with_note_id(
    slack_request, slack_interaction, notes_table, capture_queue
):
    _capture(slack_request, notes_table)
    transport = FakeTransport()
    resp = _handle(slack_interaction("block_actions"), notes_table, transport)
    assert resp["statusCode"] == 200
    assert resp["body"] == ""
    (call,) = transport.calls
    url, headers, body = call
    assert url == VIEWS_OPEN_URL
    assert headers["Authorization"] == f"Bearer {BOT_TOKEN}"
    assert body["trigger_id"] == TRIGGER_ID
    view = body["view"]
    assert view["type"] == "modal"
    assert view["callback_id"] == "severity_modal"
    assert view["private_metadata"] == NOTE_ID
    (block,) = view["blocks"]
    assert block["type"] == "input"
    assert block["block_id"] == "severity"
    element = block["element"]
    assert element["type"] == "static_select"
    assert element["action_id"] == "severity_select"
    assert [o["value"] for o in element["options"]] == [s.value for s in Severity]
    assert element["initial_option"]["value"] == "LOW"


def test_button_initial_option_is_current_severity(
    slack_request, slack_interaction, notes_table, capture_queue
):
    _capture(slack_request, notes_table)
    _handle(slack_interaction("view_submission", severity="CRITICAL"), notes_table)
    transport = FakeTransport()
    _handle(slack_interaction("block_actions"), notes_table, transport)
    element = transport.calls[0][2]["view"]["blocks"][0]["element"]
    assert element["initial_option"]["value"] == "CRITICAL"


def test_button_for_missing_note_opens_nothing(slack_interaction, notes_table):
    transport = FakeTransport()
    resp = _handle(slack_interaction("block_actions"), notes_table, transport)
    assert resp["statusCode"] == 200
    assert resp["body"] == ""
    assert transport.calls == []


def test_other_action_id_opens_nothing(
    slack_interaction, slack_request, notes_table, capture_queue
):
    _capture(slack_request, notes_table)
    event = slack_interaction("block_actions")
    import urllib.parse

    from conftest import sign

    payload = json.loads(urllib.parse.parse_qs(event["body"])["payload"][0])
    payload["actions"][0]["action_id"] = "something_else"
    body = urllib.parse.urlencode({"payload": json.dumps(payload)})
    ts = int(time.time())
    event = {
        "headers": {"X-Slack-Request-Timestamp": str(ts), "X-Slack-Signature": sign(body, ts)},
        "body": body,
        "isBase64Encoded": False,
    }
    transport = FakeTransport()
    resp = _handle(event, notes_table, transport)
    assert resp["statusCode"] == 200
    assert resp["body"] == ""
    assert transport.calls == []


def test_unknown_severity_returns_errors(
    slack_request, slack_interaction, notes_table, capture_queue
):
    _capture(slack_request, notes_table)
    for bad in ("URGENT", "high", ""):
        resp = _handle(slack_interaction("view_submission", severity=bad), notes_table)
        _errors(resp)
    assert get_note(notes_table, NOTE_ID).severity is Severity.LOW


def test_submission_for_missing_note_returns_errors(slack_interaction, notes_table):
    resp = _handle(slack_interaction("view_submission", severity="HIGH"), notes_table)
    _errors(resp)
    assert notes_table.scan()["Count"] == 0


def test_other_team_cannot_set_severity(slack_interaction, notes_table):
    nid = _put_other_team_note(notes_table)
    transport = FakeTransport()
    resp = _handle(slack_interaction("block_actions", note_id=nid), notes_table, transport)
    assert resp["statusCode"] == 200
    assert resp["body"] == ""
    assert transport.calls == []

    resp = _handle(
        slack_interaction("view_submission", severity="CRITICAL", note_id=nid), notes_table
    )
    body = _errors(resp)
    assert get_note(notes_table, nid).severity is Severity.LOW
    # same message as a missing note: no probing of note ids
    missing = _errors(
        _handle(
            slack_interaction("view_submission", severity="CRITICAL", note_id="c" * 32),
            notes_table,
        )
    )
    assert body == missing


@pytest.mark.parametrize("kind", ["block_actions", "view_submission"])
def test_bad_signature_rejected(slack_request, slack_interaction, notes_table, capture_queue, kind):
    _capture(slack_request, notes_table)
    transport = FakeTransport()
    bad = _handle(slack_interaction(kind, severity="HIGH", secret="wrong"), notes_table, transport)
    assert bad["statusCode"] == 401
    stale = _handle(
        slack_interaction(kind, severity="HIGH", ts=int(time.time()) - 3600), notes_table, transport
    )
    assert stale["statusCode"] == 401
    assert transport.calls == []
    assert get_note(notes_table, NOTE_ID).severity is Severity.LOW


def _signed(body):
    from conftest import sign

    ts = int(time.time())
    return {
        "headers": {"X-Slack-Request-Timestamp": str(ts), "X-Slack-Signature": sign(body, ts)},
        "body": body,
        "isBase64Encoded": False,
    }


@pytest.mark.parametrize("body", ["foo=bar", "payload=not-json", "payload=%5B1%5D", ""])
def test_missing_or_invalid_payload_is_400(notes_table, body):
    assert _handle(_signed(body), notes_table)["statusCode"] == 400


def test_unknown_payload_type_rejected(notes_table):
    import urllib.parse

    for payload in (
        {"type": "view_closed", "team": {"id": "T000TEST"}},
        {"type": "shortcut"},
        {},
    ):
        body = urllib.parse.urlencode({"payload": json.dumps(payload)})
        assert _handle(_signed(body), notes_table)["statusCode"] == 400


def test_views_open_failure_is_logged_not_raised(
    slack_request, slack_interaction, notes_table, capture_queue, caplog
):
    _capture(slack_request, notes_table)
    failures = [
        FakeTransport(reply={"ok": False, "error": "expired_trigger_id"}),
        FakeTransport(exc=OSError("network down")),
    ]
    for transport in failures:
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            resp = _handle(slack_interaction("block_actions"), notes_table, transport)
        assert resp["statusCode"] == 200
        assert resp["body"] == ""
        assert len(transport.calls) == 1
        assert any(
            r.levelno == logging.WARNING and NOTE_ID in r.getMessage() for r in caplog.records
        )
        logged = caplog.text
        assert BOT_TOKEN not in logged
        assert SIGNING_SECRET not in logged
        assert NOTE_TEXT not in logged
        assert "hooks.slack.invalid" not in logged


def test_slack_client_raises_on_failure():
    client = _slack(FakeTransport(reply={"ok": False, "error": "invalid_auth"}))
    with pytest.raises(SlackApiError) as info:
        client.views_open("t", {"type": "modal"})
    assert BOT_TOKEN not in str(info.value)
    with pytest.raises(SlackApiError):
        _slack(FakeTransport(exc=OSError("x"))).views_open("t", {})
    assert BOT_TOKEN not in repr(client)


def _imported_modules(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


BANNED = (
    "boto3", "botocore", "aiobotocore", "requests", "httpx", "urllib3", "aiohttp",
    "http", "urllib.request", "socket", "slack_sdk", "slack_bolt",
)


@pytest.mark.parametrize("name", ["modal.py", "capture.py"])
def test_handlers_import_no_http_client(name):
    source = (SRC / name).read_text()
    modules = set(_imported_modules(ast.parse(source)))
    for module in modules:
        for banned in BANNED:
            assert module != banned and not module.startswith(banned + "."), module
    assert "response_url" not in source
    if name == "modal.py":
        assert {"slackkb.store", "slackkb.slack_verify"} <= modules
