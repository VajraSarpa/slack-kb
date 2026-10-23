finding: anumanabhasa: attempt 1: "Besides the five named tests, I added test_dotenv_not_read. It puts a .env file with the secret in the cwd and checks that Settings() still raises, which covers the 'no .env file is read' requirement." cites no observation for its reason
diff --git a/src/slackkb/config.py b/src/slackkb/config.py
new file mode 100644
index 0000000..e7054b3
--- /dev/null
+++ b/src/slackkb/config.py
@@ -0,0 +1,15 @@
+from pydantic import SecretStr
+from pydantic_settings import BaseSettings, SettingsConfigDict
+
+
+class Settings(BaseSettings):
+    """App settings from SLACKKB_-prefixed environment variables (D-007).
+
+    `extra` is deliberately left at the pydantic-settings default ("forbid")
+    so unknown keyword arguments raise ValidationError. No .env file is read.
+    """
+
+    model_config = SettingsConfigDict(env_prefix="SLACKKB_")
+
+    signing_secret: SecretStr
+    notes_table: str
diff --git a/tests/test_config.py b/tests/test_config.py
new file mode 100644
index 0000000..a63e1d8
--- /dev/null
+++ b/tests/test_config.py
@@ -0,0 +1,43 @@
+import pytest
+from conftest import NOTES_TABLE, SIGNING_SECRET
+from pydantic import SecretStr, ValidationError
+
+from slackkb.config import Settings
+
+
+def test_reads_prefixed_env():
+    s = Settings()
+    assert s.notes_table == NOTES_TABLE
+    assert isinstance(s.signing_secret, SecretStr)
+    assert s.signing_secret.get_secret_value() == SIGNING_SECRET
+
+
+def test_missing_signing_secret_fails(monkeypatch):
+    monkeypatch.delenv("SLACKKB_SIGNING_SECRET")
+    with pytest.raises(ValidationError):
+        Settings()
+
+
+def test_missing_notes_table_fails(monkeypatch):
+    monkeypatch.delenv("SLACKKB_NOTES_TABLE")
+    with pytest.raises(ValidationError):
+        Settings()
+
+
+def test_secret_not_in_repr():
+    s = Settings()
+    assert SIGNING_SECRET not in repr(s)
+    assert SIGNING_SECRET not in str(s)
+
+
+def test_unknown_kwarg_rejected():
+    with pytest.raises(ValidationError):
+        Settings(notes_tabel="typo")
+
+
+def test_dotenv_not_read(monkeypatch, tmp_path):
+    monkeypatch.delenv("SLACKKB_SIGNING_SECRET")
+    (tmp_path / ".env").write_text("SLACKKB_SIGNING_SECRET=from-dotenv\n")
+    monkeypatch.chdir(tmp_path)
+    with pytest.raises(ValidationError):
+        Settings()

review PASS: The changes correctly implement the requirements using `pydantic-settings` V2. The `Settings` class is properly configured with `SettingsConfigDict` and safely handles secrets via `SecretStr`. The tests cover all edge cases, including verifying that `.env` files are intentionally ignored, missing environment variables correctly raise `ValidationError`, extra keyword arguments are forbidden, and secrets don't leak into `repr()` strings. Pytest execution passed cleanly and `monkeypatch` was utilized safely. The author's claims are fully supported by the diff and test results.
merge prama/personal_4a2f7ff2 into the current branch of /home/vajrasarpa/Projects/slack-kb? [y/N]: merged as c85c2484c73b. Nothing was pushed.
