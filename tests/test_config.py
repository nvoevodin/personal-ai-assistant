"""Unit tests for configuration validation and environment settings."""

import pytest
from pydantic import ValidationError
from core.config import Settings


def test_settings_valid_initialization(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify settings loads properly when all required keys are present."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_bot_token_123")
    monkeypatch.setenv("GEMINI_API_KEY", "test_gemini_key_456")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "1001, 1002, 1003")

    settings = Settings()
    assert settings.telegram_token_value == "test_bot_token_123"
    assert settings.gemini_api_key_value == "test_gemini_key_456"
    assert settings.allowed_telegram_user_ids == {1001, 1002, 1003}
    assert settings.gemini_model == "gemini-3.8-flash"
    assert settings.is_user_allowed(1001) is True
    assert settings.is_user_allowed(9999) is False
    assert settings.is_user_allowed(None) is False


def test_settings_comma_and_semicolon_formats(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify parser handles various delimiters and whitespace."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("GEMINI_API_KEY", "key")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", " 555; 666 , 777 ")

    settings = Settings()
    assert settings.allowed_telegram_user_ids == {555, 666, 777}


def test_settings_single_int_format() -> None:
    """Verify passing a single int directly to allowed_telegram_user_ids."""
    settings = Settings(
        telegram_bot_token="tok",
        gemini_api_key="key",
        allowed_telegram_user_ids=12345,  # type: ignore[arg-type]
    )
    assert settings.allowed_telegram_user_ids == {12345}


def test_settings_missing_token_raises_validation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure missing TELEGRAM_BOT_TOKEN triggers a ValidationError."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "key")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    with pytest.raises(ValidationError) as exc:
        Settings()
    assert "telegram_bot_token" in str(exc.value)


def test_settings_invalid_user_id_raises_validation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure non-numeric user IDs fail validation."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("GEMINI_API_KEY", "key")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "not_a_number,123")

    with pytest.raises(ValidationError):
        Settings()
