"""Pluggable connector for Monarch Money financial stream supporting live API & demo fallback."""

import logging
import os
import ssl
from datetime import datetime, timedelta, timezone
from typing import Any
import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())

from connectors.base import BaseConnector
from connectors.models import LifeStreamType, MonarchAccount, MonarchTransaction, StreamEvent
from connectors.sanitization import sanitize_payload, sanitize_text

# Update Monarch endpoint to new production domain to avoid 301 redirects
from monarchmoney.monarchmoney import MonarchMoneyEndpoints
MonarchMoneyEndpoints.BASE_URL = "https://api.monarch.com"

logger = logging.getLogger(__name__)


class MonarchConnector(BaseConnector):
    """Monarch Money financial connector with live session token, browser cookie, and mock fallback."""

    def __init__(
        self,
        name: str = "monarch",
        token: str | None = None,
        cookie: str | None = None,
        email: str | None = None,
        password: str | None = None,
        mfa_secret: str | None = None,
    ) -> None:
        super().__init__(name=name, stream_type=LifeStreamType.FINANCE)
        self.token = token
        self.cookie = cookie
        self.email = email
        self.password = password
        self.mfa_secret = mfa_secret
        self._client: Any = None

    async def connect(self) -> None:
        """Establish connection with Monarch Money API using cookie, credentials, or session token."""
        from monarchmoney import MonarchMoney

        # Priority 1: Authenticated browser cookie session
        if self.cookie and self.cookie.strip() and "session_id" in self.cookie:
            try:
                client = MonarchMoney()
                await client.login_with_cookies(self.cookie.strip())
                self._client = client
                self.is_connected = True
                logger.info("MonarchConnector successfully authenticated via live browser cookie session.")
                return
            except Exception as exc:
                logger.warning(
                    "Monarch cookie authentication failed (%s); checking credentials or fallback.",
                    exc,
                )

        # Priority 2: Automated credentials with hands-free MFA secret
        if self.email and self.password:
            try:
                client = MonarchMoney()
                await client.login(
                    email=self.email,
                    password=self.password,
                    mfa_secret_key=self.mfa_secret,
                    use_saved_session=True,
                    save_session=True,
                )
                self._client = client
                self.is_connected = True
                logger.info("MonarchConnector authenticated hands-free via email + password + MFA.")
                return
            except Exception as exc:
                logger.warning(
                    "Monarch automated login failed (%s); checking token or mock fallback.",
                    exc,
                )

        # Priority 3: Session token
        if self.token and self.token != "your_token_here":
            try:
                client = MonarchMoney()
                client.set_token(self.token)
                self._client = client
                self.is_connected = True
                logger.info("MonarchConnector successfully authenticated with live session token.")
                return
            except Exception as exc:
                logger.warning(
                    "Failed to authenticate with live Monarch API via token: %s; falling back to demo mode.",
                    exc,
                )
                self._client = None

        self.is_connected = True
        logger.info("MonarchConnector initialized in mock demo mode.")

    async def get_accounts(self) -> list[MonarchAccount]:
        """Fetch account balances from live Monarch API, or fallback to mock data."""
        if self._client:
            try:
                res = await self._client.get_accounts()
                raw_accounts = res.get("accounts", [])
                accounts: list[MonarchAccount] = []
                for raw in raw_accounts:
                    type_info = raw.get("type") or {}
                    type_name = type_info.get("display") or type_info.get("name") or "other"
                    raw_mask = raw.get("mask") or "****"
                    mask = raw_mask if raw_mask.startswith("*") else f"****{raw_mask[-4:]}"
                    accounts.append(
                        MonarchAccount(
                            account_id=str(raw.get("id")),
                            name=str(raw.get("displayName") or "Account"),
                            type=type_name.lower(),
                            balance=float(raw.get("currentBalance") or 0.0),
                            mask=mask,
                            updated_at=datetime.now(timezone.utc),
                        )
                    )
                return accounts
            except Exception as exc:
                logger.error("Live Monarch get_accounts failed: %s; falling back to demo.", exc)

        # Fallback Mock Data
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
        """Fetch transactions from live Monarch API, or fallback to mock data."""
        if self._client:
            try:
                res = await self._client.get_transactions(limit=limit)
                all_tx = res.get("allTransactions", {}).get("results", [])
                txs: list[MonarchTransaction] = []
                for raw in all_tx:
                    m_info = raw.get("merchant") or {}
                    merchant_name = m_info.get("name") or raw.get("plaidName") or "Unknown Merchant"
                    cat_info = raw.get("category") or {}
                    cat_name = cat_info.get("name") or "General"
                    acct_info = raw.get("account") or {}
                    acct_name = acct_info.get("displayName") or "Account"

                    ts = datetime.now(timezone.utc)
                    if raw.get("date"):
                        try:
                            ts = datetime.fromisoformat(raw["date"]).replace(tzinfo=timezone.utc)
                        except Exception:
                            pass

                    raw_item = {
                        "transaction_id": str(raw.get("id")),
                        "merchant": merchant_name,
                        "amount": float(raw.get("amount") or 0.0),
                        "category": cat_name,
                        "account_name": acct_name,
                        "account_mask": "****",
                        "timestamp": ts,
                        "pending": bool(raw.get("pending")),
                        "notes": raw.get("notes") or "",
                    }
                    sanitized = sanitize_payload(raw_item)
                    if sanitized.get("notes"):
                        sanitized["notes"] = sanitize_text(sanitized["notes"])
                    txs.append(MonarchTransaction(**sanitized))
                return txs
            except Exception as exc:
                logger.error("Live Monarch get_transactions failed: %s; falling back to demo.", exc)

        # Fallback Mock Data
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
                "notes": "Weekly family grocery haul (account #49213840291)",
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
                "amount": -4250.00,
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

    async def get_recurring_obligations(self) -> list[dict[str, Any]]:
        """Fetch recurring bills, auto loans, insurance, and subscription payment dates."""
        if not self._client:
            return [
                {
                    "id": "monarch-rec-hyundai",
                    "name": "Hyundai (Car Payment)",
                    "category": "auto_loan",
                    "amount": 256.28,
                    "frequency": "monthly",
                    "next_due_date": "2026-11-13",
                    "due_day_of_month": 13,
                    "is_income": False,
                    "notes": "Auto loan monthly financing installment",
                },
                {
                    "id": "monarch-rec-progressive",
                    "name": "Progressive Auto Insurance",
                    "category": "insurance",
                    "amount": 404.00,
                    "frequency": "monthly",
                    "next_due_date": "2026-11-11",
                    "due_day_of_month": 11,
                    "is_income": False,
                    "notes": "Vehicle insurance monthly premium",
                },
            ]

        try:
            res = await self._client.get_recurring_transaction_streams()
            streams = res.get("recurringTransactionStreams", [])
            obligations: list[dict[str, Any]] = []
            for item in streams:
                st = item.get("stream") or {}
                if not st.get("isActive", True):
                    continue
                name = st.get("name") or "Recurring Bill"
                amt = float(st.get("amount") or 0.0)
                is_income = st.get("recurringType") == "income" or amt > 0
                abs_amt = abs(amt)
                freq = st.get("frequency") or "monthly"
                next_tx = item.get("nextForecastedTransaction") or {}
                next_date = next_tx.get("date") or st.get("baseDate")

                cat = "general"
                lower_name = name.lower()
                if "hyundai" in lower_name or "auto" in lower_name or "car" in lower_name:
                    cat = "auto_loan"
                elif "progressive" in lower_name or "geico" in lower_name or "state farm" in lower_name:
                    cat = "insurance"
                elif is_income:
                    cat = "income"
                elif any(u in lower_name for u in ["power", "light", "water", "electric", "gas", "utility"]):
                    cat = "utilities"
                elif any(i in lower_name for i in ["internet", "frontier", "verizon", "at&t", "comcast", "spectrum"]):
                    cat = "internet"
                elif any(s in lower_name for s in ["google", "netflix", "spotify", "apple", "gym", "fit"]):
                    cat = "subscription"

                obligations.append({
                    "id": f"monarch-rec-{st.get('id', name.lower().replace(' ', '-'))}",
                    "name": f"{name} (Car Payment)" if cat == "auto_loan" and "car" not in lower_name else name,
                    "category": cat,
                    "amount": abs_amt,
                    "frequency": freq,
                    "next_due_date": next_date,
                    "is_income": is_income,
                    "notes": f"Monarch Money recurring stream ({freq})",
                })
            return obligations
        except Exception as exc:
            logger.error("Failed fetching recurring streams from Monarch API: %s", exc)
            return []

    async def get_health(self) -> dict[str, Any]:
        """Return connector health status."""
        return {
            "connector": self.name,
            "connected": self.is_connected,
            "is_live": self._client is not None,
            "type": self.stream_type.value,
            "latency_ms": 12.4,
        }

    async def disconnect(self) -> None:
        """Simulate session teardown."""
        self._client = None
        self.is_connected = False
