"""Unit tests for life-stream connectors, data models, and PII sanitization."""

import pytest
from connectors.base import ConnectorRegistry
from connectors.gmail import GmailConnector
from connectors.models import LifeStreamType, StreamEvent
from connectors.monarch import MonarchConnector
from connectors.sanitization import sanitize_payload, sanitize_text


def test_pii_sanitizer_credit_card() -> None:
    """Verify credit card numbers are masked preserving only last 4 digits."""
    raw = "Customer paid with Visa 4111222233334444 at store."
    sanitized = sanitize_text(raw)
    assert "4111222233334444" not in sanitized
    assert "****-****-****-4444" in sanitized


def test_pii_sanitizer_ssn() -> None:
    """Verify Social Security Numbers are replaced with [REDACTED_SSN]."""
    raw = "My SSN is 000-12-3456 on file."
    sanitized = sanitize_text(raw)
    assert "000-12-3456" not in sanitized
    assert "[REDACTED_SSN]" in sanitized


def test_pii_sanitizer_bank_account() -> None:
    """Verify raw bank account numbers are masked."""
    raw = "Checking transfer from account #987654321098."
    sanitized = sanitize_text(raw)
    assert "987654321098" not in sanitized
    assert "account ****1098" in sanitized


def test_pii_sanitizer_dict_payload() -> None:
    """Verify nested dictionary payload scrubbing for credentials and tokens."""
    payload = {
        "user": "nikita",
        "api_key": "sec_key_super_secret_token_123",
        "nested": {
            "password": "Password123!",
            "message": "Call bank on 4111222233334444",
        },
    }
    sanitized = sanitize_payload(payload)
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["nested"]["password"] == "[REDACTED]"
    assert "****-****-****-4444" in sanitized["nested"]["message"]


@pytest.mark.asyncio
async def test_monarch_connector_lifecycle_and_data() -> None:
    """Verify MonarchConnector connects, pulls sanitized transactions, and produces StreamEvents."""
    connector = MonarchConnector()
    await connector.connect()
    assert connector.is_connected is True

    accounts = await connector.get_accounts()
    assert len(accounts) >= 3
    assert any(a.name == "Chase Premier Checking" for a in accounts)

    txs = await connector.get_recent_transactions(limit=5)
    assert len(txs) > 0
    # Verify raw account number in notes was sanitized
    for tx in txs:
        if tx.notes:
            assert "49213840291" not in tx.notes

    events = await connector.fetch_events(limit=5)
    assert len(events) > 0
    assert all(e.stream_type == LifeStreamType.FINANCE for e in events)

    health = await connector.get_health()
    assert health["connected"] is True
    assert health["type"] == "finance"

    await connector.disconnect()
    assert connector.is_connected is False


@pytest.mark.asyncio
async def test_gmail_connector_lifecycle_and_alerts() -> None:
    """Verify GmailConnector returns structured alerts with PII scrubbed."""
    connector = GmailConnector()
    await connector.connect()
    assert connector.is_connected is True

    alerts = await connector.get_recent_alerts(limit=5)
    assert len(alerts) >= 3
    # Check travel alert
    travel_alert = next((a for a in alerts if a.category == "travel"), None)
    assert travel_alert is not None
    assert "UA 412" in travel_alert.subject

    events = await connector.fetch_events(limit=5)
    assert len(events) >= 3
    assert any(e.is_urgent for e in events)  # Security alert should be urgent

    health = await connector.get_health()
    assert health["connected"] is True

    await connector.disconnect()
    assert connector.is_connected is False


@pytest.mark.asyncio
async def test_connector_registry_fetch_all() -> None:
    """Verify ConnectorRegistry aggregates events across multiple connectors."""
    registry = ConnectorRegistry()
    registry.register(MonarchConnector())
    registry.register(GmailConnector())

    await registry.connect_all()
    events = await registry.fetch_all_events(limit_per_connector=5)

    assert len(events) >= 5
    types_found = {e.stream_type for e in events}
    assert LifeStreamType.FINANCE in types_found
    assert LifeStreamType.EMAIL in types_found
