"""Production Gmail connector for live inbound inbox monitoring and receipt triage."""

import asyncio
from datetime import datetime, timezone
import email
import email.message
from email.header import decode_header
import imaplib
import logging
import os
import re
import ssl
from typing import Any
import certifi

from connectors.base import BaseConnector
from connectors.models import GmailAlert, LifeStreamType, StreamEvent
from connectors.sanitization import sanitize_payload, sanitize_text

logger = logging.getLogger(__name__)

GMAIL_IMAP_HOST = "imap.gmail.com"
GMAIL_IMAP_PORT = 993


def _decode_mime_header(header_value: str | None) -> str:
    """Safely decode RFC 2047 MIME-encoded email headers."""
    if not header_value:
        return ""
    try:
        decoded_fragments = decode_header(header_value)
        text_parts = []
        for content, encoding in decoded_fragments:
            if isinstance(content, bytes):
                encoding = encoding or "utf-8"
                try:
                    text_parts.append(content.decode(encoding, errors="replace"))
                except (LookupError, UnicodeDecodeError):
                    text_parts.append(content.decode("utf-8", errors="replace"))
            else:
                text_parts.append(str(content))
        return " ".join(text_parts).strip()
    except Exception:
        return str(header_value)


def _categorize_email(sender: str, subject: str, snippet: str) -> str:
    """Categorize incoming email based on high-signal keywords."""
    combined = f"{sender} {subject} {snippet}".lower()

    if any(k in combined for k in ["flight", "eticket", "airline", "boarding pass", "united", "delta", "american airlines", "alaska air", "hotel", "airbnb", "reservation", "booking confirmation"]):
        return "travel"
    if any(k in combined for k in ["receipt", "invoice", "order confirmed", "purchase", "payment received", "billing", "charged", "your order of"]):
        return "receipt"
    if any(k in combined for k in ["shipped", "tracking", "out for delivery", "delivered", "fedex", "ups", "usps", "dhl", "package"]):
        return "delivery"
    if any(k in combined for k in ["security alert", "password reset", "unauthorized", "verification code", "2-step", "new sign-in"]):
        return "security"
    return "general"


def _extract_text_body(msg: email.message.Message, max_chars: int = 500) -> str:
    """Extract and sanitize plain text from an email message structure."""
    body_parts = []
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            if content_type == "text/plain" and "attachment" not in content_disposition:
                payload = part.get_payload(decode=True)
                if payload:
                    body_parts.append(payload.decode("utf-8", errors="replace"))
            elif content_type == "text/html" and not body_parts and "attachment" not in content_disposition:
                payload = part.get_payload(decode=True)
                if payload:
                    raw_html = payload.decode("utf-8", errors="replace")
                    clean_text = re.sub(r"<[^>]+>", " ", raw_html)
                    body_parts.append(clean_text)
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            text = payload.decode("utf-8", errors="replace")
            if msg.get_content_type() == "text/html":
                text = re.sub(r"<[^>]+>", " ", text)
            body_parts.append(text)

    raw_text = " ".join(" ".join(body_parts).split())
    return raw_text[:max_chars].strip()


