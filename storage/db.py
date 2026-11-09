"""SQLite asynchronous persistence layer for conversation history and receipt management."""

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "data/assistant.db"


class DatabaseManager:
    """Manages SQLite storage for conversational memory and scanned receipts."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        # Ensure parent directory exists
        parent_dir = os.path.dirname(self.db_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)
        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        """Establish SQLite connection with foreign keys and dict-like rows."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        """Initialize database schema tables and indexes."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 1. Conversation history table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                    content TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_conv_user_timestamp
                ON conversation_history (user_id, timestamp DESC);
            """)

            # 2. Receipts and OCR expense table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS receipts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    merchant TEXT NOT NULL,
                    total_amount REAL NOT NULL,
                    currency TEXT NOT NULL DEFAULT 'USD',
                    tax_amount REAL DEFAULT 0.0,
                    receipt_date TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'General',
                    items_json TEXT DEFAULT '[]',
                    raw_summary TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_receipts_user_date
                ON receipts (user_id, receipt_date DESC);
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_receipts_merchant
                ON receipts (user_id, merchant);
            """)
            conn.commit()

    async def save_message(self, user_id: int, role: str, content: str) -> None:
        """Persist a conversation turn asynchronously."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO conversation_history (user_id, role, content) VALUES (?, ?, ?);",
                (user_id, role, content),
            )
            conn.commit()

    async def get_recent_messages(self, user_id: int, limit: int = 8) -> list[dict[str, str]]:
        """Retrieve recent chronological conversation turns for context injection."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT role, content
                FROM conversation_history
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?;
                """,
                (user_id, limit),
            )
            rows = cursor.fetchall()
            # Return in chronological order
            return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

    async def save_receipt(
        self,
        user_id: int,
        merchant: str,
        total_amount: float,
        currency: str = "USD",
        tax_amount: float = 0.0,
        receipt_date: str | None = None,
        category: str = "General",
        items: list[dict[str, Any]] | None = None,
        raw_summary: str = "",
    ) -> int:
        """Store an OCR-parsed receipt."""
        date_str = receipt_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        items_payload = json.dumps(items or [])

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO receipts (
                    user_id, merchant, total_amount, currency, tax_amount,
                    receipt_date, category, items_json, raw_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    user_id,
                    merchant,
                    float(total_amount),
                    currency.upper(),
                    float(tax_amount),
                    date_str,
                    category,
                    items_payload,
                    raw_summary,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0

    async def search_receipts(
        self,
        user_id: int,
        query: str = "",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search receipts by merchant name or category."""
        clean_query = f"%{query.strip().lower()}%"
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if query.strip():
                cursor.execute(
                    """
                    SELECT id, merchant, total_amount, currency, tax_amount,
                           receipt_date, category, raw_summary, created_at
                    FROM receipts
                    WHERE user_id = ? AND (LOWER(merchant) LIKE ? OR LOWER(category) LIKE ?)
                    ORDER BY receipt_date DESC
                    LIMIT ?;
                    """,
                    (user_id, clean_query, clean_query, limit),
                )
            else:
                cursor.execute(
                    """
                    SELECT id, merchant, total_amount, currency, tax_amount,
                           receipt_date, category, raw_summary, created_at
                    FROM receipts
                    WHERE user_id = ?
                    ORDER BY receipt_date DESC
                    LIMIT ?;
                    """,
                    (user_id, limit),
                )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_spending_summary(self, user_id: int, days: int = 30) -> dict[str, Any]:
        """Aggregate total scanned expenditure and categories over recent days."""
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT SUM(total_amount) as total_spent, COUNT(id) as receipt_count
                FROM receipts
                WHERE user_id = ? AND receipt_date >= ?;
                """,
                (user_id, cutoff_date),
            )
            summary_row = cursor.fetchone()
            total_spent = summary_row["total_spent"] if summary_row and summary_row["total_spent"] else 0.0
            receipt_count = summary_row["receipt_count"] if summary_row else 0

            # Group by category
            cursor.execute(
                """
                SELECT category, SUM(total_amount) as category_spent
                FROM receipts
                WHERE user_id = ? AND receipt_date >= ?
                GROUP BY category
                ORDER BY category_spent DESC;
                """,
                (user_id, cutoff_date),
            )
            cat_rows = cursor.fetchall()
            category_breakdown = {row["category"]: round(row["category_spent"], 2) for row in cat_rows}

            return {
                "period_days": days,
                "total_spent": round(total_spent, 2),
                "receipt_count": receipt_count,
                "categories": category_breakdown,
            }
