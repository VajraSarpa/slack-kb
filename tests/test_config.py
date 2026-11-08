import pytest
from conftest import (
    BOT_TOKEN,
    EMBED_MODEL_ID,
    NOTES_BUCKET,
    NOTES_TABLE,
    SIGNING_SECRET,
    VECTORS_TABLE,
)
from pydantic import SecretStr, ValidationError

from slackkb.config import Settings

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


def test_missing_signing_secret_fails(monkeypatch):
    monkeypatch.delenv("SLACKKB_SIGNING_SECRET")
    with pytest.raises(ValidationError):
        Settings()


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
    with pytest.raises(ValidationError):
        Settings()


def test_missing_slack_bot_token_fails(monkeypatch):
    monkeypatch.delenv("SLACKKB_SLACK_BOT_TOKEN")
    with pytest.raises(ValidationError):
        Settings()


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
