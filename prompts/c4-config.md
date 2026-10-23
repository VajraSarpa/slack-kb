GOAL
Rung C4 of Slice 1: load app settings from SLACKKB_-prefixed environment
variables.

SCOPE (only these paths may change)
- src/slackkb/config.py
- tests/test_config.py

CONTEXT
- tests/conftest.py and tests/fixtures/ are read-only. Its autouse
  offline_env fixture sets SLACKKB_SIGNING_SECRET and SLACKKB_NOTES_TABLE;
  use monkeypatch to change or remove them in a test.
- docs/DECISIONS.md (D-007) and okf/slackkb/ are authoritative. reference/
  is testimony.
- In the sandbox, run tests with `python -m pytest`; `uv` is not on PATH.

REQUIREMENTS
1. class Settings(pydantic_settings.BaseSettings), env prefix SLACKKB_.
2. signing_secret: SecretStr, required, no default.
3. notes_table: str, required, no default.
4. No .env file is read and no secret value is hard-coded.
   repr(Settings()) must not contain the secret.
5. Do not set `extra` in model_config. An unknown keyword argument
   (e.g. a misspelled field name) must raise ValidationError, never be
   silently ignored.

TESTS (write first; they must fail before implementation)
- test_reads_prefixed_env
- test_missing_signing_secret_fails
- test_missing_notes_table_fails
- test_secret_not_in_repr
- test_unknown_kwarg_rejected
Every requirement above has a test that fails if the requirement is
broken.

NON-GOALS
No Secrets Manager (Slice 8), no caching helper, no handler. Do not touch
reference/, tests/conftest.py, or tests/fixtures/.

DONE WHEN
All checks exit 0 in the sandbox with no network.
