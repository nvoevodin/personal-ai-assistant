"""Telegram bot command and message handlers."""

import logging
from typing import Any
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from agent.runner import AgentRunner
from bot.security import authorized_only
from connectors.base import ConnectorRegistry
from core.config import get_settings

logger = logging.getLogger(__name__)


async def _safe_reply_markdown(message: Any, text: str) -> None:
    """Send markdown-formatted message, falling back to plain text if formatting is invalid."""
    if not message:
        return
    chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)] if len(text) > 4000 else [text]
    for chunk in chunks:
        try:
            await message.reply_text(chunk, parse_mode="Markdown")
        except Exception as exc:
            logger.warning("Markdown entity parsing failed (%s); sending plain text fallback", exc)
            await message.reply_text(chunk)


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


def format_financial_table(accounts: list) -> str:
    """Format accounts into a razor-sharp monospace ASCII table for Telegram."""
    lines = ["```text"]
    lines.append(f"{'Account':<18} {'Mask':<5} {'Balance':>13}")
    lines.append("─" * 38)
    total_balance = 0.0
    for a in accounts:
        sign = "$" if a.balance >= 0 else "-$"
        val_str = f"{sign}{abs(a.balance):,.2f}"
        name = (a.name[:17] + "…") if len(a.name) > 17 else a.name
        mask = a.mask or "••••"
        lines.append(f"{name:<18} {mask:<5} {val_str:>13}")
        total_balance += a.balance
    lines.append("─" * 38)
    tot_sign = "$" if total_balance >= 0 else "-$"
    lines.append(f"{'Total Net':<18} {'':<5} {f'{tot_sign}{abs(total_balance):,.2f}':>13}")
    lines.append("```")
    return "\n".join(lines)


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Construct interactive Telegram inline keyboard buttons for common actions."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💳 Account Balances", callback_data="cmd_balances"),
            InlineKeyboardButton("📊 Recent Spending", callback_data="cmd_spending"),
        ],
        [
            InlineKeyboardButton("⚡ Stream Alerts", callback_data="cmd_sync"),
            InlineKeyboardButton("🤖 System Status", callback_data="cmd_status"),
        ],
    ])


@authorized_only
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command for authorized users."""
    user = update.effective_user
    first_name = user.first_name if user else "there"

    welcome_message = (
        f"🎩 **Welcome, {first_name}!**\n\n"
        "I am your **LifeStream Personal AI Assistant & Executive Butler**, monitoring your life streams "
        "and finances with discretion and precision.\n\n"
        "**Connected Life Streams:**\n"
        "• 💰 **Monarch Money**: Live balance monitoring & spending breakdown\n"
        "• 📬 **Gmail Alerts**: High-signal travel, flight alerts & notifications\n"
        "• 📸 **Multimodal OCR**: Snap receipts or invoices for immediate parsing\n\n"
        "Tap a quick action below or ask me any question directly."
    )
    if update.effective_message:
        await update.effective_message.reply_text(
            welcome_message,
            parse_mode="Markdown",
            reply_markup=get_main_menu_keyboard(),
        )


@authorized_only
async def balances_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /balances command: fetches and renders formatted financial account table."""
    if update.effective_message and update.effective_chat:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    registry = _get_connector_registry(context)
    monarch = registry.get("monarch")
    if not monarch:
        if update.effective_message:
            await update.effective_message.reply_text("Monarch Money connector is not configured.")
        return

    accounts = await monarch.get_accounts()
    if not accounts:
        if update.effective_message:
            await update.effective_message.reply_text("No active accounts found in Monarch Money.")
        return

    table_text = format_financial_table(accounts)
    msg = f"🏛️ **Financial Accounts & Balances**\n\n{table_text}"
    if update.effective_message:
        await _safe_reply_markdown(update.effective_message, msg)


