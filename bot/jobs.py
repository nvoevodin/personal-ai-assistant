"""APScheduler recurring background jobs: life-stream noise triage and daily briefings."""

import datetime
import logging
from typing import Any
from telegram.ext import ContextTypes

from agent.runner import AgentRunner
from bot.handlers import format_financial_table
from bot.noise_filter import is_hardcoded_noise
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

    # Sync recurring payment obligations (car payments, bills, subscriptions)
    monarch = registry.get("monarch")
    if monarch and hasattr(monarch, "get_recurring_obligations") and runner.db:
        try:
            obligations = await monarch.get_recurring_obligations()
            for ob in obligations:
                await runner.db.upsert_payment_obligation(
                    obligation_id=ob["id"],
                    name=ob["name"],
                    category=ob.get("category", "bills"),
                    amount=float(ob.get("amount", 0.0)),
                    frequency=ob.get("frequency", "monthly"),
                    next_due_date=ob.get("next_due_date"),
                    autopay=bool(ob.get("autopay", False)),
                    notes=ob.get("notes"),
                )
        except Exception as ob_err:
            logger.debug("Failed updating recurring obligations in background poll: %s", ob_err)

    # Proactive alert check: notify user for payment obligations due within 48 hours
    if runner.db:
        try:
            today_date = datetime.datetime.now(datetime.timezone.utc).date()
            upcoming_obs = await runner.db.get_upcoming_payment_obligations(limit=15)
            for ob in upcoming_obs:
                due_str = ob.get("next_due_date")
                if not due_str or len(due_str) < 10 or ob.get("is_income"):
                    continue
                try:
                    due_date = datetime.date.fromisoformat(due_str[:10])
                    diff_days = (due_date - today_date).days
                except Exception:
                    continue

                if 0 <= diff_days <= 1:
                    alert_id = f"bill-reminder-{ob['id']}-{due_str[:10]}"
                    if not await runner.db.is_event_processed(alert_id):
                        timing = "Today" if diff_days == 0 else "Tomorrow"
                        autopay_str = "AutoPay is scheduled" if ob.get("autopay") else "Action required: Manual payment"
                        alert_msg = (
                            f"🎩 📅 **Executive Bill Reminder**\n\n"
                            f"Your **{ob['name']}** payment is due **{timing}** ({due_str[:10]}).\n\n"
                            f"```text\n"
                            f"Obligation: {ob['name']}\n"
                            f"Amount:     ${float(ob.get('amount') or 0):,.2f}\n"
                            f"Due Date:   {due_str[:10]} ({timing})\n"
                            f"Status:     {autopay_str}\n"
                            f"```\n"
                            f"{'_Ensure sufficient checking balance is available._' if ob.get('autopay') else '_Please submit payment to avoid late fees._'}"
                        )
                        await runner.db.mark_event_processed(
                            event_id=alert_id,
                            source="billing_reminder",
                            title=f"{ob['name']} due {timing}",
                            summary=alert_msg,
                            category="finance",
                            urgency="high",
                            notified=True,
                        )
                        for uid in settings.allowed_telegram_user_ids:
                            try:
                                await context.bot.send_message(
                                    chat_id=uid,
                                    text=alert_msg,
                                    parse_mode="Markdown",
                                )
                                logger.info("Delivered proactive bill reminder for [%s] to user %s", ob['name'], uid)
                            except Exception as snd_err:
                                logger.error("Failed sending proactive bill reminder: %s", snd_err)
        except Exception as check_err:
            logger.debug("Failed checking imminent bills for proactive reminder: %s", check_err)

    for ev in events:
        try:
            # Skip if already triaged or notified
            if await runner.db.is_event_processed(ev.id):
                continue

            # Step 0: Hard-coded heuristic noise filter (drops routine shipping, statements, marketing without waking LLM)
            is_noise, noise_reason = is_hardcoded_noise(
                source=ev.source,
                title=ev.title,
                summary=ev.summary,
                metadata=ev.metadata,
            )
            if is_noise:
                logger.debug("Event %s dropped by hard-coded noise filter: %s", ev.id, noise_reason)
                await runner.db.mark_event_processed(
                    event_id=ev.id,
                    source=ev.source,
                    title=ev.title,
                    summary=ev.summary,
                    category="noise",
                    urgency="low",
                    notified=False,
                )
                continue

            payload = (
                f"Source: {ev.source}\n"
                f"Title: {ev.title}\n"
                f"Summary: {ev.summary}\n"
                f"Urgent Flag: {ev.is_urgent}\n"
                f"Metadata: {ev.metadata}"
            )

            # Step 1: Tier 1 Gatekeeper (gpt-6-luna)
            triage = None
            if runner.dispatcher and runner.dispatcher._settings.openai_api_key_value:
                try:
                    triage = await runner.dispatcher.evaluate_background_event(event_text=payload)
                except Exception as eval_err:
                    logger.warning("Tier 1 evaluation failed on event %s: %s; falling back to rule-based", ev.id, eval_err)

            # Rule-based fallback if dispatcher is unavailable or failed
            if triage is None:
                needs_investigation = ev.is_urgent
                urgency = "high" if ev.is_urgent else "low"
                category = "finance" if ev.source == "monarch" else "noise"
                summary = ev.summary
            else:
                needs_investigation = triage.needs_investigation or triage.should_notify
                urgency = triage.urgency
                category = triage.category
                summary = triage.summary

            if not needs_investigation:
                # Event does not warrant investigation or notification
                await runner.db.mark_event_processed(
                    event_id=ev.id,
                    source=ev.source,
                    title=ev.title,
                    summary=summary,
                    category=category,
                    urgency=urgency,
                    notified=False,
                )
                continue

            # Step 2: Tier 2 Analyst Investigation with live financial context (Investigate Before Alerting)
            advisory = None
            if runner.dispatcher and runner.dispatcher._settings.openai_api_key_value:
                try:
                    context_block = await runner.context_builder.build_context_block(max_events=10)
                    advisory = await runner.dispatcher.investigate_and_advise(
                        event_payload=payload,
                        context_block=context_block,
                    )
                except Exception as adv_err:
                    logger.error("Tier 2 investigation failed for event %s: %s", ev.id, adv_err)
            else:
                if ev.is_urgent:
                    advisory = summary

            # If Tier 2 determines NO_ACTION_REQUIRED or returns None, suppress alert
            if advisory is None:
                logger.info("Event %s silenced after Tier 2 investigation (NO_ACTION_REQUIRED)", ev.id)
                await runner.db.mark_event_processed(
                    event_id=ev.id,
                    source=ev.source,
                    title=ev.title,
                    summary=summary,
                    category=category,
                    urgency=urgency,
                    notified=False,
                )
                continue

            # Event is verified and actionable: record and notify Telegram
            await runner.db.mark_event_processed(
                event_id=ev.id,
                source=ev.source,
                title=ev.title,
                summary=advisory,
                category=category,
                urgency=urgency,
                notified=True,
            )

            urgency_icon = "🚨" if urgency == "high" else "💡"
            alert_text = (
                f"🎩 {urgency_icon} **Executive Advisory Alert**\n\n"
                f"**Stream:** `{ev.source.upper()}` | **Category:** `{category.capitalize()}`\n\n"
                f"{advisory}\n\n"
                f"_Investigated & verified by Tier 2 (gpt-6.1-terra)_"
            )

            for user_id in settings.allowed_telegram_user_ids:
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=alert_text,
                        parse_mode="Markdown",
                    )
                    logger.info("Delivered Tier 2 Executive Advisory for [%s] to user %s", ev.id, user_id)
                except Exception as send_err:
                    logger.error("Failed delivering alert to user %s: %s", user_id, send_err)

        except Exception as item_err:
            logger.error("Error processing event %s during background poll: %s", getattr(ev, "id", "unknown"), item_err)


