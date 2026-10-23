diff --git a/src/slackkb/capture.py b/src/slackkb/capture.py
index b5576a3..a6e411f 100644
--- a/src/slackkb/capture.py
+++ b/src/slackkb/capture.py
@@ -36,6 +36,27 @@ def _ephemeral(text: str) -> dict[str, Any]:
     return _response(200, body, "application/json")
 
 
+def _ack(note_id: str) -> dict[str, Any]:
+    """The ack: same text, plus a section and a "Set severity" button (D-013)."""
+    blocks = [
+        {"type": "section", "text": {"type": "mrkdwn", "text": ACK_TEXT}},
+        {
+            "type": "actions",
+            "block_id": "note_actions",
+            "elements": [
+                {
+                    "type": "button",
+                    "action_id": "set_severity",
+                    "text": {"type": "plain_text", "text": "Set severity"},
+                    "value": note_id,
+                }
+            ],
+        },
+    ]
+    body = json.dumps({"response_type": "ephemeral", "text": ACK_TEXT, "blocks": blocks})
+    return _response(200, body, "application/json")
+
+
 def _raw_body(event: Mapping[str, Any]) -> str:
     body = event.get("body") or ""
     if event.get("isBase64Encoded"):
@@ -71,10 +92,10 @@ def handle(
         text=request.text,
     )
     if not put_if_absent(table, note):
-        return _ephemeral(ACK_TEXT)
+        return _ack(note.note_id)
     try:
         send_capture_job(sqs, settings.capture_queue_url, CaptureJob(note_id=note.note_id))
     except EnqueueError as exc:
         logger.warning("enqueue failed (%s), note_id=%s", exc, note.note_id)
         return _ephemeral(RETRY_TEXT)
-    return _ephemeral(ACK_TEXT)
+    return _ack(note.note_id)
diff --git a/src/slackkb/config.py b/src/slackkb/config.py
index a9346d9..920c52f 100644
--- a/src/slackkb/config.py
+++ b/src/slackkb/config.py
@@ -14,3 +14,4 @@ class Settings(BaseSettings):
     signing_secret: SecretStr
     notes_table: str
     capture_queue_url: str