class GmailConnector(BaseConnector):
    """Production Gmail connector with live SSL IMAP inbox monitoring and PII sanitization."""

    def __init__(
        self,
        name: str = "gmail",
        email_address: str | None = None,
        app_password: str | None = None,
        folder: str = "INBOX",
    ) -> None:
        super().__init__(name=name, stream_type=LifeStreamType.EMAIL)
        self.email_address = email_address
        self.app_password = app_password
        self.folder = folder

    def _sync_connect_and_fetch(self, limit: int = 10) -> list[dict[str, Any]]:
        """Synchronous IMAP execution designed to run in background thread."""
        if not self.email_address or not self.app_password:
            logger.debug("Gmail credentials not provided; skipping IMAP connection.")
            return []

        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        mail = None
        results = []
        try:
            logger.info("Connecting to Gmail IMAP [%s] as %s...", GMAIL_IMAP_HOST, self.email_address)
            mail = imaplib.IMAP4_SSL(GMAIL_IMAP_HOST, GMAIL_IMAP_PORT, ssl_context=ssl_ctx)
            mail.login(self.email_address, self.app_password)
            mail.select(self.folder, readonly=True)

            status, search_data = mail.search(None, "ALL")
            if status != "OK" or not search_data or not search_data[0]:
                return []

            message_ids = search_data[0].split()
            recent_ids = message_ids[-limit:]
            recent_ids.reverse()

            for msg_id in recent_ids:
                try:
                    res_status, msg_data = mail.fetch(msg_id, "(RFC822)")
                    if res_status != "OK" or not msg_data:
                        continue

                    raw_email_bytes = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email_bytes)

                    sender = _decode_mime_header(msg.get("From", "Unknown"))
                    subject = _decode_mime_header(msg.get("Subject", "(No Subject)"))
                    date_header = msg.get("Date", "")

                    received_at = datetime.now(timezone.utc)
                    try:
                        parsed_date = email.utils.parsedate_to_datetime(date_header)
                        if parsed_date:
                            received_at = parsed_date.astimezone(timezone.utc)
                    except Exception:
                        pass

                    snippet = _extract_text_body(msg)
                    category = _categorize_email(sender=sender, subject=subject, snippet=snippet)

                    results.append({
                        "message_id": msg_id.decode("utf-8", errors="replace"),
                        "sender": sender,
                        "subject": subject,
                        "snippet": snippet,
                        "received_at": received_at,
                        "category": category,
                        "is_starred": False,
                    })
                except Exception as parse_err:
                    logger.warning("Error parsing Gmail message ID %s: %s", msg_id, parse_err)
                    continue

        except imaplib.IMAP4.error as imap_err:
            logger.error("Gmail IMAP authentication or protocol error: %s", imap_err)
        except Exception as exc:
            logger.error("Unexpected error connecting to Gmail: %s", exc)
        finally:
            if mail:
                try:
                    mail.close()
                    mail.logout()
                except Exception:
                    pass

        return results

    async def connect(self) -> None:
        """Validate Gmail credentials and establish readiness."""
        if self.email_address and self.app_password:
            try:
                ssl_ctx = ssl.create_default_context(cafile=certifi.where())
                def _test_login():
                    with imaplib.IMAP4_SSL(GMAIL_IMAP_HOST, GMAIL_IMAP_PORT, ssl_context=ssl_ctx) as m:
                        m.login(self.email_address, self.app_password)
                        return True
                self.is_connected = await asyncio.to_thread(_test_login)
                logger.info("GmailConnector authenticated live for %s.", self.email_address)
            except Exception as exc:
                logger.warning("Gmail live authentication failed (%s). Check credentials in .env.", exc)
                self.is_connected = False
        else:
            self.is_connected = False
            logger.info("GmailConnector initialized without credentials (dormant).")

    async def get_recent_alerts(self, limit: int = 5) -> list[GmailAlert]:
        """Fetch real emails via IMAP with PII scrubbing. Returns empty list if unconfigured."""
        if not self.email_address or not self.app_password:
            return []

        raw_items = await asyncio.to_thread(self._sync_connect_and_fetch, limit=limit)
        alerts: list[GmailAlert] = []

        for raw in raw_items:
            sanitized = sanitize_payload(raw)
            sanitized["snippet"] = sanitize_text(sanitized.get("snippet", ""))
            sanitized["subject"] = sanitize_text(sanitized.get("subject", ""))
            alerts.append(GmailAlert(**sanitized))

        return alerts

    async def fetch_events(self, limit: int = 10) -> list[StreamEvent]:
        """Convert real inbound Gmail emails into normalized StreamEvents."""
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
            "account": self.email_address if self.email_address else None,
            "type": self.stream_type.value,
            "is_live": bool(self.email_address and self.app_password),
        }

    async def disconnect(self) -> None:
        """Teardown connector state."""
        self.is_connected = False
