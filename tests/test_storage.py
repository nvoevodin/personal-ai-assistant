"""Unit tests for SQLite conversation memory and receipt database."""

import os
import pytest
from storage.db import DatabaseManager


@pytest.fixture
def temp_db(tmp_path: pytest.TempPathFactory) -> DatabaseManager:
    """Create an isolated test database in a temporary directory."""
    db_file = tmp_path / "test_assistant.db"  # type: ignore[operator]
    return DatabaseManager(db_path=str(db_file))


@pytest.mark.asyncio
async def test_conversation_history_lifecycle(temp_db: DatabaseManager) -> None:
    """Verify adding messages and retrieving recent turns in chronological order."""
    user_id = 12345
    await temp_db.save_message(user_id=user_id, role="user", content="Hello!")
    await temp_db.save_message(user_id=user_id, role="assistant", content="Hello! How can I help?")
    await temp_db.save_message(user_id=user_id, role="user", content="What is my spending?")

    messages = await temp_db.get_recent_messages(user_id=user_id, limit=10)
    assert len(messages) == 3
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Hello!"
    assert messages[1]["role"] == "assistant"
    assert messages[2]["role"] == "user"
    assert messages[2]["content"] == "What is my spending?"


@pytest.mark.asyncio
async def test_receipt_storage_and_search(temp_db: DatabaseManager) -> None:
    """Verify saving receipts and searching by merchant/category."""
    user_id = 999
    receipt_id = await temp_db.save_receipt(
        user_id=user_id,
        merchant="Trader Joe's",
        total_amount=56.40,
        currency="USD",
        tax_amount=4.20,
        receipt_date="2026-11-05",
        category="Groceries",
        items=[{"name": "Organic Apples", "price": 4.99}],
        raw_summary="Trader Joe's groceries total $56.40",
    )
    assert receipt_id > 0

    # Search by merchant
    results = await temp_db.search_receipts(user_id=user_id, query="trader")
    assert len(results) == 1
    assert results[0]["merchant"] == "Trader Joe's"
    assert results[0]["total_amount"] == 56.40

    # Search by category
    cat_results = await temp_db.search_receipts(user_id=user_id, query="groceries")
    assert len(cat_results) == 1

    # Search non-matching
    no_results = await temp_db.search_receipts(user_id=user_id, query="BestBuy")
    assert len(no_results) == 0


@pytest.mark.asyncio
async def test_spending_summary_aggregation(temp_db: DatabaseManager) -> None:
    """Verify aggregation across period days and categories."""
    user_id = 555
    await temp_db.save_receipt(
        user_id=user_id,
        merchant="Store A",
        total_amount=100.0,
        category="Shopping",
    )
    await temp_db.save_receipt(
        user_id=user_id,
        merchant="Store B",
        total_amount=50.0,
        category="Dining",
    )

    summary = await temp_db.get_spending_summary(user_id=user_id, days=7)
    assert summary["receipt_count"] == 2
    assert summary["total_spent"] == 150.0
    assert summary["categories"]["Shopping"] == 100.0
    assert summary["categories"]["Dining"] == 50.0


@pytest.mark.asyncio
async def test_payment_obligations_storage(temp_db: DatabaseManager) -> None:
    """Verify upserting and retrieving recurring payment obligations and car payment dates."""
    await temp_db.upsert_payment_obligation(
        obligation_id="rec-hyundai",
        name="Hyundai (Car Payment)",
        category="auto_loan",
        amount=256.28,
        frequency="monthly",
        due_day_of_month=13,
        next_due_date="2026-11-13",
        notes="Auto financing installment",
    )
    await temp_db.upsert_payment_obligation(
        obligation_id="rec-progressive",
        name="Progressive Auto Insurance",
        category="insurance",
        amount=404.00,
        frequency="monthly",
        due_day_of_month=11,
        next_due_date="2026-11-11",
        notes="Vehicle coverage",
    )

    obligations = await temp_db.get_upcoming_payment_obligations(limit=10)
    assert len(obligations) == 2
    # Chronological sort: Progressive (Nov 11) before Hyundai (Nov 13)
    assert obligations[0]["name"] == "Progressive Auto Insurance"
    assert obligations[0]["amount"] == 404.00
    assert obligations[0]["next_due_date"] == "2026-11-11"
    assert obligations[1]["name"] == "Hyundai (Car Payment)"
    assert obligations[1]["amount"] == 256.28
    assert obligations[1]["next_due_date"] == "2026-11-13"
