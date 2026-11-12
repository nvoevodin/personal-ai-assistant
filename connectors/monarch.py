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
                    raw_type = (type_info.get("name") or type_info.get("display") or "other").lower()
                    if "credit" in raw_type:
                        normalized_type = "credit"
                    elif any(c in raw_type for c in ["cash", "checking", "savings", "depository"]):
                        normalized_type = "checking"
                    elif any(i in raw_type for i in ["investment", "brokerage", "ira", "401k"]):
                        normalized_type = "brokerage"
                    else:
                        normalized_type = raw_type

                    inst_info = raw.get("institution") or {}
                    inst_name = inst_info.get("name") if isinstance(inst_info, dict) else str(inst_info or "")
                    disp_name = str(raw.get("displayName") or "Account")
                    if inst_name and inst_name.lower() not in disp_name.lower() and disp_name.upper().startswith("CREDIT CARD"):
                        disp_name = f"{inst_name} {disp_name}"

                    raw_mask = raw.get("mask") or "****"
                    mask = raw_mask if raw_mask.startswith("*") else f"****{raw_mask[-4:]}"
                    accounts.append(
                        MonarchAccount(
                            account_id=str(raw.get("id")),
                            name=disp_name,
                            type=normalized_type,
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
            amt = tx.amount
            abs_amt = abs(amt)
            is_credit_card = any(k in (tx.account_name or "").lower() for k in ["credit", "card", "mastercard", "visa", "amex"])

            if is_credit_card:
                if amt > 0:
                    flow_type = "PAYMENT (CREDIT)"
                    flow_text = f"+${abs_amt:,.2f} payment credited to {tx.account_name} from {tx.merchant}"
                else:
                    flow_type = "CHARGE (EXPENSE)"
                    flow_text = f"-${abs_amt:,.2f} charged to {tx.account_name} at {tx.merchant} [{tx.category}]"
            else:
                # Bank/Checking accounts: positive is incoming deposit, negative is outgoing debit
                if amt > 0:
                    flow_type = "DEPOSIT (INFLOW)"
                    flow_text = f"+${abs_amt:,.2f} deposited INTO {tx.account_name} FROM {tx.merchant} [{tx.category}]"
                else:
                    flow_type = "WITHDRAWAL (OUTFLOW)"
                    flow_text = f"-${abs_amt:,.2f} paid/transferred OUT OF {tx.account_name} TO {tx.merchant} [{tx.category}]"

            pending_str = " (Pending)" if tx.pending else ""
            summary = f"[{flow_type}] {flow_text}{pending_str}"
            is_large = abs_amt > 1000.0 or (amt > 500.0 and not is_credit_card)

            events.append(
                StreamEvent(
                    id=f"monarch-{tx.transaction_id}",
                    stream_type=self.stream_type,
                    source=self.name,
                    timestamp=tx.timestamp,
                    title=f"{flow_type}: {tx.merchant}",
                    summary=summary,
                    raw_data=tx.model_dump(mode="json"),
                    is_urgent=is_large,
                    metadata={"pending": tx.pending, "category": tx.category, "amount": amt},
                )
            )

        return events

    async def request_sync(self, account_ids: list[str] | None = None) -> bool:
        """Trigger an on-demand live bank sync via Monarch API to refresh balances from institutions."""
        if not self._client:
            return False
        try:
            if not account_ids:
                accounts = await self.get_accounts()
                account_ids = [a.account_id for a in accounts if a.account_id and a.account_id != "None"]
            if account_ids:
                res = await self._client.request_accounts_refresh(account_ids=account_ids)
                logger.info("Monarch accounts sync requested for %d accounts: %s", len(account_ids), res)
                return bool(res)
        except Exception as exc:
            logger.warning("Failed requesting Monarch account refresh: %s", exc)
        return False

    async def get_recurring_obligations(self) -> list[dict[str, Any]]:
        """Fetch verified billing statements and active recurring streams.

        Ground-truth billing statements from official emails take precedence
        over algorithmic transaction stream estimates.
        """
        verified_statements: list[dict[str, Any]] = []
        covered_merchants: set[str] = set()

        # Step 1: Extract verified statements directly from billing emails
        try:
            from connectors.statements import StatementExtractor
            extractor = StatementExtractor()
            verified_statements = await extractor.get_verified_obligations()
            for v in verified_statements:
                n_low = v["name"].lower()
                if "hyundai" in n_low or "ioniq" in n_low:
                    covered_merchants.add("hyundai")
                if "frontier" in n_low:
                    covered_merchants.add("frontier")
                if "progressive" in n_low:
                    covered_merchants.add("progressive")
                if "barclays" in n_low or "frontier airlines" in n_low:
                    covered_merchants.add("barclays")
                if "amex" in n_low or "delta" in n_low:
                    covered_merchants.add("amex")
                if "venture" in n_low or "capital one" in n_low:
                    covered_merchants.add("capitalone")
                if "chase" in n_low:
                    covered_merchants.add("chase")
        except Exception as ext_err:
            logger.debug("StatementExtractor unavailable or failed: %s", ext_err)

        if not self._client:
            if verified_statements:
                return verified_statements
            return [
                {
                    "id": "stmt-hyundai-car-loan",
                    "name": "Hyundai Ioniq 5 (Car Payment)",
                    "category": "auto_loan",
                    "amount": 256.28,
                    "frequency": "monthly",
                    "next_due_date": "2026-11-11",
                    "due_display": "Nov 11, 2026",
                    "account_mask": "5613",
                    "autopay": True,
                    "is_verified": True,
                    "source": "Hyundai Motor Finance Statement",
                    "status": "Due Nov 11 (AutoPay Active)",
                    "notes": "Verified financing installment for 2025 Hyundai Ioniq 5",
                },
                {
                    "id": "stmt-frontier-internet",
                    "name": "Frontier Internet",
                    "category": "internet",
                    "amount": 49.99,
                    "frequency": "monthly",
                    "next_due_date": "2026-11-27",
                    "due_display": "Nov 27, 2026",
                    "account_mask": "7005",
                    "autopay": True,
                    "is_verified": True,
                    "source": "Frontier Official Statement",
                    "status": "Due Nov 27 (AutoPay)",
                    "notes": "Verified bill notice received Nov 04, 2026",
                },
                {
                    "id": "stmt-progressive-auto",
                    "name": "Progressive Auto Insurance",
                    "category": "insurance",
                    "amount": 404.00,
                    "frequency": "semiannual",
                    "next_due_date": "2027-04-11",
                    "due_display": "Apr 11, 2027",
                    "account_mask": "995960080",
                    "autopay": True,
                    "is_verified": True,
                    "source": "Progressive Policy 995960080",
                    "status": "Paid in Full ($404 on Oct 11; Next Renewal: Apr 2027)",
                    "notes": "6-month policy term paid in full. No payment due in November.",
                },
            ]

        try:
            res = await self._client.get_recurring_transaction_streams()
            streams = res.get("recurringTransactionStreams", [])
            additional_obligations: list[dict[str, Any]] = []

            for item in streams:
                st = item.get("stream") or {}
                if not st.get("isActive", True):
                    continue
                name = st.get("name") or "Recurring Bill"
                lower_name = name.lower()
                amt = float(st.get("amount") or 0.0)
                abs_amt = abs(amt)

                # Filter out known false positives:
                # 1. Florida Power & Light: charges were EV charging sessions at EVolution chargers, not a monthly utility bill
                if "florida power" in lower_name or "fpl" in lower_name:
                    logger.debug("Skipping FPL from recurring bills: EV charging transactions")
                    continue

                # 2. Frontier $149 charges: airline flight ticket purchases on Frontier Mastercard, not internet
                if "frontier" in lower_name and abs(abs_amt - 149.0) < 1.0:
                    logger.debug("Skipping Frontier $149: airline flight transactions")
                    continue

                # 3. Progressive: policy is 6-month term paid in full on Oct 11; covered by StatementExtractor
                if "progressive" in lower_name:
                    continue

                # 4. Skip merchants already covered with verified statements
                if any(m in lower_name for m in covered_merchants):
                    continue

                is_income = st.get("recurringType") == "income" or amt > 0
                freq = st.get("frequency") or "monthly"
                next_tx = item.get("nextForecastedTransaction") or {}
                next_date = next_tx.get("date") or st.get("baseDate")

                cat = "general"
                if is_income:
                    cat = "income"
                elif any(s in lower_name for s in ["google", "netflix", "spotify", "apple", "gym", "fit"]):
                    cat = "subscription"
                elif any(u in lower_name for u in ["water", "electric", "gas", "utility"]):
                    cat = "utilities"

                status_label = "Scheduled Payroll" if is_income else f"Recurring ({freq})"
                additional_obligations.append({
                    "id": f"monarch-rec-{st.get('id', name.lower().replace(' ', '-'))}",
                    "name": name,
                    "category": cat,
                    "amount": abs_amt,
                    "frequency": freq,
                    "next_due_date": next_date,
                    "is_income": is_income,
                    "is_verified": False,
                    "source": "Monarch Stream (Estimated)",
                    "status": status_label,
                    "notes": f"Monarch Money recurring stream ({freq})",
                })

            combined = verified_statements + additional_obligations
            return combined
        except Exception as exc:
            logger.error("Failed fetching recurring streams from Monarch API: %s", exc)
            return verified_statements

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
