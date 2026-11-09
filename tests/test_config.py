import time

import pytest
from conftest import (
    BOT_TOKEN,
    EMBED_MODEL_ID,
    EVENTS_TABLE,
    NOTES_BUCKET,
    NOTES_TABLE,
    QUESTION_QUEUE_URL,
    SIGNING_SECRET,
    VECTORS_TABLE,
)
from pydantic import SecretStr, ValidationError

from slackkb import capture, events, modal, thread
from slackkb.config import MissingSecret, Settings
from slackkb.slack_api import SlackClient

CAPTURE_QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/slackkb-capture-test"


@pytest.fixture(autouse=True)
def capture_queue_env(monkeypatch):
    monkeypatch.setenv("SLACKKB_CAPTURE_QUEUE_URL", CAPTURE_QUEUE_URL)


def test_reads_prefixed_env():
    s = Settings()
    assert s.notes_table == NOTES_TABLE
    assert isinstance(s.signing_secret, SecretStr)
    assert s.signing_secret.get_secret_value() == SIGNING_SECRET
    assert s.capture_queue_url == CAPTURE_QUEUE_URL


def test_missing_signing_secret_is_none(monkeypatch):
    monkeypatch.delenv("SLACKKB_SIGNING_SECRET")
    s = Settings()
    assert s.signing_secret is None
    with pytest.raises(MissingSecret) as exc:
        s.require("signing_secret")
    assert str(exc.value) == "signing_secret is not configured"


def test_reads_vectors_settings():
    s = Settings()
    assert s.vectors_table == VECTORS_TABLE
    assert s.embed_model_id == EMBED_MODEL_ID


@pytest.mark.parametrize("name", ["SLACKKB_VECTORS_TABLE", "SLACKKB_EMBED_MODEL_ID"])
def test_missing_vectors_settings_fail(monkeypatch, name):
    monkeypatch.delenv(name)
    with pytest.raises(ValidationError):
        Settings()


def test_missing_notes_table_fails(monkeypatch):
    monkeypatch.delenv("SLACKKB_NOTES_TABLE")
    with pytest.raises(ValidationError):
        Settings()


def test_reads_notes_bucket():
    assert Settings().notes_bucket == NOTES_BUCKET


def test_missing_notes_bucket_fails(monkeypatch):
    monkeypatch.delenv("SLACKKB_NOTES_BUCKET")
    with pytest.raises(ValidationError):
        Settings()


def test_missing_capture_queue_url_fails(monkeypatch):
    monkeypatch.delenv("SLACKKB_CAPTURE_QUEUE_URL")
    with pytest.raises(ValidationError):
        Settings()


def test_secret_not_in_repr():
    s = Settings()
    assert SIGNING_SECRET not in repr(s)
    assert SIGNING_SECRET not in str(s)


def test_unknown_kwarg_rejected():
    with pytest.raises(ValidationError):
        Settings(notes_tabel="typo")


def test_dotenv_not_read(monkeypatch, tmp_path):
    monkeypatch.delenv("SLACKKB_SIGNING_SECRET")
    (tmp_path / ".env").write_text("SLACKKB_SIGNING_SECRET=from-dotenv\n")
    monkeypatch.chdir(tmp_path)
    assert Settings().signing_secret is None


def test_missing_slack_bot_token_is_none(monkeypatch):
    monkeypatch.delenv("SLACKKB_SLACK_BOT_TOKEN")
    s = Settings()
    assert s.slack_bot_token is None
    with pytest.raises(MissingSecret) as exc:
        s.require("slack_bot_token")
    assert str(exc.value) == "slack_bot_token is not configured"


def test_reads_qa_model_id():
    assert Settings().qa_model_id == "us.anthropic.claude-haiku-test"


def test_missing_qa_model_id_fails(monkeypatch):
    monkeypatch.delenv("SLACKKB_QA_MODEL_ID")
    with pytest.raises(ValidationError):
        Settings()


def test_bot_token_is_secret():
    s = Settings()
    assert isinstance(s.slack_bot_token, SecretStr)
    assert BOT_TOKEN not in repr(s)
    assert BOT_TOKEN not in str(s)


def test_reads_events_settings():
    s = Settings()
    assert s.events_table == EVENTS_TABLE
    assert s.question_queue_url == QUESTION_QUEUE_URL


@pytest.mark.parametrize("name", ["SLACKKB_EVENTS_TABLE", "SLACKKB_QUESTION_QUEUE_URL"])
def test_missing_events_settings_fail(monkeypatch, name):
    monkeypatch.delenv(name)
    with pytest.raises(ValidationError):
        Settings()


def test_require_returns_the_secret():
    s = Settings()
    assert isinstance(s.require("signing_secret"), SecretStr)
    assert s.require("signing_secret").get_secret_value() == SIGNING_SECRET
    assert s.require("slack_bot_token").get_secret_value() == BOT_TOKEN
    with pytest.raises(ValueError):
        s.require("other")


class _Recorder:
    """A fake that records any attribute access or call."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        self.calls.append(name)
        raise AssertionError(f"unexpected use: {name}")

    def __call__(self, *args, **kwargs):
        self.calls.append("call")
        raise AssertionError("unexpected call")


def test_capture_without_signing_secret_raises(monkeypatch, slack_request):
    monkeypatch.delenv("SLACKKB_SIGNING_SECRET")
    table, sqs = _Recorder(), _Recorder()
    with pytest.raises(MissingSecret):
        capture.handle(
            slack_request(), table=table, sqs=sqs, settings=Settings(), now=int(time.time())
        )
    assert table.calls == [] and sqs.calls == []


def test_modal_without_signing_secret_raises(monkeypatch, slack_interaction):
    monkeypatch.delenv("SLACKKB_SIGNING_SECRET")
    table, slack = _Recorder(), _Recorder()
    with pytest.raises(MissingSecret):
        modal.handle(
            slack_interaction("block_actions"),
            table=table,
            slack=slack,
            settings=Settings(),
            now=int(time.time()),
        )
    assert table.calls == [] and slack.calls == []


def test_events_without_signing_secret_raises(monkeypatch, slack_event):
    monkeypatch.delenv("SLACKKB_SIGNING_SECRET")
    events_table, sqs = _Recorder(), _Recorder()
    with pytest.raises(MissingSecret):
        events.handle(
            slack_event(),
            events_table=events_table,
            sqs=sqs,
            settings=Settings(),
            now=int(time.time()),
        )
    assert events_table.calls == [] and sqs.calls == []


def test_handlers_with_signing_secret_still_verify(
    slack_request, slack_interaction, slack_event
):
    now = int(time.time())
    bad = "wrong-secret"
    fake = _Recorder()
    s = Settings()
    assert capture.handle(
        slack_request(secret=bad), table=fake, sqs=fake, settings=s, now=now
    )["statusCode"] == 401
    assert modal.handle(
        slack_interaction("block_actions", secret=bad),
        table=fake,
        slack=fake,
        settings=s,
        now=now,
    )["statusCode"] == 401
    assert events.handle(
        slack_event(secret=bad), events_table=fake, sqs=fake, settings=s, now=now
    )["statusCode"] == 401


def test_thread_slack_client_without_bot_token_raises(monkeypatch):
    assert isinstance(thread.slack_client(Settings()), SlackClient)
    monkeypatch.delenv("SLACKKB_SLACK_BOT_TOKEN")
    with pytest.raises(MissingSecret):
        thread.slack_client(Settings())
