"""Agent runner and tool execution routines."""

import json
import logging
import re
from typing import Any, Callable
from agent.context import LifeStreamContextBuilder
from agent.prompts import IMAGE_ANALYSIS_PROMPT, SYSTEM_INSTRUCTION
from connectors.base import ConnectorRegistry
from connectors.gmail import GmailConnector
from connectors.monarch import MonarchConnector
from core.dispatcher import ModelDispatcher, ModelTier
from core.gemini import GeminiClient
from core.rate_limit import RateLimiter
from storage.db import DatabaseManager

logger = logging.getLogger(__name__)


class AgentRunner:
    """Orchestrates LLM interaction, dynamic context augmentation, and tool execution."""

    def __init__(
        self,
        gemini_client: GeminiClient,
        registry: ConnectorRegistry,
        rate_limiter: RateLimiter | None = None,
        db: DatabaseManager | None = None,
        dispatcher: ModelDispatcher | None = None,
    ) -> None:
        self.gemini_client = gemini_client
        self.registry = registry
        self.context_builder = LifeStreamContextBuilder(registry=registry)
        self.rate_limiter = rate_limiter or RateLimiter()
        self.db = db or DatabaseManager()
        self.dispatcher = dispatcher or ModelDispatcher()
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
                lines.append(f"• **{acc.name}** ({acc.mask}): `{sign}{abs(acc.balance):,.2f}`")

            lines.append("\n**Recent Transactions:**")
            for t in txs:
                lines.append(f"• **{t.timestamp.strftime('%b %d')}**: {t.merchant} - `${t.amount:,.2f}` ({t.category})")

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
                    lines.append(f"• `[{a.category.upper()}]` From: {a.sender}\n  Subject: {a.subject}\n  Snippet: {a.snippet}")
            return "\n".join(lines)

        async def get_urgent_stream_alerts() -> str:
            """Scan all connectors for active urgent or security alerts."""
            all_events = await registry.fetch_all_events(limit_per_connector=10)
            urgent = [e for e in all_events if e.is_urgent]
            if not urgent:
                return "All streams nominal. No active urgent alerts."
            lines = ["**Active Urgent Stream Alerts:**"]
            for ev in urgent:
                lines.append(f"• `[{ev.source.upper()}]` {ev.title}: {ev.summary}")
            return "\n".join(lines)

        return [get_financial_summary, get_recent_emails, get_urgent_stream_alerts]

    async def handle_user_query(self, user_id: int, query: str) -> str:
        """Route user conversational query to Gemini with tools and life-stream context."""
        await self.rate_limiter.acquire(user_id=user_id)

        # Build dynamic real-time context
        stream_context = await self.context_builder.build_context_block(max_events=10)

        # Fetch recent conversational memory for multi-turn coherence
        recent_messages = await self.db.get_recent_messages(user_id=user_id, limit=6)
        history_block = ""
        if recent_messages:
            history_lines = [
                f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
                for m in recent_messages
            ]
            history_block = "### Recent Conversation History:\n" + "\n".join(history_lines) + "\n\n"

        augmented_prompt = (
            f"{stream_context}\n\n"
            f"{history_block}"
            f"### Current User Message:\n{query}"
        )

        history_payload = [
            {"role": m["role"], "content": m["content"]}
            for m in recent_messages
        ]

        response_text = ""
        # 1. Prefer OpenAI Tier 2 Workhorse (gpt-6.1-terra) if key is active
        if self.dispatcher and self.dispatcher._settings.openai_api_key_value:
            try:
                res = await self.dispatcher.dispatch_query(
                    user_message=augmented_prompt,
                    conversation_history=history_payload,
                    tier_override=ModelTier.TIER_2,
                    system_instruction=SYSTEM_INSTRUCTION,
                )
                response_text = res.content
            except Exception as exc:
                logger.warning("OpenAI Tier 2 dispatch failed (%s); falling back to Gemini", exc)

        # 2. Fallback to Gemini if Tier 2 didn't respond
        if not response_text:
            response_text, _ = await self.gemini_client.generate_with_tools(
                prompt=augmented_prompt,
                tools=self.tools,
                system_instruction=SYSTEM_INSTRUCTION,
            )

        # Save turns to database
        try:
            await self.db.save_message(user_id=user_id, role="user", content=query)
            await self.db.save_message(user_id=user_id, role="assistant", content=response_text)
        except Exception as db_exc:
            logger.warning("Failed to persist conversation history: %s", db_exc)

        return response_text

    async def handle_deep_analysis(self, user_id: int, query: str) -> str:
        """Route explicitly requested complex reasoning scenarios to Tier 3 Frontier Analyst (gpt-6.1-sol)."""
        await self.rate_limiter.acquire(user_id=user_id)
        stream_context = await self.context_builder.build_context_block(max_events=10)
        recent_messages = await self.db.get_recent_messages(user_id=user_id, limit=6)

        history_payload = [
            {"role": m["role"], "content": m["content"]}
            for m in recent_messages
        ]

        if self.dispatcher and self.dispatcher._settings.openai_api_key_value:
            augmented_query = f"{stream_context}\n\n### Analytical Directive:\n{query}"
            res = await self.dispatcher.dispatch_query(
                user_message=augmented_query,
                conversation_history=history_payload,
                tier_override=ModelTier.TIER_3,
                system_instruction=SYSTEM_INSTRUCTION,
            )
            response_text = f"🧠 **[Tier 3: {res.model}]**\n\n{res.content}\n\n_Tokens: {res.total_tokens} | Est: ${res.estimated_cost_usd:.4f}_"
        else:
            augmented_query = f"{stream_context}\n\n### In-Depth Deep Analytical Directive:\n{query}"
            response_text, _ = await self.gemini_client.generate_with_tools(
                prompt=augmented_query,
                tools=self.tools,
                system_instruction=SYSTEM_INSTRUCTION,
            )

        try:
            await self.db.save_message(user_id=user_id, role="user", content=query)
            await self.db.save_message(user_id=user_id, role="assistant", content=response_text)
        except Exception as db_exc:
            logger.warning("Failed to persist deep analysis history: %s", db_exc)

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

        result_text = await self.gemini_client.analyze_image(
            image_bytes=image_bytes,
            mime_type=mime_type,
            prompt=prompt,
            system_instruction=SYSTEM_INSTRUCTION,
        )

        # Record photo interaction and extract receipt JSON if present
        try:
            user_msg = f"[Photo Upload: {mime_type}] {user_caption or ''}".strip()
            await self.db.save_message(user_id=user_id, role="user", content=user_msg)
            await self.db.save_message(user_id=user_id, role="assistant", content=result_text)

            # Check for ```json ... ``` block to auto-store receipt
            json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", result_text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(1))
                if "merchant" in data and "total_amount" in data:
                    await self.db.save_receipt(
                        user_id=user_id,
                        merchant=str(data["merchant"]),
                        total_amount=float(data["total_amount"]),
                        currency=str(data.get("currency", "USD")),
                        tax_amount=float(data.get("tax_amount", 0.0)),
                        receipt_date=str(data.get("date", "")),
                        category=str(data.get("category", "General")),
                        items=data.get("items", []),
                        raw_summary=result_text[:500],
                    )
        except Exception as exc:
            logger.warning("Failed to store photo/receipt metadata: %s", exc)

        return result_text
