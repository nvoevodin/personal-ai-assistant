"""APScheduler recurring background jobs: life-stream noise triage and daily briefings."""

import datetime
import logging
from typing import Any
from telegram.ext import ContextTypes

from agent.runner import AgentRunner
from bot.handlers import format_financial_table
from connectors.base import ConnectorRegistry
from core.config import Settings
from core.dispatcher import ModelTier

logger = logging.getLogger(__name__)


async def poll_and_triage_streams(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Scan connected life streams, triage events using Tier 1 (gpt-6-luna), and alert user."""
    runner: AgentRunner | None = context.bot_data.get("agent_runner")
    registry: ConnectorRegistry | None = context.bot_data.get("connector_registry")
    settings: Settings | None = context.bot_data.get("settings")

    if not runner or not registry or not settings:
        logger.debug("Skipping stream triage: dependencies not loaded in bot_data.")
        return

    try:
        events = await registry.fetch_all_events(limit_per_connector=10)
    except Exception as exc:
        logger.error("Error fetching life-stream events during background poll: %s", exc)
        return

    logger.debug("Background poller collected %d events across all connectors.", len(events))

    for ev in events:
        try:
            # Skip if already triaged or notified
            if await runner.db.is_event_processed(ev.id):
                continue

            triage = None
            if runner.dispatcher and runner.dispatcher._settings.openai_api_key_value:
                try:
                    payload = (
                        f"Source: {ev.source}\n"
                        f"Title: {ev.title}\n"
                        f"Summary: {ev.summary}\n"
                        f"Urgent Flag: {ev.is_urgent}\n"
                        f"Metadata: {ev.metadata}"
                    )
                    triage = await runner.dispatcher.evaluate_background_event(event_text=payload)
                except Exception as eval_err:
                    logger.warning("Tier 1 evaluation failed on event %s: %s; falling back to rule-based", ev.id, eval_err)

            # Rule-based fallback if dispatcher is unavailable or failed
            if triage is None:
                should_notify = ev.is_urgent
                urgency = "high" if ev.is_urgent else "low"
                category = "finance" if ev.source == "monarch" else "noise"
                summary = ev.summary
            else:
                should_notify = triage.should_notify
                urgency = triage.urgency
                category = triage.category
                summary = triage.summary

            # Persist evaluation so this event is never re-processed
            await runner.db.mark_event_processed(
                event_id=ev.id,
                source=ev.source,
                title=ev.title,
                summary=summary,
                category=category,
                urgency=urgency,
                notified=should_notify,
            )

            if should_notify:
                urgency_icon = "🚨" if urgency == "high" else "⚡"
                alert_text = (
                    f"🎩 {urgency_icon} **Executive LifeStream Alert**\n\n"
                    f"**Stream:** `{ev.source.upper()}` | **Category:** `{category.capitalize()}`\n"
                    f"**Urgency:** `{urgency.upper()}`\n\n"
                    f"{summary}\n\n"
                    f"_Triaged by Tier 1 (gpt-6-luna)_"
                )

                for user_id in settings.allowed_telegram_user_ids:
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=alert_text,
                            parse_mode="Markdown",
                        )
                        logger.info("Delivered Tier 1 alert for [%s] to user %s", ev.id, user_id)
                    except Exception as send_err:
                        logger.error("Failed delivering alert to user %s: %s", user_id, send_err)

        except Exception as item_err:
            logger.error("Error processing event %s during background poll: %s", getattr(ev, "id", "unknown"), item_err)


async def send_daily_executive_briefing(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Deliver an 8:00 AM proactive executive summary of net worth and daily cash status."""
    runner: AgentRunner | None = context.bot_data.get("agent_runner")
    registry: ConnectorRegistry | None = context.bot_data.get("connector_registry")
    settings: Settings | None = context.bot_data.get("settings")

    if not runner or not registry or not settings:
        return

    logger.info("Generating scheduled daily executive morning briefing...")
    table_str = ""
    monarch = registry.get("monarch")
    if monarch:
        try:
            accounts = await monarch.get_accounts()
            table_str = format_financial_table(accounts)
        except Exception as exc:
            logger.warning("Could not fetch accounts for morning briefing: %s", exc)

    prompt = (
        "You are an elite, discreet Executive Butler providing the morning briefing.\n"
        "Draft a crisp, elegant, 2-3 sentence morning salutation and liquidity overview.\n"
        "Acknowledge that life streams and accounts are actively monitored.\n"
        f"Accounts Snapshot:\n{table_str}"
    )

    briefing_text = ""
    if runner.dispatcher and runner.dispatcher._settings.openai_api_key_value:
        try:
            res = await runner.dispatcher.dispatch_query(
                user_message=prompt,
                tier_override=ModelTier.TIER_2,
            )
            briefing_text = res.content
        except Exception as exc:
            logger.warning("Tier 2 failed to generate morning briefing: %s", exc)

    if not briefing_text:
        try:
            briefing_text, _ = await runner.gemini_client.generate_with_tools(
                prompt=prompt,
                tools=[],
            )
        except Exception as exc:
            briefing_text = "Good morning, sir. Your liquid reserves and accounts are steady and under active surveillance."

    full_message = (
        "🎩 **Executive Morning Briefing**\n\n"
        f"{briefing_text}\n\n"
        f"{table_str}\n\n"
        "_LifeStream Assistant Online_"
    )

    for user_id in settings.allowed_telegram_user_ids:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=full_message,
                parse_mode="Markdown",
            )
            logger.info("Delivered daily morning briefing to user %s", user_id)
        except Exception as exc:
            logger.error("Failed to send morning briefing to user %s: %s", user_id, exc)
