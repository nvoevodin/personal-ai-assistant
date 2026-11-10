"""Life-stream context builder aggregating real-time data across connectors."""

import logging
from datetime import datetime, timezone
from connectors.base import ConnectorRegistry
from connectors.models import LifeStreamType, StreamEvent

logger = logging.getLogger(__name__)


class LifeStreamContextBuilder:
    """Aggregates and formats normalized connector events into dynamic LLM context."""

    def __init__(self, registry: ConnectorRegistry) -> None:
        self.registry = registry

    async def build_context_block(self, max_events: int = 15) -> str:
        """Fetch latest events, bills, and account balances into an executive prompt block."""
        events: list[StreamEvent] = await self.registry.fetch_all_events(limit_per_connector=max_events)
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        lines = [
            f"### Current Life Stream Snapshot (Recorded: {now_str})",
            "",
        ]

        # 1. Upcoming Payment Obligations (Car payments, insurance, bills)
        monarch = self.registry.get("monarch")
        if monarch and hasattr(monarch, "get_recurring_obligations"):
            try:
                obligations = await monarch.get_recurring_obligations()
                if obligations:
                    lines.append("📅 **UPCOMING BILLS & PAYMENT SCHEDULE (GROUND TRUTH):**")
                    for ob in obligations:
                        due = ob.get("next_due_date") or "Scheduled"
                        amt = f"${ob['amount']:,.2f}"
                        cat = ob.get("category", "").upper()
                        sign = "+" if ob.get("is_income") else "-"
                        ver_tag = "[VERIFIED STATEMENT]" if ob.get("is_verified") else "[STREAM ESTIMATE]"
                        status_note = f" | Status: {ob.get('status')}" if ob.get('status') else ""
                        lines.append(f"- **{ob['name']}** [{cat}] {ver_tag}: `{sign}{amt}` (Due: {due}){status_note}")
                    lines.append("Note: Florida Power & Light transactions were ad-hoc EV charging sessions for the Hyundai Ioniq 5, not a monthly electric bill. Frontier Internet is $49.99 due Nov 27 with AutoPay. Progressive auto insurance was paid in full $404 for 6 months on Oct 11, 2026; next renewal is April 11, 2027.")
                    lines.append("")
            except Exception as exc:
                logger.debug("Failed adding recurring obligations to context: %s", exc)

        # 2. Credit Cards & Cash Balances
        if monarch and hasattr(monarch, "get_accounts"):
            try:
                accounts = await monarch.get_accounts()
                credit_cards = [a for a in accounts if a.type == "credit"]
                cash_accounts = [a for a in accounts if a.type in {"checking", "savings", "depository"}]
                if credit_cards or cash_accounts:
                    lines.append("💳 **CREDIT CARDS & CASH LIQUIDITY:**")
                    for c in credit_cards:
                        lines.append(f"- Credit Card: **{c.name}** ({c.mask}) | Current Balance: `-${abs(c.balance):,.2f}`")
                    for k in cash_accounts:
                        lines.append(f"- Cash: **{k.name}** ({k.mask}) | Available: `${k.balance:,.2f}`")
                    lines.append("")
            except Exception as exc:
                logger.debug("Failed adding account balances to context: %s", exc)

        if not events:
            lines.append("*No recent raw stream alerts detected across monitored streams.*")
            return "\n".join(lines)

        urgent_events = [e for e in events if e.is_urgent]
        normal_events = [e for e in events if not e.is_urgent]

        if urgent_events:
            lines.append("⚠️ **URGENT ALERTS / CRITICAL STREAM EVENTS:**")
            for ev in urgent_events:
                ts = ev.timestamp.strftime("%b %d %H:%M")
                lines.append(f"- `[{ev.stream_type.value.upper()}]` **{ev.title}** ({ts}): {ev.summary}")
            lines.append("")

        lines.append("📋 **RECENT AMBIENT ACTIVITY:**")
        for ev in normal_events[:10]:
            ts = ev.timestamp.strftime("%b %d %H:%M")
            lines.append(f"- `[{ev.stream_type.value.upper()}]` {ev.summary} ({ts})")

        return "\n".join(lines)
