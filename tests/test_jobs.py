"""Unit tests for background APScheduler jobs."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest

from bot.jobs import poll_and_triage_streams, send_daily_executive_briefing
from connectors.models import LifeStreamType, MonarchAccount, StreamEvent
from core.dispatcher import TriageResult
from storage.db import DatabaseManager


@pytest.mark.asyncio
async def test_poll_and_triage_streams_suppresses_already_processed(tmp_path):
    """Verify that events already in the database are not re-evaluated or alerted."""
    db_file = tmp_path / "test_jobs.db"
    db = DatabaseManager(db_path=str(db_file))

    # Pre-mark event as processed
    await db.mark_event_processed(
        event_id="ev-123",
        source="monarch",
        title="Existing charge",
        summary="Old charge",
        category="finance",
        urgency="low",
        notified=False,
    )

    ev = StreamEvent(
        id="ev-123",
        stream_type=LifeStreamType.FINANCE,
        source="monarch",
        timestamp=datetime.now(timezone.utc),
        title="Existing charge",
        summary="Old charge",
        raw_data={},
        is_urgent=False,
    )

    registry_mock = MagicMock()
    registry_mock.fetch_all_events = AsyncMock(return_value=[ev])

    runner_mock = MagicMock()
    runner_mock.db = db
    runner_mock.dispatcher = MagicMock()
    runner_mock.dispatcher._settings.openai_api_key_value = "sk-test"

    settings_mock = MagicMock()
    settings_mock.allowed_telegram_user_ids = [1116928631]

    context = MagicMock()
    context.bot_data = {
        "agent_runner": runner_mock,
        "connector_registry": registry_mock,
        "settings": settings_mock,
    }
    context.bot.send_message = AsyncMock()

    await poll_and_triage_streams(context)

    # Event was already processed, so no message should be sent
    context.bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_poll_and_triage_streams_sends_alert_on_high_urgency(tmp_path):
    """Verify that a high urgency event identified by Tier 1 triage alerts the user."""
    db_file = tmp_path / "test_jobs_urgent.db"
    db = DatabaseManager(db_path=str(db_file))

    ev = StreamEvent(
        id="ev-new-urgent",
        stream_type=LifeStreamType.FINANCE,
        source="monarch",
        timestamp=datetime.now(timezone.utc),
        title="Wire Transfer",
        summary="Unusual wire transfer of $5,000",
        raw_data={},
        is_urgent=True,
    )

    registry_mock = MagicMock()
    registry_mock.fetch_all_events = AsyncMock(return_value=[ev])

    runner_mock = MagicMock()
    runner_mock.db = db
    runner_mock.dispatcher = MagicMock()
    runner_mock.dispatcher._settings.openai_api_key_value = "sk-test"
    runner_mock.dispatcher.evaluate_background_event = AsyncMock(
        return_value=TriageResult(
            should_notify=True,
            summary="Wire transfer of $5,000 detected.",
            urgency="high",
            category="finance",
        )
    )

    settings_mock = MagicMock()
    settings_mock.allowed_telegram_user_ids = [1116928631]

    context = MagicMock()
    context.bot_data = {
        "agent_runner": runner_mock,
        "connector_registry": registry_mock,
        "settings": settings_mock,
    }
    context.bot.send_message = AsyncMock()

    await poll_and_triage_streams(context)

    # Alert should have been delivered to the user
    context.bot.send_message.assert_awaited_once()
    call_args = context.bot.send_message.call_args.kwargs
    assert call_args["chat_id"] == 1116928631
    assert "Wire transfer of $5,000 detected." in call_args["text"]

    # Verify marked as processed in DB
    assert await db.is_event_processed("ev-new-urgent") is True


@pytest.mark.asyncio
async def test_poll_and_triage_streams_sends_proactive_bill_reminder(tmp_path):
    """Verify that an obligation due tomorrow triggers a proactive alert."""
    import datetime
    db_file = tmp_path / "test_jobs_bill.db"
    db = DatabaseManager(db_path=str(db_file))

    tomorrow = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    await db.upsert_payment_obligation(
        obligation_id="stmt-hyundai-car-loan",
        name="Hyundai Ioniq 5 (Car Payment)",
        category="auto_loan",
        amount=256.28,
        frequency="monthly",
        next_due_date=tomorrow,
        autopay=True,
    )

    registry_mock = MagicMock()
    registry_mock.fetch_all_events = AsyncMock(return_value=[])
    registry_mock.get.return_value = None

    runner_mock = MagicMock()
    runner_mock.db = db
    runner_mock.dispatcher = None

    settings_mock = MagicMock()
    settings_mock.allowed_telegram_user_ids = [1116928631]

    context = MagicMock()
    context.bot_data = {
        "agent_runner": runner_mock,
        "connector_registry": registry_mock,
        "settings": settings_mock,
    }
    context.bot.send_message = AsyncMock()

    await poll_and_triage_streams(context)

    context.bot.send_message.assert_awaited_once()
    call_args = context.bot.send_message.call_args.kwargs
    assert call_args["chat_id"] == 1116928631
    assert "Executive Bill Reminder" in call_args["text"]
    assert "Hyundai Ioniq 5" in call_args["text"]
    assert "Tomorrow" in call_args["text"]
