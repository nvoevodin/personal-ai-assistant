"""Unit tests for Telegram bot handlers, security filters, and application factory."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from telegram import Chat, Message, PhotoSize, Update, User
from telegram.ext import ContextTypes

from bot.handlers import (
    bills_command,
    error_handler,
    photo_message_handler,
    start_command,
    status_command,
    sync_command,
    text_message_handler,
)
from bot.main import build_bot_application, unauthorized_user_handler
from bot.security import UserWhitelistFilter, authorized_only
from connectors.base import ConnectorRegistry
from core.config import Settings
from core.gemini import GeminiClient


@pytest.fixture
def mock_bot_context(test_settings: Settings, mock_gemini_client: GeminiClient) -> MagicMock:
    """Create a mock Telegram ContextTypes object with registered bot_data."""
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.bot = MagicMock()
    context.bot.send_chat_action = AsyncMock()

    mock_runner = MagicMock()
    mock_runner.handle_user_query = AsyncMock(return_value="Agent response to test query")
    mock_runner.handle_photo_analysis = AsyncMock(return_value="Photo receipt summary: $42.00")

    mock_registry = MagicMock(spec=ConnectorRegistry)
    mock_registry.all_connectors.return_value = []
    mock_registry.fetch_all_events = AsyncMock(return_value=[])

    context.bot_data = {
        "settings": test_settings,
        "agent_runner": mock_runner,
        "connector_registry": mock_registry,
        "gemini_client": mock_gemini_client,
    }
    return context


def test_user_whitelist_filter() -> None:
    """Verify whitelist filter correctly permits or denies messages."""
    filter_obj = UserWhitelistFilter(allowed_user_ids={111222333})

    allowed_msg = MagicMock(spec=Message)
    allowed_msg.from_user = MagicMock(spec=User)
    allowed_msg.from_user.id = 111222333

    denied_msg = MagicMock(spec=Message)
    denied_msg.from_user = MagicMock(spec=User)
    denied_msg.from_user.id = 999999999

    no_user_msg = MagicMock(spec=Message)
    no_user_msg.from_user = None

    assert filter_obj.filter(allowed_msg) is True
    assert filter_obj.filter(denied_msg) is False
    assert filter_obj.filter(no_user_msg) is False


@pytest.mark.asyncio
async def test_start_command(mock_bot_context: MagicMock) -> None:
    """Verify /start returns formatted welcome message."""
    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(spec=User)
    update.effective_user.first_name = "Alice"
    update.effective_user.id = 111222333
    update.effective_message = MagicMock(spec=Message)
    update.effective_message.reply_text = AsyncMock()

    await start_command(update, mock_bot_context)

    update.effective_message.reply_text.assert_awaited_once()
    reply_call = update.effective_message.reply_text.call_args[0][0]
    assert "Welcome, Alice!" in reply_call
    assert "LifeStream Personal AI Assistant" in reply_call


@pytest.mark.asyncio
async def test_status_command(mock_bot_context: MagicMock) -> None:
    """Verify /status reports health and settings."""
    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = 111222333
    update.effective_message = MagicMock(spec=Message)
    update.effective_message.reply_text = AsyncMock()

    await status_command(update, mock_bot_context)

    update.effective_message.reply_text.assert_awaited_once()
    reply_call = update.effective_message.reply_text.call_args[0][0]
    assert "LifeStream Assistant System Status" in reply_call
    assert "gemini-3.8-flash" in reply_call


@pytest.mark.asyncio
async def test_sync_command(mock_bot_context: MagicMock) -> None:
    """Verify /sync runs event refresh."""
    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = 111222333
    update.effective_chat = MagicMock(spec=Chat)
    update.effective_chat.id = 12345
    update.effective_message = MagicMock(spec=Message)
    update.effective_message.reply_text = AsyncMock()

    await sync_command(update, mock_bot_context)

    update.effective_message.reply_text.assert_awaited_once()
    reply_call = update.effective_message.reply_text.call_args[0][0]
    assert "No new events to report" in reply_call


@pytest.mark.asyncio
async def test_text_message_handler(mock_bot_context: MagicMock) -> None:
    """Verify inbound text queries trigger runner and return reply."""
    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = 111222333
    update.effective_chat = MagicMock(spec=Chat)
    update.effective_chat.id = 12345
    update.effective_message = MagicMock(spec=Message)
    update.effective_message.text = "How much did I spend yesterday?"
    update.effective_message.reply_text = AsyncMock()

    await text_message_handler(update, mock_bot_context)

    runner = mock_bot_context.bot_data["agent_runner"]
    runner.handle_user_query.assert_awaited_once_with(
        user_id=111222333,
        query="How much did I spend yesterday?",
    )
    from unittest.mock import ANY
    update.effective_message.reply_text.assert_awaited_once_with(
        "Agent response to test query",
        parse_mode="Markdown",
        reply_markup=ANY,
    )


@pytest.mark.asyncio
async def test_photo_message_handler(mock_bot_context: MagicMock) -> None:
    """Verify inbound photo messages trigger OCR image analysis."""
    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = 111222333
    update.effective_chat = MagicMock(spec=Chat)
    update.effective_chat.id = 12345

    mock_photo_file = MagicMock()
    mock_photo_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"fake_jpeg_bytes"))

    mock_photo = MagicMock(spec=PhotoSize)
    mock_photo.get_file = AsyncMock(return_value=mock_photo_file)

    update.effective_message = MagicMock(spec=Message)
    update.effective_message.photo = [mock_photo]
    update.effective_message.caption = "Dinner receipt"
    update.effective_message.reply_text = AsyncMock()

    await photo_message_handler(update, mock_bot_context)

    runner = mock_bot_context.bot_data["agent_runner"]
    runner.handle_photo_analysis.assert_awaited_once_with(
        user_id=111222333,
        image_bytes=b"fake_jpeg_bytes",
        mime_type="image/jpeg",
        user_caption="Dinner receipt",
    )
    update.effective_message.reply_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_unauthorized_user_blocked() -> None:
    """Verify unauthorized handler blocks and replies with access denied."""
    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = 999999999
    update.effective_user.username = "intruder"
    update.effective_message = MagicMock(spec=Message)
    update.effective_message.reply_text = AsyncMock()

    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    await unauthorized_user_handler(update, context)

    update.effective_message.reply_text.assert_awaited_once()
    reply = update.effective_message.reply_text.call_args[0][0]
    assert "Access Denied" in reply


@pytest.mark.asyncio
async def test_bills_command(mock_bot_context: MagicMock) -> None:
    """Verify /bills command renders upcoming recurring payment schedule."""
    mock_monarch = MagicMock()
    mock_monarch.get_recurring_obligations = AsyncMock(return_value=[
        {
            "id": "rec-hyundai",
            "name": "Hyundai (Car Payment)",
            "category": "auto_loan",
            "amount": 256.28,
            "frequency": "monthly",
            "next_due_date": "2026-11-13",
            "is_income": False,
        },
        {
            "id": "rec-progressive",
            "name": "Progressive Auto Insurance",
            "category": "insurance",
            "amount": 404.00,
            "frequency": "monthly",
            "next_due_date": "2026-11-11",
            "is_income": False,
        },
    ])
    mock_monarch.get_accounts = AsyncMock(return_value=[])
    registry = mock_bot_context.bot_data["connector_registry"]
    registry.get.return_value = mock_monarch

    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = 111222333
    update.effective_chat = MagicMock(spec=Chat)
    update.effective_chat.id = 12345
    update.effective_message = MagicMock(spec=Message)
    update.effective_message.reply_text = AsyncMock()

    await bills_command(update, mock_bot_context)

    update.effective_message.reply_text.assert_awaited_once()
    reply = update.effective_message.reply_text.call_args[0][0]
    assert "Upcoming Payment Obligations" in reply
    assert "Hyundai" in reply
    assert "Progressive" in reply


def test_build_bot_application(test_settings: Settings, mock_gemini_client: GeminiClient) -> None:
    """Verify Telegram Application construction and dependency binding."""
    app = build_bot_application(
        settings=test_settings,
        gemini_client=mock_gemini_client,
    )
    assert app is not None
    assert "agent_runner" in app.bot_data
    assert "connector_registry" in app.bot_data
    assert "gemini_client" in app.bot_data
