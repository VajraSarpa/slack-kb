import pytest
from conftest import NOTES_TABLE, SIGNING_SECRET
from pydantic import SecretStr, ValidationError

from slackkb.config import Settings


def test_reads_prefixed_env():
    s = Settings()
    assert s.notes_table == NOTES_TABLE
    assert isinstance(s.signing_secret, SecretStr)
    assert s.signing_secret.get_secret_value() == SIGNING_SECRET


def test_missing_signing_secret_fails(monkeypatch):
    monkeypatch.delenv("SLACKKB_SIGNING_SECRET")
    with pytest.raises(ValidationError):
        Settings()


def test_missing_notes_table_fails(monkeypatch):
    monkeypatch.delenv("SLACKKB_NOTES_TABLE")
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
