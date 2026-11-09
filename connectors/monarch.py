"""Pluggable mock connector for Monarch Money financial stream."""

from datetime import datetime, timedelta, timezone
from typing import Any
from connectors.base import BaseConnector
from connectors.models import LifeStreamType, MonarchAccount, MonarchTransaction, StreamEvent
from connectors.sanitization import sanitize_payload, sanitize_text


class MonarchConnector(BaseConnector):
    """Mock connector simulating Monarch Money financial ingestion."""

    def __init__(self, name: str = "monarch") -> None:
        super().__init__(name=name, stream_type=LifeStreamType.FINANCE)

    async def connect(self) -> None:
        """Simulate authentication handshake with Monarch Money API."""
        self.is_connected = True

    async def get_accounts(self) -> list[MonarchAccount]:
        """Fetch current mock account balances."""
        now = datetime.now(timezone.utc)
        return [
            MonarchAccount(
                account_id="acc-chase-chk",
                name="Chase Premier Checking",
                type="checking",
                balance=5430.25,
                mask="****4921",
                updated_at=now,
            ),
            MonarchAccount(
                account_id="acc-marcus-hysa",
                name="Marcus High-Yield Savings",
                type="savings",
                balance=34850.00,
                mask="****8810",
                updated_at=now,
            ),
            MonarchAccount(
                account_id="acc-amex-gold",
                name="Amex Gold Card",
                type="credit",
                balance=-1280.45,
                mask="****1004",
                updated_at=now,
            ),
        ]

    async def get_recent_transactions(self, limit: int = 5) -> list[MonarchTransaction]:
        """Generate realistic mock transactions with automated PII sanitization."""
        now = datetime.now(timezone.utc)
        raw_items = [
            {
                "transaction_id": "tx-101",
                "merchant": "Whole Foods Market",
                "amount": 142.38,
                "category": "Groceries",
                "account_name": "Amex Gold Card",
                "account_mask": "****1004",
                "timestamp": now - timedelta(hours=2),
                "pending": True,
                "notes": "Weekly family grocery haul (account #49213840291)",  # Raw account to sanitize
            },
            {
                "transaction_id": "tx-102",
                "merchant": "Chevron Fuel",
                "amount": 58.75,
                "category": "Transportation",
                "account_name": "Chase Premier Checking",
                "account_mask": "****4921",
                "timestamp": now - timedelta(hours=8),
                "pending": False,
                "notes": "Full tank fill-up",
            },
            {
                "transaction_id": "tx-103",
                "merchant": "Employer Direct Deposit (Acme Corp)",
                "amount": -4250.00,  # Credit
                "category": "Income",
                "account_name": "Chase Premier Checking",
                "account_mask": "****4921",
                "timestamp": now - timedelta(days=1),
                "pending": False,
                "notes": "Bi-weekly salary payroll deposit",
            },
            {
                "transaction_id": "tx-104",
                "merchant": "Apple Services",
                "amount": 14.99,
                "category": "Subscriptions",
                "account_name": "Amex Gold Card",
                "account_mask": "****1004",
                "timestamp": now - timedelta(days=2),
                "pending": False,
                "notes": "iCloud+ 2TB storage subscription",
            },
        ]

        # Sanitize and convert to typed models
        transactions: list[MonarchTransaction] = []
        for raw in raw_items[:limit]:
            sanitized = sanitize_payload(raw)
            if sanitized.get("notes"):
                sanitized["notes"] = sanitize_text(sanitized["notes"])
            transactions.append(MonarchTransaction(**sanitized))

        return transactions

    async def fetch_events(self, limit: int = 10) -> list[StreamEvent]:
        """Convert financial transactions and balances into normalized StreamEvents."""
        txs = await self.get_recent_transactions(limit=limit)
        events: list[StreamEvent] = []

        for tx in txs:
            is_large = abs(tx.amount) > 500.0 and tx.amount > 0
            summary = (
                f"{tx.merchant}: ${abs(tx.amount):.2f} "
                f"[{tx.category}] via {tx.account_name} ({tx.account_mask})"
            )
            events.append(
                StreamEvent(
                    id=f"monarch-{tx.transaction_id}",
                    stream_type=self.stream_type,
                    source=self.name,
                    timestamp=tx.timestamp,
                    title=f"Transaction: {tx.merchant}",
                    summary=summary,
                    raw_data=tx.model_dump(mode="json"),
                    is_urgent=is_large,
                    metadata={"pending": tx.pending, "category": tx.category},
                )
            )

        return events

    async def get_health(self) -> dict[str, Any]:
        """Return connector health status."""
        return {
            "connector": self.name,
            "connected": self.is_connected,
            "type": self.stream_type.value,
            "latency_ms": 12.4,
        }

    async def disconnect(self) -> None:
        """Simulate session teardown."""
        self.is_connected = False
