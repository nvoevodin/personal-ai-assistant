"""Telegram bot command and message handlers."""

import logging
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from agent.runner import AgentRunner
from bot.security import authorized_only
from connectors.base import ConnectorRegistry
from core.config import get_settings

logger = logging.getLogger(__name__)


def _get_agent_runner(context: ContextTypes.DEFAULT_TYPE) -> AgentRunner:
    """Retrieve the shared AgentRunner instance from bot_data."""
    runner = context.bot_data.get("agent_runner")
    if not runner:
        raise RuntimeError("AgentRunner is not initialized in bot_data.")
    return runner


def _get_connector_registry(context: ContextTypes.DEFAULT_TYPE) -> ConnectorRegistry:
    """Retrieve the shared ConnectorRegistry from bot_data."""
    registry = context.bot_data.get("connector_registry")
    if not registry:
        raise RuntimeError("ConnectorRegistry is not initialized in bot_data.")
    return registry


@authorized_only
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command for authorized users."""
    user = update.effective_user
    first_name = user.first_name if user else "there"

    welcome_message = (
        f"👋 **Welcome, {first_name}!**\n\n"
        "I am your **LifeStream Personal AI Assistant**, operating on Gemini 3.8 Flash.\n\n"
        "**Active Capabilities:**\n"
        "• 💰 **Monarch Money**: Live balance monitoring & spending breakdown\n"
        "• 📬 **Gmail Alerts**: Flight tracking, high-signal alerts & receipts\n"
        "• 📸 **Multimodal OCR**: Send receipts, invoices, or tickets for instant analysis\n"
        "• ⚡ **Automated Tool Calling**: Query your finances and alerts conversationally\n\n"
        "**Available Commands:**\n"
        "/status - View system health, active streams, and rate limits\n"
        "/sync   - Force a refresh of all life streams\n\n"
        "Try asking me: *'What were my recent expenses?'* or simply send a photo of a receipt!"
    )
    if update.effective_message:
        await update.effective_message.reply_text(welcome_message, parse_mode="Markdown")


@authorized_only
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command: reports health of model and connected streams."""
    settings = get_settings()
    registry = _get_connector_registry(context)

    connectors_health = []
    for conn in registry.all_connectors():
        health = await conn.get_health()
        status_icon = "🟢" if health.get("connected") else "🔴"
        connectors_health.append(
            f"  {status_icon} **{conn.name.title()}**: Connected ({health.get('latency_ms', 0)}ms)"
        )

    connectors_str = "\n".join(connectors_health) if connectors_health else "  *No active connectors registered*"

    status_message = (
        "📊 **LifeStream Assistant System Status**\n\n"
        f"🤖 **Model**: `{settings.gemini_model}`\n"
        f"🔒 **Security**: Whitelist Active ({len(settings.allowed_telegram_user_ids)} authorized user(s))\n"
        f"⏱️ **Rate Limit**: {settings.rate_limit_calls_per_minute} calls/min\n\n"
        "🔌 **Connected Streams:**\n"
        f"{connectors_str}\n\n"
        "✅ All systems nominal. Free-tier multimodal pipeline ready."
    )
    if update.effective_message:
        await update.effective_message.reply_text(status_message, parse_mode="Markdown")


@authorized_only
async def sync_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /sync command: fetches and delivers a fresh digest of life-stream events."""
    if update.effective_message and update.effective_chat:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    registry = _get_connector_registry(context)
    events = await registry.fetch_all_events(limit_per_connector=5)

    if not events:
        if update.effective_message:
            await update.effective_message.reply_text("✨ Streams refreshed. No new events to report.")
        return

    lines = ["🔄 **Life Streams Synced:**\n"]
    for ev in events:
        icon = "⚠️" if ev.is_urgent else "🔹"
        lines.append(f"{icon} `[{ev.source.upper()}]` **{ev.title}**\n   {ev.summary}")

    if update.effective_message:
        await update.effective_message.reply_text("\n".join(lines), parse_mode="Markdown")


@authorized_only
async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inbound user queries, routes them through AgentRunner and Gemini."""
    if not update.effective_message or not update.effective_message.text:
        return

    user = update.effective_user
    user_id = user.id if user else 0
    query = update.effective_message.text

    if update.effective_chat:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    runner = _get_agent_runner(context)
    try:
        reply_text = await runner.handle_user_query(user_id=user_id, query=query)
        await update.effective_message.reply_text(reply_text, parse_mode="Markdown")
    except Exception as exc:
        logger.exception("Error processing text query from user %s: %s", user_id, exc)
        await update.effective_message.reply_text(
            f"⚠️ Could not process your request: {exc}",
        )


@authorized_only
async def photo_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Download inbound photo attachment and perform multimodal OCR analysis via Gemini."""
    if not update.effective_message or not update.effective_message.photo:
        return

    user = update.effective_user
    user_id = user.id if user else 0
    caption = update.effective_message.caption

    if update.effective_chat:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    # Telegram provides multiple photo sizes; the last item is the highest resolution
    highest_res_photo = update.effective_message.photo[-1]

    try:
        # Download photo bytes
        telegram_file = await highest_res_photo.get_file()
        photo_bytes_io = await telegram_file.download_as_bytearray()
        image_bytes = bytes(photo_bytes_io)

        runner = _get_agent_runner(context)
        analysis_result = await runner.handle_photo_analysis(
            user_id=user_id,
            image_bytes=image_bytes,
            mime_type="image/jpeg",
            user_caption=caption,
        )

        await update.effective_message.reply_text(analysis_result, parse_mode="Markdown")
    except Exception as exc:
        logger.exception("Error processing inbound photo from user %s: %s", user_id, exc)
        await update.effective_message.reply_text(
            f"⚠️ Photo analysis failed: {exc}",
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global unhandled exception catcher."""
    logger.error("Exception while handling an update: %s", context.error, exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ An unexpected system error occurred while handling this update.",
            )
        except Exception as reply_err:
            logger.error("Failed to notify user about error: %s", reply_err)
