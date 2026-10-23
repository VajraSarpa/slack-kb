from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings from SLACKKB_-prefixed environment variables (D-007).

    `extra` is deliberately left at the pydantic-settings default ("forbid")
    so unknown keyword arguments raise ValidationError. No .env file is read.
    """

    model_config = SettingsConfigDict(env_prefix="SLACKKB_")

    signing_secret: SecretStr
    notes_table: str