+    slack_bot_token: SecretStr
diff --git a/src/slackkb/modal.py b/src/slackkb/modal.py
new file mode 100644
index 0000000..8728839
--- /dev/null
+++ b/src/slackkb/modal.py
@@ -0,0 +1,155 @@
+"""Severity modal: block_actions (open the modal) and view_submission (set severity).
+
+D-013. All DynamoDB access goes through store.py and all Slack Web API calls through
+slack_api.py. Never logs note text, secrets, or Slack callback URLs.
+"""
+
+import base64
+import binascii
+import json
+import logging
+import urllib.parse
+from collections.abc import Mapping
+from typing import Any
+
+from slackkb.config import Settings
+from slackkb.models import Severity
+from slackkb.slack_api import SlackApiError, SlackClient
+from slackkb.slack_verify import SignatureError, verify
+from slackkb.store import NoteNotFoundError, get_note, set_severity
+
+logger = logging.getLogger(__name__)
+
+ACTION_ID = "set_severity"
+CALLBACK_ID = "severity_modal"
+BLOCK_ID = "severity"
+SELECT_ACTION_ID = "severity_select"
+NOT_FOUND_TEXT = "That note could not be found."
+BAD_SEVERITY_TEXT = "Choose one of: " + ", ".join(s.value for s in Severity) + "."
+
+
+def _response(status: int, body: str, content_type: str = "text/plain") -> dict[str, Any]:
+    return {"statusCode": status, "headers": {"Content-Type": content_type}, "body": body}
+
+
+def _empty() -> dict[str, Any]:
+    return _response(200, "")
+
+
+def _errors(message: str) -> dict[str, Any]:
+    body = json.dumps({"response_action": "errors", "errors": {BLOCK_ID: message}})
+    return _response(200, body, "application/json")
+
+
+def _raw_body(event: Mapping[str, Any]) -> str:
+    body = event.get("body") or ""
+    if event.get("isBase64Encoded"):
+        return base64.b64decode(body, validate=True).decode()
+    return body
+
+
+def _get(obj: Any, *path: str) -> Any:
+    for key in path:
+        if not isinstance(obj, Mapping):
+            return None
+        obj = obj.get(key)
+    return obj
+
+
+def _view(note_id: str, current: Severity) -> dict[str, Any]:
+    options = [
+        {"text": {"type": "plain_text", "text": s.value}, "value": s.value} for s in Severity
+    ]
+    initial = {"text": {"type": "plain_text", "text": current.value}, "value": current.value}
+    return {
+        "type": "modal",
+        "callback_id": CALLBACK_ID,
+        "private_metadata": note_id,
+        "title": {"type": "plain_text", "text": "Set severity"},
+        "submit": {"type": "plain_text", "text": "Save"},
+        "close": {"type": "plain_text", "text": "Cancel"},
+        "blocks": [
+            {
+                "type": "input",
+                "block_id": BLOCK_ID,
+                "label": {"type": "plain_text", "text": "Severity"},
+                "element": {
+                    "type": "static_select",
+                    "action_id": SELECT_ACTION_ID,
+                    "options": options,
+                    "initial_option": initial,
+                },
+            }
+        ],
+    }
+
+
+def _block_actions(payload: Mapping[str, Any], table: Any, slack: SlackClient) -> dict[str, Any]:
+    actions = payload.get("actions")
+    action = actions[0] if isinstance(actions, list) and actions else None
+    if _get(action, "action_id") != ACTION_ID:
+        return _empty()
+    note_id = _get(action, "value")
+    trigger_id = payload.get("trigger_id")
+    team_id = _get(payload, "team", "id")
+    if not isinstance(note_id, str) or not isinstance(trigger_id, str) or not note_id:
+        return _empty()
+    note = get_note(table, note_id)
+    if note is None or team_id is None or note.team_id != team_id:
+        return _empty()
+    try:
+        slack.views_open(trigger_id, _view(note.note_id, note.severity))
+    except SlackApiError as exc:
+        logger.warning("views.open failed (%s), note_id=%s", exc, note.note_id)
+    return _empty()
+
+
+def _view_submission(payload: Mapping[str, Any], table: Any) -> dict[str, Any]:
+    if _get(payload, "view", "callback_id") != CALLBACK_ID:
+        return _response(400, "bad request")
+    note_id = _get(payload, "view", "private_metadata")
+    value = _get(
+        payload, "view", "state", "values", BLOCK_ID, SELECT_ACTION_ID, "selected_option", "value"
+    )
+    try:
+        severity = Severity(value)
+    except ValueError:
+        return _errors(BAD_SEVERITY_TEXT)
+    if not isinstance(note_id, str) or not note_id:
+        return _errors(NOT_FOUND_TEXT)
+    note = get_note(table, note_id)
+    team_id = _get(payload, "team", "id")
+    if note is None or team_id is None or note.team_id != team_id:
+        return _errors(NOT_FOUND_TEXT)
+    try:
+        set_severity(table, note_id, severity)
+    except NoteNotFoundError:
+        return _errors(NOT_FOUND_TEXT)
+    return _empty()
+
+
+def handle(
+    event: Mapping[str, Any], *, table: Any, slack: SlackClient, settings: Settings, now: int
+) -> dict:
+    """Handle one API Gateway proxy event for Slack interactivity and return the response."""
+    headers = event.get("headers") or {}
+    try:
+        body = _raw_body(event)
+        verify(headers, body, settings.signing_secret.get_secret_value(), now)
+    except (SignatureError, binascii.Error, UnicodeDecodeError):
+        return _response(401, "unauthorized")
+
+    fields = dict(urllib.parse.parse_qsl(body, keep_blank_values=True))
+    try:
+        payload = json.loads(fields["payload"])
+    except (KeyError, ValueError):
+        return _response(400, "bad request")
+    if not isinstance(payload, dict):
+        return _response(400, "bad request")
+
+    kind = payload.get("type")
+    if kind == "block_actions":
+        return _block_actions(payload, table, slack)
+    if kind == "view_submission":
+        return _view_submission(payload, table)
+    return _response(400, "bad request")
diff --git a/src/slackkb/slack_api.py b/src/slackkb/slack_api.py
new file mode 100644
index 0000000..c9b25b2
--- /dev/null
+++ b/src/slackkb/slack_api.py
@@ -0,0 +1,59 @@
+"""Slack Web API client. The only module that calls the Slack Web API.
+
+The transport is injected: a callable (url, headers, json_body) -> dict. Tests pass a
+fake; `urllib_transport` is the default for real use. The bot token is never logged
+and never appears in exception messages or reprs.
+"""
+
+import json
+import urllib.request
+from collections.abc import Callable, Mapping
+from typing import Any
+
+from pydantic import SecretStr
+
+VIEWS_OPEN_URL = "https://slack.com/api/views.open"
+DEFAULT_TIMEOUT_SECONDS = 2.5
+
+Transport = Callable[[str, Mapping[str, str], Mapping[str, Any]], dict]
+
+
+class SlackApiError(Exception):
+    """A Slack Web API call failed. Messages never carry the token."""
+
+
+def urllib_transport(url: str, headers: Mapping[str, str], json_body: Mapping[str, Any]) -> dict:
+    """POST json_body as JSON and return the decoded JSON reply."""
+    if not url.startswith("https://"):
+        raise ValueError("only https URLs are allowed")
+    request = urllib.request.Request(  # noqa: S310
+        url,
+        data=json.dumps(json_body).encode(),
+        headers={"Content-Type": "application/json; charset=utf-8", **headers},
+        method="POST",
+    )
+    with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as resp:  # noqa: S310
+        return json.loads(resp.read().decode())
+
+
+class SlackClient:
+    def __init__(self, token: SecretStr, transport: Transport = urllib_transport) -> None:
+        self._token = token
+        self._transport = transport
+
+    def __repr__(self) -> str:
+        return "SlackClient(token=**********)"
+
+    def _call(self, url: str, body: Mapping[str, Any]) -> None:
+        headers = {"Authorization": f"Bearer {self._token.get_secret_value()}"}
+        try:
+            reply = self._transport(url, headers, body)
+        except Exception as exc:
+            raise SlackApiError(f"transport failed: {type(exc).__name__}") from None
+        if not isinstance(reply, Mapping) or reply.get("ok") is not True:
+            error = reply.get("error") if isinstance(reply, Mapping) else None
+            raise SlackApiError(f"slack error: {error if isinstance(error, str) else 'unknown'}")
+
+    def views_open(self, trigger_id: str, view: Mapping[str, Any]) -> None:
+        """Open a modal. Raises SlackApiError if Slack rejects it or the call fails."""
+        self._call(VIEWS_OPEN_URL, {"trigger_id": trigger_id, "view": view})
diff --git a/src/slackkb/store.py b/src/slackkb/store.py
index 3415ee0..52e0ca8 100644
--- a/src/slackkb/store.py
+++ b/src/slackkb/store.py
@@ -7,7 +7,7 @@ from typing import Any
 
 from botocore.exceptions import ClientError
 