@authorized_only
async def spending_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /spending command: fetches recent transactions with clean breakdown."""
    if update.effective_message and update.effective_chat:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    registry = _get_connector_registry(context)
    monarch = registry.get("monarch")
    if not monarch:
        if update.effective_message:
            await update.effective_message.reply_text("Monarch Money connector is not configured.")
        return

    txs = await monarch.get_recent_transactions(limit=10)
    if not txs:
        if update.effective_message:
            await update.effective_message.reply_text("No recent transactions found.")
        return

    lines = ["📊 **Recent Expenditures & Transactions:**\n"]
    for t in txs:
        date_str = t.timestamp.strftime("%b %d")
        lines.append(f"• `{date_str}` **{t.merchant}** ─── `${t.amount:,.2f}`\n  *Category: {t.category}*")

    if update.effective_message:
        await _safe_reply_markdown(update.effective_message, "\n".join(lines))


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle taps on inline action buttons."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    data = query.data
    user = update.effective_user
    settings = get_settings()
    allowed_ids = settings.allowed_telegram_user_ids
    if user and user.id not in allowed_ids:
        await query.edit_message_text("⛔ Unauthorized action.")
        return

    if data == "cmd_balances":
        registry = _get_connector_registry(context)
        monarch = registry.get("monarch")
        if monarch:
            accounts = await monarch.get_accounts()
            table_text = format_financial_table(accounts)
            await query.message.reply_text(
                f"🏛️ **Financial Accounts & Balances**\n\n{table_text}",
                parse_mode="Markdown",
            )
    elif data == "cmd_spending":
        registry = _get_connector_registry(context)
        monarch = registry.get("monarch")
        if monarch:
            txs = await monarch.get_recent_transactions(limit=8)
            lines = ["📊 **Recent Expenditures:**\n"]
            for t in txs:
                date_str = t.timestamp.strftime("%b %d")
                lines.append(f"• `{date_str}` **{t.merchant}** ─── `${t.amount:,.2f}` ({t.category})")
            await query.message.reply_text("\n".join(lines), parse_mode="Markdown")
    elif data == "cmd_sync":
        await sync_command(update, context)
    elif data == "cmd_status":
        await status_command(update, context)


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
        await _safe_reply_markdown(update.effective_message, status_message)


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
        await _safe_reply_markdown(update.effective_message, "\n".join(lines))


@authorized_only
async def deep_analysis_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /deep, /audit, and /solve commands routed to Tier 3 Frontier Analyst (gpt-6.1-sol)."""
    if not update.effective_message or not update.effective_message.text:
        return

    user = update.effective_user
    user_id = user.id if user else 0
    raw_text = update.effective_message.text

    parts = raw_text.split(maxsplit=1)
    prompt = parts[1] if len(parts) > 1 else ""
    if not prompt:
        await _safe_reply_markdown(
            update.effective_message,
            "🧠 **Tier 3 Frontier Analyst (`gpt-6.1-sol`)**\n\n"
            "Please provide an analytical scenario or audit request after the command.\n\n"
            "**Examples:**\n"
            "• `/audit Review all my credit cards, interest risk, and debt payoff order`\n"
            "• `/deep Simulate 12-month net worth growth assuming $2,500 monthly savings`\n"
            "• `/solve Optimize emergency fund allocation across high-yield cash and brokerage`",
        )
        return

    if update.effective_chat:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    runner = _get_agent_runner(context)
    try:
        reply_text = await runner.handle_deep_analysis(user_id=user_id, query=raw_text)
        await _safe_reply_markdown(update.effective_message, reply_text)
    except Exception as exc:
        logger.exception("Error processing deep analysis from user %s: %s", user_id, exc)
        await _safe_reply_markdown(
            update.effective_message,
            f"⚠️ Deep analysis failed: {exc}",
        )


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
        if query.strip().lower().startswith(("/deep", "/audit", "/solve")):
            reply_text = await runner.handle_deep_analysis(user_id=user_id, query=query)
        else:
            reply_text = await runner.handle_user_query(user_id=user_id, query=query)
        await _safe_reply_markdown(update.effective_message, reply_text)
    except Exception as exc:
        logger.exception("Error processing text query from user %s: %s", user_id, exc)
        await _safe_reply_markdown(
            update.effective_message,
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

        await _safe_reply_markdown(update.effective_message, analysis_result)
    except Exception as exc:
        logger.exception("Error processing inbound photo from user %s: %s", user_id, exc)
        await _safe_reply_markdown(
            update.effective_message,
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
