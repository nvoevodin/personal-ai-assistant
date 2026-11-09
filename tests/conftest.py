"""Pytest fixtures for isolating configuration, mocks, and asynchronous tests."""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock
from telegram import Chat, Message, PhotoSize, Update, User
from telegram.ext import ContextTypes

from agent.runner import AgentRunner
from connectors.base import ConnectorRegistry
from connectors.gmail import GmailConnector
from connectors.monarch import MonarchConnector
from core.config import Settings
from core.gemini import GeminiClient
from core.rate_limit import RateLimiter


@pytest.fixture(autouse=True)
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set default test environment variables."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ")
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyTestGeminiFakeKey12345678")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "111222333,444555666")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")
    monkeypatch.setenv("RATE_LIMIT_CALLS_PER_MINUTE", "60")


@pytest.fixture
def test_settings() -> Settings:
    """Create an explicit Settings instance for unit tests."""
    return Settings(
        telegram_bot_token="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ",
        gemini_api_key="AIzaSyTestGeminiFakeKey12345678",
        allowed_telegram_user_ids={111222333, 444555666},
        gemini_model="gemini-3.8-flash",
        rate_limit_calls_per_minute=60,
    )


@pytest.fixture
def mock_gemini_client() -> GeminiClient:
    """Provide a mock GeminiClient instance."""
    client = MagicMock(spec=GeminiClient)
    client.model = "gemini-3.8-flash"
    client.generate_text = AsyncMock(return_value="Mocked text completion from Gemini 3.8 Flash.")
    client.analyze_image = AsyncMock(return_value="Mocked OCR Receipt Analysis:\n- Merchant: Whole Foods\n- Total: $142.38")
    client.generate_with_tools = AsyncMock(
        return_value=("Processed response with financial tools.", [{"name": "get_financial_summary", "args": {}, "result": "OK"}])
    )
    return client


@pytest.fixture
def mock_registry() -> ConnectorRegistry:
    """Provide a populated ConnectorRegistry with mock Monarch and Gmail connectors."""
    registry = ConnectorRegistry()
    registry.register(MonarchConnector())
    registry.register(GmailConnector())
    return registry


@pytest.fixture
def mock_agent_runner(mock_gemini_client: GeminiClient, mock_registry: ConnectorRegistry) -> AgentRunner:
    """Provide an AgentRunner configured with mock client and connectors."""
    limiter = RateLimiter(max_calls=100, window_seconds=60.0)
    return AgentRunner(
        gemini_client=mock_gemini_client,
        registry=mock_registry,
        rate_limiter=limiter,
    )


@pytest.fixture
def make_telegram_update():
    """Factory fixture generating realistic mock Telegram Update objects."""

    def _factory(
        user_id: int = 111222333,
        username: str = "testuser",
        text: str | None = None,
        photo_bytes: bytes | None = None,
        caption: str | None = None,
    ) -> tuple[Update, ContextTypes.DEFAULT_TYPE]:
        user = User(id=user_id, is_bot=False, first_name="Test", username=username)
        chat = Chat(id=user_id, type="private")

        message = MagicMock(spec=Message)
        message.from_user = user
        message.effective_user = user
        message.chat = chat
        message.text = text
        message.caption = caption
        message.reply_text = AsyncMock()

        if photo_bytes is not None:
            photo_size = MagicMock(spec=PhotoSize)
            telegram_file = MagicMock()
            telegram_file.download_as_bytearray = AsyncMock(return_value=bytearray(photo_bytes))
            photo_size.get_file = AsyncMock(return_value=telegram_file)
            message.photo = [photo_size]
        else:
            message.photo = []

        update = MagicMock(spec=Update)
        update.effective_user = user
        update.effective_chat = chat
        update.effective_message = message
        update.message = message

        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        context.bot = MagicMock()
        context.bot.send_chat_action = AsyncMock()
        context.bot_data = {}

        return update, context

    return _factory