-from slackkb.models import Note, NoteStatus
+from slackkb.models import Note, NoteStatus, Severity
 
 
 def put_if_absent(table: Any, note: Note) -> bool:
@@ -64,3 +64,21 @@ def transition_status(
             raise NoteNotFoundError(note_id) from None
         return False
     return True
+
+
+def set_severity(table: Any, note_id: str, severity: Severity) -> None:
+    """Set the note's severity only; status and every other attribute are untouched (D-009).
+
+    Raises NoteNotFoundError if there is no such note.
+    """
+    try:
+        table.update_item(
+            Key={"note_id": note_id},
+            UpdateExpression="SET severity = :severity",
+            ConditionExpression="attribute_exists(note_id)",
+            ExpressionAttributeValues={":severity": severity.value},
+        )
+    except ClientError as exc:
+        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
+            raise NoteNotFoundError(note_id) from None
+        raise
diff --git a/tests/test_config.py b/tests/test_config.py
index 0576353..076e59a 100644
--- a/tests/test_config.py
+++ b/tests/test_config.py
@@ -1,5 +1,5 @@
 import pytest
-from conftest import NOTES_TABLE, SIGNING_SECRET
+from conftest import BOT_TOKEN, NOTES_TABLE, SIGNING_SECRET
 from pydantic import SecretStr, ValidationError
 
 from slackkb.config import Settings
@@ -55,3 +55,16 @@ def test_dotenv_not_read(monkeypatch, tmp_path):
     monkeypatch.chdir(tmp_path)
     with pytest.raises(ValidationError):
         Settings()
+
+
+def test_missing_slack_bot_token_fails(monkeypatch):
+    monkeypatch.delenv("SLACKKB_SLACK_BOT_TOKEN")
+    with pytest.raises(ValidationError):
+        Settings()
+
+
+def test_bot_token_is_secret():
+    s = Settings()
+    assert isinstance(s.slack_bot_token, SecretStr)
+    assert BOT_TOKEN not in repr(s)
+    assert BOT_TOKEN not in str(s)
diff --git a/tests/test_modal.py b/tests/test_modal.py
new file mode 100644
index 0000000..30238a5
--- /dev/null
+++ b/tests/test_modal.py
@@ -0,0 +1,340 @@
+import ast
+import json
+import logging
+import time
+from pathlib import Path
+
+import boto3
+import pytest
+from conftest import BOT_TOKEN, SIGNING_SECRET
+from pydantic import SecretStr
+
+from slackkb import capture, modal
+from slackkb.config import Settings
+from slackkb.models import Note, NoteStatus, Severity, note_id
+from slackkb.slack_api import SlackApiError, SlackClient
+from slackkb.store import get_note, put_if_absent
+
+SRC = Path(__file__).parent.parent / "src" / "slackkb"
+NOTE_ID = note_id("T000TEST", "1111.2222.abcdef")
+TRIGGER_ID = "3333.4444.fedcba"
+NOTE_TEXT = "db connection timeouts on /api/orders since 14:05"
+VIEWS_OPEN_URL = "https://slack.com/api/views.open"
+
+
+@pytest.fixture(autouse=True)
+def capture_queue_env(monkeypatch):
+    monkeypatch.setenv("SLACKKB_CAPTURE_QUEUE_URL", "https://sqs.invalid/000000000000/q")
+
+
+class FakeTransport:
+    def __init__(self, reply=None, exc=None):
+        self.calls = []
+        self.reply = {"ok": True} if reply is None else reply
+        self.exc = exc
+
+    def __call__(self, url, headers, json_body):
+        self.calls.append((url, headers, json_body))
+        if self.exc is not None:
+            raise self.exc
+        return self.reply
+
+
+def _slack(transport):
+    return SlackClient(SecretStr(BOT_TOKEN), transport)
+
+
+def _handle(event, table, transport=None):
+    transport = FakeTransport() if transport is None else transport
+    return modal.handle(
+        event, table=table, slack=_slack(transport), settings=Settings(), now=int(time.time())
+    )
+
+
+def _capture(slack_request, table):
+    return capture.handle(
+        slack_request(),
+        table=table,
+        sqs=boto3.client("sqs"),
+        settings=Settings(),
+        now=int(time.time()),
+    )
+
+
+def _put_other_team_note(table, nid="b" * 32):
+    note = Note(note_id=nid, team_id="T999OTHER", channel_id="C1", user_id="U1", text="secret")
+    assert put_if_absent(table, note)
+    return nid
+
+
+def _errors(resp):
+    assert resp["statusCode"] == 200
+    body = json.loads(resp["body"])
+    assert body["response_action"] == "errors"
+    assert set(body["errors"]) == {"severity"}
+    assert body["errors"]["severity"]
+    return body
+
+
+def test_modal_submission_updates_severity(
+    slack_request, slack_interaction, notes_table, capture_queue
+):
+    _capture(slack_request, notes_table)
+    before = get_note(notes_table, NOTE_ID)
+    assert before.severity is Severity.LOW
+    resp = _handle(slack_interaction("view_submission", severity="HIGH"), notes_table)
+    assert resp["statusCode"] == 200
+    assert resp["body"] == ""
+    after = get_note(notes_table, NOTE_ID)
+    assert after.severity is Severity.HIGH
+    assert after.status is NoteStatus.CAPTURED
+    assert after.text == NOTE_TEXT
+    assert after == before.model_copy(update={"severity": Severity.HIGH})
+
+
+@pytest.mark.parametrize("duplicate", [False, True])
+def test_ack_has_set_severity_button(slack_request, notes_table, capture_queue, duplicate):
+    resp = _capture(slack_request, notes_table)
+    if duplicate:
+        resp = _capture(slack_request, notes_table)
+    body = json.loads(resp["body"])
+    assert body["response_type"] == "ephemeral"
+    assert body["text"] == capture.ACK_TEXT
+    section, actions = body["blocks"]
+    assert section["type"] == "section"
+    assert section["text"]["text"] == capture.ACK_TEXT
+    assert actions["type"] == "actions"
+    assert actions["block_id"] == "note_actions"
+    (button,) = actions["elements"]
+    assert button["type"] == "button"
+    assert button["action_id"] == "set_severity"
+    assert button["value"] == NOTE_ID
+
+
+def test_retry_message_has_no_button(slack_request, notes_table, capture_queue):
+    class Failing:
+        def send_message(self, **kwargs):
+            raise RuntimeError("boom")
+
+    from slackkb.queue import EnqueueError  # noqa: F401
+
+    sqs = boto3.client("sqs")
+    sqs.delete_queue(QueueUrl=capture_queue.url)
+    resp = capture.handle(
+        slack_request(), table=notes_table, sqs=sqs, settings=Settings(), now=int(time.time())
+    )
+    body = json.loads(resp["body"])
+    assert body == {"response_type": "ephemeral", "text": capture.RETRY_TEXT}
+
+
+def test_button_opens_modal_with_note_id(
+    slack_request, slack_interaction, notes_table, capture_queue
+):
+    _capture(slack_request, notes_table)
+    transport = FakeTransport()
+    resp = _handle(slack_interaction("block_actions"), notes_table, transport)
+    assert resp["statusCode"] == 200
+    assert resp["body"] == ""
+    (call,) = transport.calls
+    url, headers, body = call
+    assert url == VIEWS_OPEN_URL
+    assert headers["Authorization"] == f"Bearer {BOT_TOKEN}"
+    assert body["trigger_id"] == TRIGGER_ID
+    view = body["view"]
+    assert view["type"] == "modal"
+    assert view["callback_id"] == "severity_modal"
+    assert view["private_metadata"] == NOTE_ID
+    (block,) = view["blocks"]
+    assert block["type"] == "input"
+    assert block["block_id"] == "severity"
+    element = block["element"]
+    assert element["type"] == "static_select"
+    assert element["action_id"] == "severity_select"
+    assert [o["value"] for o in element["options"]] == [s.value for s in Severity]
+    assert element["initial_option"]["value"] == "LOW"
+
+
+def test_button_initial_option_is_current_severity(
+    slack_request, slack_interaction, notes_table, capture_queue
+):
+    _capture(slack_request, notes_table)
+    _handle(slack_interaction("view_submission", severity="CRITICAL"), notes_table)
+    transport = FakeTransport()
+    _handle(slack_interaction("block_actions"), notes_table, transport)
+    element = transport.calls[0][2]["view"]["blocks"][0]["element"]
+    assert element["initial_option"]["value"] == "CRITICAL"
+
+
+def test_button_for_missing_note_opens_nothing(slack_interaction, notes_table):
+    transport = FakeTransport()
+    resp = _handle(slack_interaction("block_actions"), notes_table, transport)
+    assert resp["statusCode"] == 200
+    assert resp["body"] == ""
+    assert transport.calls == []
+
+
+def test_other_action_id_opens_nothing(
+    slack_interaction, slack_request, notes_table, capture_queue
+):
+    _capture(slack_request, notes_table)
+    event = slack_interaction("block_actions")
+    import urllib.parse
+
+    from conftest import sign
+
+    payload = json.loads(urllib.parse.parse_qs(event["body"])["payload"][0])
+    payload["actions"][0]["action_id"] = "something_else"
+    body = urllib.parse.urlencode({"payload": json.dumps(payload)})
+    ts = int(time.time())
+    event = {
+        "headers": {"X-Slack-Request-Timestamp": str(ts), "X-Slack-Signature": sign(body, ts)},
+        "body": body,
+        "isBase64Encoded": False,
+    }
+    transport = FakeTransport()
+    resp = _handle(event, notes_table, transport)
+    assert resp["statusCode"] == 200
+    assert resp["body"] == ""
+    assert transport.calls == []
+
+
+def test_unknown_severity_returns_errors(
+    slack_request, slack_interaction, notes_table, capture_queue
+):
+    _capture(slack_request, notes_table)
+    for bad in ("URGENT", "high", ""):
+        resp = _handle(slack_interaction("view_submission", severity=bad), notes_table)
+        _errors(resp)
+    assert get_note(notes_table, NOTE_ID).severity is Severity.LOW
+
+
+def test_submission_for_missing_note_returns_errors(slack_interaction, notes_table):
+    resp = _handle(slack_interaction("view_submission", severity="HIGH"), notes_table)
+    _errors(resp)
+    assert notes_table.scan()["Count"] == 0
+
+
+def test_other_team_cannot_set_severity(slack_interaction, notes_table):
+    nid = _put_other_team_note(notes_table)
+    transport = FakeTransport()
+    resp = _handle(slack_interaction("block_actions", note_id=nid), notes_table, transport)
+    assert resp["statusCode"] == 200
+    assert resp["body"] == ""
+    assert transport.calls == []
+
+    resp = _handle(
+        slack_interaction("view_submission", severity="CRITICAL", note_id=nid), notes_table
+    )
+    body = _errors(resp)
+    assert get_note(notes_table, nid).severity is Severity.LOW
+    # same message as a missing note: no probing of note ids
+    missing = _errors(
+        _handle(
+            slack_interaction("view_submission", severity="CRITICAL", note_id="c" * 32),
+            notes_table,
+        )
+    )
+    assert body == missing
+
+
+@pytest.mark.parametrize("kind", ["block_actions", "view_submission"])
+def test_bad_signature_rejected(slack_request, slack_interaction, notes_table, capture_queue, kind):
+    _capture(slack_request, notes_table)
+    transport = FakeTransport()
+    bad = _handle(slack_interaction(kind, severity="HIGH", secret="wrong"), notes_table, transport)
+    assert bad["statusCode"] == 401
+    stale = _handle(
+        slack_interaction(kind, severity="HIGH", ts=int(time.time()) - 3600), notes_table, transport
+    )
+    assert stale["statusCode"] == 401
+    assert transport.calls == []
+    assert get_note(notes_table, NOTE_ID).severity is Severity.LOW
+
+
+def _signed(body):
+    from conftest import sign
+
+    ts = int(time.time())
+    return {
+        "headers": {"X-Slack-Request-Timestamp": str(ts), "X-Slack-Signature": sign(body, ts)},
+        "body": body,
+        "isBase64Encoded": False,
+    }
+
+
+@pytest.mark.parametrize("body", ["foo=bar", "payload=not-json", "payload=%5B1%5D", ""])
+def test_missing_or_invalid_payload_is_400(notes_table, body):
+    assert _handle(_signed(body), notes_table)["statusCode"] == 400
+
+
+def test_unknown_payload_type_rejected(notes_table):
+    import urllib.parse
+
+    for payload in (
+        {"type": "view_closed", "team": {"id": "T000TEST"}},
+        {"type": "shortcut"},
+        {},
+    ):
+        body = urllib.parse.urlencode({"payload": json.dumps(payload)})
+        assert _handle(_signed(body), notes_table)["statusCode"] == 400
+
+
+def test_views_open_failure_is_logged_not_raised(
+    slack_request, slack_interaction, notes_table, capture_queue, caplog
+):
+    _capture(slack_request, notes_table)
+    failures = [
+        FakeTransport(reply={"ok": False, "error": "expired_trigger_id"}),
+        FakeTransport(exc=OSError("network down")),
+    ]
+    for transport in failures:
+        caplog.clear()
+        with caplog.at_level(logging.WARNING):
+            resp = _handle(slack_interaction("block_actions"), notes_table, transport)
+        assert resp["statusCode"] == 200
+        assert resp["body"] == ""
+        assert len(transport.calls) == 1
+        assert any(
+            r.levelno == logging.WARNING and NOTE_ID in r.getMessage() for r in caplog.records
+        )
+        logged = caplog.text
+        assert BOT_TOKEN not in logged
+        assert SIGNING_SECRET not in logged
+        assert NOTE_TEXT not in logged
+        assert "hooks.slack.invalid" not in logged
+
+
+def test_slack_client_raises_on_failure():
+    client = _slack(FakeTransport(reply={"ok": False, "error": "invalid_auth"}))
+    with pytest.raises(SlackApiError) as info:
+        client.views_open("t", {"type": "modal"})
+    assert BOT_TOKEN not in str(info.value)
+    with pytest.raises(SlackApiError):
+        _slack(FakeTransport(exc=OSError("x"))).views_open("t", {})
+    assert BOT_TOKEN not in repr(client)
+
+
+def _imported_modules(tree):
+    for node in ast.walk(tree):
+        if isinstance(node, ast.Import):
+            yield from (alias.name for alias in node.names)
+        elif isinstance(node, ast.ImportFrom) and node.module:
+            yield node.module
+
+
+BANNED = (
+    "boto3", "botocore", "aiobotocore", "requests", "httpx", "urllib3", "aiohttp",
+    "http", "urllib.request", "socket", "slack_sdk", "slack_bolt",
+)
+
+
+@pytest.mark.parametrize("name", ["modal.py", "capture.py"])
+def test_handlers_import_no_http_client(name):
+    source = (SRC / name).read_text()
+    modules = set(_imported_modules(ast.parse(source)))
+    for module in modules:
+        for banned in BANNED:
+            assert module != banned and not module.startswith(banned + "."), module
+    assert "response_url" not in source
+    if name == "modal.py":
+        assert {"slackkb.store", "slackkb.slack_verify"} <= modules
diff --git a/tests/test_store.py b/tests/test_store.py
index a0f28a6..b241ebd 100644
--- a/tests/test_store.py
+++ b/tests/test_store.py
@@ -48,3 +48,24 @@ def test_put_if_absent_propagates_other_errors(notes_table):
     with pytest.raises(ClientError) as exc:
         put_if_absent(missing, make_note())
     assert exc.value.response["Error"]["Code"] != "ConditionalCheckFailedException"
+
+
+def test_set_severity_leaves_status(notes_table):
+    from slackkb.models import NoteStatus, Severity
+    from slackkb.store import set_severity
+
+    note = make_note(status=NoteStatus.ROUTED)
+    assert put_if_absent(notes_table, note)
+    set_severity(notes_table, note.note_id, Severity.CRITICAL)
+    assert get_note(notes_table, note.note_id) == note.model_copy(
+        update={"severity": Severity.CRITICAL}
+    )
+
+
+def test_set_severity_missing_note_raises(notes_table):
+    from slackkb.models import Severity
+    from slackkb.store import NoteNotFoundError, set_severity
+
+    with pytest.raises(NoteNotFoundError):
+        set_severity(notes_table, "f" * 32, Severity.HIGH)
+    assert notes_table.scan()["Count"] == 0
diff --git a/tests/test_worker.py b/tests/test_worker.py
index 208233d..a3372b0 100644
--- a/tests/test_worker.py
+++ b/tests/test_worker.py
@@ -55,7 +55,9 @@ def _failures(resp):
 def test_ack_before_processing(slack_request, notes_table, capture_queue):
     resp = _capture(slack_request(), notes_table)
     assert resp["statusCode"] == 200
-    assert json.loads(resp["body"]) == {"response_type": "ephemeral", "text": capture.ACK_TEXT}
+    body = json.loads(resp["body"])
+    assert body["response_type"] == "ephemeral"
+    assert body["text"] == capture.ACK_TEXT
     # No worker has run: the note is still CAPTURED and its job is waiting on the queue.
     assert get_note(notes_table, EXPECTED_NOTE_ID).status is NoteStatus.CAPTURED
     messages = _queued(capture_queue.url)

review PASS: All claims are supported by the diff. The Slack modal handling correctly verifies signatures, responds to block actions and view submissions, safely performs conditional DynamoDB updates, abstracts HTTP transport securely without leaking tokens, and validates error flows effectively. No bugs, secrets, or insecure patterns observed.
merge prama/personal_b9a5284d into the current branch of /home/vajrasarpa/Projects/slack-kb? [y/N]: merged as c550d13c9844. Nothing was pushed.
