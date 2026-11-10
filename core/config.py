"""Application configuration and environment variable validation using Pydantic Settings."""

import functools
from typing import Any
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly typed application configuration validated from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    telegram_bot_token: SecretStr = Field(
        ...,
        description="Telegram Bot API token issued by @BotFather",
    )
    gemini_api_key: SecretStr = Field(
        ...,
        description="Google Gemini API key from Google AI Studio",
    )
    allowed_telegram_user_ids: set[int] | str = Field(
        ...,
        description="Whitelist of allowed Telegram user IDs permitted to access the bot",
    )
    gemini_model: str = Field(
        default="gemini-3.8-flash",
        description="Gemini model identifier for text and multimodal OCR operations",
    )
    openai_api_key: SecretStr | None = Field(
        default=None,
        description="Optional OpenAI API key for 3-tier model dispatcher",
    )
    openai_tier1_model: str = Field(
        default="gpt-6-luna",
        description="Tier 1 High-Speed Router & Noise Gatekeeper model identifier",
    )
    openai_tier2_model: str = Field(
        default="gpt-6.1-terra",
        description="Tier 2 Default Brain & Daily Workhorse model identifier",
    )
    openai_tier3_model: str = Field(
        default="gpt-6.1-sol",
        description="Tier 3 Frontier Deep Analyst model identifier",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )
    rate_limit_calls_per_minute: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Maximum permitted LLM invocations per minute per user",
    )
    monarch_token: SecretStr | None = Field(
        default=None,
        description="Optional Monarch Money session token for live account syncing",
    )
    monarch_email: str | None = Field(
        default=None,
        description="Optional Monarch Money login email",
    )
    monarch_password: SecretStr | None = Field(
        default=None,
        description="Optional Monarch Money login password",
    )
    monarch_mfa_secret: SecretStr | None = Field(
        default=None,
        description="Optional Monarch Money TOTP secret for hands-free background 2FA",
    )
    monarch_cookie: SecretStr | None = Field(
        default=None,
        description="Optional Monarch Money session cookie for authenticated GraphQL calls",
    )
    gmail_email: str | None = Field(
        default=None,
        description="Gmail or Google Workspace email address",
    )
    gmail_app_password: SecretStr | None = Field(
        default=None,
        description="Gmail 16-character App Password generated from Google Account Security",
    )
    gmail_credentials_file: str | None = Field(
        default=None,
        description="Path to OAuth credentials.json file for Google Workspace API",
    )

    @field_validator("allowed_telegram_user_ids", mode="before")
    @classmethod
    def parse_allowed_user_ids(cls, v: Any) -> set[int]:
        """Parse comma-separated strings, lists, or numbers into a set of integer IDs."""
        if isinstance(v, str):
            # Split comma or whitespace separated values
            tokens = [token.strip() for token in v.replace(";", ",").split(",") if token.strip()]
            if not tokens:
                raise ValueError("ALLOWED_TELEGRAM_USER_IDS must contain at least one valid user ID")
            try:
                return {int(tok) for tok in tokens}
            except ValueError as err:
                raise ValueError(f"Invalid user ID in ALLOWED_TELEGRAM_USER_IDS: {err}") from err

        if isinstance(v, (list, tuple, set)):
            if not v:
                raise ValueError("ALLOWED_TELEGRAM_USER_IDS cannot be empty")
            return {int(item) for item in v}

        if isinstance(v, int):
            return {v}

        raise ValueError(f"Cannot parse ALLOWED_TELEGRAM_USER_IDS from type: {type(v)}")

    @property
    def telegram_token_value(self) -> str:
        """Helper to expose the raw Telegram Bot Token safely."""
        return self.telegram_bot_token.get_secret_value()

    @property
    def gemini_api_key_value(self) -> str:
        """Helper to expose the raw Gemini API Key safely."""
        return self.gemini_api_key.get_secret_value()

    @property
    def openai_api_key_value(self) -> str | None:
        """Helper to expose the raw OpenAI API Key safely."""
        return self.openai_api_key.get_secret_value() if self.openai_api_key else None

    @property
    def monarch_token_value(self) -> str | None:
        """Helper to expose the raw Monarch Token safely."""
        return self.monarch_token.get_secret_value() if self.monarch_token else None

    @property
    def monarch_password_value(self) -> str | None:
        """Helper to expose the raw Monarch Password safely."""
        return self.monarch_password.get_secret_value() if self.monarch_password else None

    @property
    def monarch_mfa_secret_value(self) -> str | None:
        """Helper to expose the raw Monarch MFA secret safely."""
        return self.monarch_mfa_secret.get_secret_value() if self.monarch_mfa_secret else None

    @property
    def monarch_cookie_value(self) -> str | None:
        """Helper to expose the raw Monarch session cookie safely."""
        return self.monarch_cookie.get_secret_value() if self.monarch_cookie else None

    @property
    def gmail_app_password_value(self) -> str | None:
        """Helper to expose the raw Gmail app password safely."""
        return self.gmail_app_password.get_secret_value() if self.gmail_app_password else None

    def is_user_allowed(self, user_id: int | None) -> bool:
        """Determine if a Telegram user ID is whitelisted."""
        if user_id is None:
            return False
        return user_id in self.allowed_telegram_user_ids


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton getter for validated application settings."""
    return Settings()
