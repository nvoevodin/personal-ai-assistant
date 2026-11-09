"""Agent runner and tool execution routines."""

import logging
from typing import Any, Callable
from agent.context import LifeStreamContextBuilder
from agent.prompts import IMAGE_ANALYSIS_PROMPT, SYSTEM_INSTRUCTION
from connectors.base import ConnectorRegistry
from connectors.gmail import GmailConnector
from connectors.monarch import MonarchConnector
from core.gemini import GeminiClient
from core.rate_limit import RateLimiter

logger = logging.getLogger(__name__)


class AgentRunner:
    """Orchestrates LLM interaction, dynamic context augmentation, and tool execution."""

    def __init__(
        self,
        gemini_client: GeminiClient,
        registry: ConnectorRegistry,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.gemini_client = gemini_client
        self.registry = registry
        self.context_builder = LifeStreamContextBuilder(registry=registry)
        self.rate_limiter = rate_limiter or RateLimiter()
        self.tools = self._build_tool_suite()

    def _build_tool_suite(self) -> list[Callable[..., Any]]:
        """Construct callable tool functions registered for Gemini tool calling."""
        registry = self.registry

        async def get_financial_summary() -> str:
            """Fetch current account balances and recent expenditures from Monarch Money."""
            monarch: MonarchConnector | None = registry.get("monarch")  # type: ignore[assignment]
            if not monarch:
                return "Monarch Money connector is not configured."
            accounts = await monarch.get_accounts()
            txs = await monarch.get_recent_transactions(limit=5)

            lines = ["**Monarch Money Balances:**"]
            for acc in accounts:
                sign = "$" if acc.balance >= 0 else "-$"
                lines.append(f"- {acc.name} ({acc.mask}): {sign}{abs(acc.balance):,.2f}")

            lines.append("\n**Recent Transactions:**")
            for t in txs:
                lines.append(f"- {t.timestamp.strftime('%b %d')}: {t.merchant} - ${t.amount:,.2f} ({t.category})")

            return "\n".join(lines)

        async def get_recent_emails(category: str = "all") -> str:
            """Fetch recent high-signal emails, receipts, and flight alerts from Gmail."""
            gmail: GmailConnector | None = registry.get("gmail")  # type: ignore[assignment]
            if not gmail:
                return "Gmail connector is not configured."
            alerts = await gmail.get_recent_alerts(limit=5)
            if not alerts:
                return "No recent unread alerts found."

            lines = ["**Recent Gmail Alerts:**"]
            for a in alerts:
                if category == "all" or a.category.lower() == category.lower():
                    lines.append(f"- [{a.category.upper()}] From: {a.sender}\n  Subject: {a.subject}\n  Snippet: {a.snippet}")
            return "\n".join(lines)

        async def get_urgent_stream_alerts() -> str:
            """Scan all connectors for active urgent or security alerts."""
            all_events = await registry.fetch_all_events(limit_per_connector=10)
            urgent = [e for e in all_events if e.is_urgent]
            if not urgent:
                return "All streams nominal. No active urgent alerts."
            lines = ["**Active Urgent Stream Alerts:**"]
            for ev in urgent:
                lines.append(f"- [{ev.source.upper()}] {ev.title}: {ev.summary}")
            return "\n".join(lines)

        return [get_financial_summary, get_recent_emails, get_urgent_stream_alerts]

    async def handle_user_query(self, user_id: int, query: str) -> str:
        """Route user conversational query to Gemini with tools and life-stream context."""
        await self.rate_limiter.acquire(user_id=user_id)

        # Build dynamic real-time context
        stream_context = await self.context_builder.build_context_block(max_events=10)
        augmented_prompt = (
            f"{stream_context}\n\n"
            f"### User Message:\n{query}"
        )

        response_text, _ = await self.gemini_client.generate_with_tools(
            prompt=augmented_prompt,
            tools=self.tools,
            system_instruction=SYSTEM_INSTRUCTION,
        )
        return response_text

    async def handle_photo_analysis(
        self,
        user_id: int,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        user_caption: str | None = None,
    ) -> str:
        """Process an inbound photo/document with Gemini OCR and multimodal analysis."""
        await self.rate_limiter.acquire(user_id=user_id)

        stream_context = await self.context_builder.build_context_block(max_events=5)
        caption_context = f"\nUser Note/Caption: {user_caption}" if user_caption else ""

        prompt = (
            f"{stream_context}\n\n"
            f"{IMAGE_ANALYSIS_PROMPT}"
            f"{caption_context}"
        )

        return await self.gemini_client.analyze_image(
            image_bytes=image_bytes,
            mime_type=mime_type,
            prompt=prompt,
            system_instruction=SYSTEM_INSTRUCTION,
        )
