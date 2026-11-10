"""Comprehensive unit tests for the UX presentation, styling, and feedback subsystem."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest

from connectors.models import MonarchAccount, MonarchTransaction, StreamEvent
from storage.db import DatabaseManager
from ux.feedback import (
    get_style_picker_keyboard,
    get_ux_feedback_keyboard,
    handle_ux_callback,
    ux_command,
)
from ux.layout import (
    format_alert_card,
    format_ascii_table,
    format_executive_response,
    format_financial_accounts,
    format_header,
    format_kpi_bar,
    format_transactions_card,
)
from ux.prompts import build_system_instruction
from ux.styles import UXStylePreset, get_style_config


def test_style_config_resolution():
    """Verify default and specific style config resolution."""
    cfg_exec = get_style_config("executive")
    assert cfg_exec.id == UXStylePreset.EXECUTIVE
    assert cfg_exec.include_insights is True

    cfg_mini = get_style_config(UXStylePreset.MINIMALIST)
    assert cfg_mini.id == UXStylePreset.MINIMALIST
    assert cfg_mini.include_salutation is False

    cfg_fallback = get_style_config("unknown_style")
    assert cfg_fallback.id == UXStylePreset.EXECUTIVE


def test_layout_formatting_components():
    """Verify ASCII table and KPI formatting without breaking Telegram parsing."""
    header = format_header(title="Portfolio Review", badge="FINANCES", emoji="💰")
    assert "💰 **[FINANCES] Portfolio Review**" in header

    kpi = format_kpi_bar([("Net Worth", "$42,500.00"), ("Cash", "$10,000.00")])
    assert "```text" in kpi
    assert "Net Worth: $42,500.00" in kpi

    # Monospace table
    table = format_ascii_table(
        headers=["Item", "Cost"],
        rows=[["Latte", "$5.50"], ["Gym", "$85.00"]],
    )
    assert "```text" in table
    assert "Latte" in table
    assert "─" in table


def test_financial_accounts_card():
    """Verify monospace financial table formatting with account masking."""
    accounts = [
        MonarchAccount(
            account_id="acc-1",
            name="Chase Checking",
            type="checking",
            balance=3500.50,
            mask="*1234",
            updated_at=datetime.now(timezone.utc),
        ),
        MonarchAccount(
            account_id="acc-2",
            name="Amex Gold",
            type="credit",
            balance=-450.00,
            mask="*5678",
            updated_at=datetime.now(timezone.utc),
        ),
    ]
    card = format_financial_accounts(accounts)
    assert "```text" in card
    assert "Chase Checking" in card
    assert "$3,500.50" in card
    assert "Total Net Worth" in card
    assert "$3,050.50" in card


def test_transactions_card():
    """Verify transaction cards are formatted concisely."""
    txs = [
        MonarchTransaction(
            transaction_id="t-1",
            merchant="Apple Store",
            amount=199.99,
            category="Electronics",
            account_name="Amex Gold",
            account_mask="*5678",
            timestamp=datetime(2026, 11, 9, 14, 30, tzinfo=timezone.utc),
        )
    ]
    card = format_transactions_card(txs)
    assert "```text" in card
    assert "Apple Store" in card
    assert "$199.99" in card


def test_format_executive_response():
    """Verify end-to-end executive response assembly."""
    response = format_executive_response(
        title="Emergency Fund Assessment",
        summary="Liquid reserves exceed the 6-month safety threshold.",
        body="Current total cash is allocated across checking and high-yield savings.",
        insights=["Maintain existing automated transfer schedule.", "Review yield on Marcus HYSA."],
        metrics=[("Coverage", "7.4 mos"), ("Cash", "$34,850.00")],
        badge="AUDIT",
        model_name="gpt-6.1-terra",
        tokens=150,
        cost=0.00045,
    )
    assert "🎩 **[AUDIT] Emergency Fund Assessment**" in response
    assert "📌 **Summary**:" in response
    assert "Coverage: 7.4 mos" in response
    assert "💡 **Executive Takeaways**:" in response
    assert "Model: `gpt-6.1-terra`" in response


def test_prompts_system_instruction():
    """Verify dynamic system instruction contains UX rules."""
    exec_inst = build_system_instruction("executive")
    assert "TELEGRAM UX & PRESENTATION FORMATTING RULES" in exec_inst
    assert "EXECUTIVE BUTLER" in exec_inst

    mini_inst = build_system_instruction("minimalist")
    assert "MINIMALIST DASHBOARD" in mini_inst


@pytest.mark.asyncio
async def test_ux_database_persistence(tmp_path):
    """Verify UX feedback and user style preferences are recorded and retrieved."""
    db_file = tmp_path / "test_ux.db"
    db = DatabaseManager(db_path=str(db_file))

    # Test style preferences
    default_style = await db.get_user_ux_style(1116928631)
    assert default_style == "executive"

    await db.set_user_ux_style(1116928631, "minimalist")
    updated_style = await db.get_user_ux_style(1116928631)
    assert updated_style == "minimalist"

    # Test feedback recording
    fid = await db.save_ux_feedback(
        user_id=1116928631,
        rating="positive",
        note="Table layout looks sharp",
        message_snippet="Portfolio balances",
        style_preset="minimalist",
    )
    assert fid > 0

    stats = await db.get_ux_feedback_stats()
    assert stats["counts"].get("positive") == 1
    assert len(stats["recent"]) == 1


@pytest.mark.asyncio
async def test_ux_callback_rating(tmp_path):
    """Verify rating button callbacks record feedback in database."""
    db_file = tmp_path / "test_callback.db"
    db = DatabaseManager(db_path=str(db_file))

    mock_query = AsyncMock()
    mock_query.data = "ux_rate:pos:test_ctx"
    mock_query.message = AsyncMock()
    mock_query.message.text = "Sample response text"

    update = MagicMock()
    update.callback_query = mock_query
    update.effective_user.id = 1116928631

    context = MagicMock()
    runner_mock = MagicMock()
    runner_mock.db = db
    context.bot_data = {"agent_runner": runner_mock}

    handled = await handle_ux_callback(update, context)
    assert handled is True
    mock_query.answer.assert_awaited_once()

    stats = await db.get_ux_feedback_stats()
    assert stats["counts"].get("positive") == 1


@pytest.mark.asyncio
async def test_ux_callback_style_switch(tmp_path):
    """Verify switching style via inline button persists new preset."""
    db_file = tmp_path / "test_style_switch.db"
    db = DatabaseManager(db_path=str(db_file))

    mock_query = AsyncMock()
    mock_query.data = "ux_set_style:analytical"
    mock_query.message = AsyncMock()

    update = MagicMock()
    update.callback_query = mock_query
    update.effective_user.id = 1116928631

    context = MagicMock()
    runner_mock = MagicMock()
    runner_mock.db = db
    context.bot_data = {"agent_runner": runner_mock}

    handled = await handle_ux_callback(update, context)
    assert handled is True

    style = await db.get_user_ux_style(1116928631)
    assert style == "analytical"
