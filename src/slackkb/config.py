from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class MissingSecret(RuntimeError):
    """A handler needs a secret this Lambda was not given (D-020)."""


class Settings(BaseSettings):
    """App settings from SLACKKB_-prefixed environment variables (D-007).

    `extra` is deliberately left at the pydantic-settings default ("forbid")
    so unknown keyword arguments raise ValidationError. No .env file is read.
    """

    model_config = SettingsConfigDict(env_prefix="SLACKKB_")

    signing_secret: SecretStr | None = None
    notes_table: str
    notes_bucket: str
    capture_queue_url: str
    slack_bot_token: SecretStr | None = None
    qa_model_id: str
    vectors_table: str
    embed_model_id: str
    events_table: str
    question_queue_url: str

    def require(self, name: str) -> SecretStr:
        """The named secret, or MissingSecret when this Lambda was not given it."""
        if name not in ("signing_secret", "slack_bot_token"):
            raise ValueError(f"{name} is not a secret setting")
        value = getattr(self, name)
        if value is None:
            raise MissingSecret(f"{name} is not configured")
        return value
