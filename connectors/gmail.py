"""Pluggable mock connector for Gmail receipts and urgent alert streams."""

from datetime import datetime, timedelta, timezone
from typing import Any
from connectors.base import BaseConnector
from connectors.models import GmailAlert, LifeStreamType, StreamEvent
from connectors.sanitization import sanitize_payload, sanitize_text


class GmailConnector(BaseConnector):
    """Mock connector simulating Gmail inbound inbox monitoring."""

    def __init__(self, name: str = "gmail") -> None:
        super().__init__(name=name, stream_type=LifeStreamType.EMAIL)

    async def connect(self) -> None:
        """Simulate OAuth2 token handshake with Google Workspace API."""
        self.is_connected = True

    async def get_recent_alerts(self, limit: int = 5) -> list[GmailAlert]:
        """Generate realistic mock Gmail messages with PII scrubbing."""
        now = datetime.now(timezone.utc)
        raw_items = [
            {
                "message_id": "msg-901",
                "sender": "no-reply@united.com",
                "subject": "eTicket Confirmation - SFO to JFK (Flight UA 412)",
                "snippet": "Confirmation code: HK729L. Passenger: Nikita. Departs: Nov 12, 08:30 AM PST. Total: $489.20.",
                "received_at": now - timedelta(hours=1),
                "category": "travel",
                "is_starred": True,
            },
            {
                "message_id": "msg-902",
                "sender": "no-reply@accounts.google.com",
                "subject": "Security notice: LifeStream Assistant integration active",
                "snippet": "Your executive assistant connector was initialized securely.",
                "received_at": now - timedelta(hours=3),
                "category": "security",
                "is_starred": True,
            },
            {
                "message_id": "msg-903",
                "sender": "auto-confirm@amazon.com",
                "subject": "Delivered: Anker Prime 100W USB-C GaN Charger",
                "snippet": "Your package was handed to resident or left near front door. Track package with auth_token: sec_tok_99182371982.",
                "received_at": now - timedelta(hours=5),
                "category": "delivery",
                "is_starred": False,
            },
        ]

        alerts: list[GmailAlert] = []
        for raw in raw_items[:limit]:
            sanitized = sanitize_payload(raw)
            sanitized["snippet"] = sanitize_text(sanitized["snippet"])
            alerts.append(GmailAlert(**sanitized))

        return alerts

    async def fetch_events(self, limit: int = 10) -> list[StreamEvent]:
        """Convert inbound Gmail alerts into normalized StreamEvents."""
        alerts = await self.get_recent_alerts(limit=limit)
        events: list[StreamEvent] = []

        for alert in alerts:
            is_urgent = alert.category in {"security", "urgent"}
            events.append(
                StreamEvent(
                    id=f"gmail-{alert.message_id}",
                    stream_type=self.stream_type,
                    source=self.name,
                    timestamp=alert.received_at,
                    title=f"Email: {alert.subject}",
                    summary=f"From: {alert.sender} | {alert.snippet}",
                    raw_data=alert.model_dump(mode="json"),
                    is_urgent=is_urgent,
                    metadata={"category": alert.category, "starred": alert.is_starred},
                )
            )

        return events

    async def get_health(self) -> dict[str, Any]:
        """Return connector health status."""
        return {
            "connector": self.name,
            "connected": self.is_connected,
            "type": self.stream_type.value,
            "latency_ms": 18.2,
        }

    async def disconnect(self) -> None:
        """Simulate session teardown."""
        self.is_connected = False