async def send_daily_executive_briefing(
    context: ContextTypes.DEFAULT_TYPE,
    target_chat_id: int | None = None,
) -> None:
    """Deliver an executive summary of net worth and daily cash status."""
    runner: AgentRunner | None = context.bot_data.get("agent_runner")
    registry: ConnectorRegistry | None = context.bot_data.get("connector_registry")
    settings: Settings | None = context.bot_data.get("settings")

    if not runner or not registry or not settings:
        return

    logger.info("Generating executive morning briefing...")
    table_str = ""
    obligations_str = ""
    monarch = registry.get("monarch")
    if monarch:
        try:
            accounts = await monarch.get_accounts()
            table_str = format_financial_table(accounts)
        except Exception as exc:
            logger.warning("Could not fetch accounts for morning briefing: %s", exc)

        if hasattr(monarch, "get_recurring_obligations"):
            try:
                obs = await monarch.get_recurring_obligations()
                if obs:
                    from ux.layout import format_obligations_table
                    obligations_str = format_obligations_table(obs[:5])
            except Exception as o_err:
                logger.debug("Could not fetch obligations for morning briefing: %s", o_err)

    prompt = (
        "You are an elite, discreet Executive Butler providing the morning briefing.\n"
        "Draft a crisp, elegant, 2-3 sentence morning salutation and liquidity overview.\n"
        "Acknowledge that life streams, payment obligations, and accounts are actively monitored.\n"
        f"Accounts Snapshot:\n{table_str}\n"
        + (f"Upcoming Obligations:\n{obligations_str}\n" if obligations_str else "")
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
        + (f"📅 **Upcoming Payment Obligations:**\n{obligations_str}\n\n" if obligations_str else "")
        + "_LifeStream Assistant Online_"
    )

    recipients = [target_chat_id] if target_chat_id else settings.allowed_telegram_user_ids
    for user_id in recipients:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=full_message,
                parse_mode="Markdown",
            )
            logger.info("Delivered morning briefing to user %s", user_id)
        except Exception as exc:
            logger.error("Failed to send morning briefing to user %s: %s", user_id, exc)
