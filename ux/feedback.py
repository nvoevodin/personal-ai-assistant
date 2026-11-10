"""UX Feedback collection, style toggling, and self-improvement subsystem."""

import logging
from typing import Any
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from storage.db import DatabaseManager
from ux.layout import DIVIDER_LINE, format_header
from ux.styles import STYLE_REGISTRY, UXStylePreset, get_style_config

logger = logging.getLogger(__name__)


def get_ux_feedback_keyboard(context_tag: str = "general") -> InlineKeyboardMarkup:
    """Generate subtle inline feedback buttons for evaluating response presentation."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👍 Crisp", callback_data=f"ux_rate:pos:{context_tag}"),
            InlineKeyboardButton("👎 Reformat", callback_data=f"ux_rate:neg:{context_tag}"),
            InlineKeyboardButton("🎨 Style", callback_data="ux_menu_styles"),
        ]
    ])


def get_style_picker_keyboard() -> InlineKeyboardMarkup:
    """Generate inline buttons for selecting the active UX presentation preset."""
    buttons = []
    for preset, cfg in STYLE_REGISTRY.items():
        buttons.append([
            InlineKeyboardButton(
                f"{cfg.emoji} {cfg.name}",
                callback_data=f"ux_set_style:{preset.value}",
            )
        ])
    buttons.append([
        InlineKeyboardButton("🔙 Back to Menu", callback_data="ux_menu_main")
    ])
    return InlineKeyboardMarkup(buttons)


async def handle_ux_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle callback queries originating from UX feedback and style menus.
    
    Returns True if the callback was processed by this handler.
    """
    query = update.callback_query
    if not query or not query.data or not query.data.startswith("ux_"):
        return False

    await query.answer()
    data = query.data
    user = update.effective_user
    user_id = user.id if user else 0
    db: DatabaseManager = context.bot_data.get("agent_runner", {}).db if context.bot_data.get("agent_runner") else DatabaseManager()

    if data.startswith("ux_rate:"):
        parts = data.split(":")
        rating_type = "positive" if parts[1] == "pos" else "negative"
        tag = parts[2] if len(parts) > 2 else "general"

        current_style = await db.get_user_ux_style(user_id)
        snippet = query.message.text[:200] if query.message and query.message.text else ""
        await db.save_ux_feedback(
            user_id=user_id,
            rating=rating_type,
            note=f"Tag: {tag}",
            message_snippet=snippet,
            style_preset=current_style,
        )

        if rating_type == "positive":
            await query.edit_message_reply_markup(reply_markup=None)
            if query.message:
                await query.message.reply_text("🎩 *Splendid.* The presentation standard has been noted.")
        else:
            await query.edit_message_reply_markup(reply_markup=get_style_picker_keyboard())
            if query.message:
                await query.message.reply_text(
                    "🎩 *Noted with apologies, sir.* Would you prefer an alternate presentation style below?\n"
                    "Or provide critique via `/ux feedback <note>`."
                )
        return True

    elif data == "ux_menu_styles":
        await query.edit_message_reply_markup(reply_markup=get_style_picker_keyboard())
        return True

    elif data.startswith("ux_set_style:"):
        new_style = data.split(":")[1]
        await db.set_user_ux_style(user_id=user_id, style=new_style)
        cfg = get_style_config(new_style)

        msg = (
            f"🎩 **UX Presentation Updated: {cfg.emoji} {cfg.name}**\n{DIVIDER_LINE}\n"
            f"_{cfg.description}_\n\n"
            "All future responses will adhere to this visual standard."
        )
        if query.message:
            await query.message.reply_text(msg, parse_mode="Markdown")
        await query.edit_message_reply_markup(reply_markup=None)
        return True

    elif data == "ux_menu_main":
        await query.edit_message_reply_markup(reply_markup=get_ux_feedback_keyboard())
        return True

    return False


async def ux_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /ux command: view current presentation settings, statistics, and switch styles."""
    user = update.effective_user
    user_id = user.id if user else 0
    db: DatabaseManager = context.bot_data.get("agent_runner", {}).db if context.bot_data.get("agent_runner") else DatabaseManager()

    # Check for subcommands like /ux feedback <text>
    args = context.args or []
    if args and args[0].lower() == "feedback":
        feedback_text = " ".join(args[1:]).strip()
        if not feedback_text:
            if update.effective_message:
                await update.effective_message.reply_text("Please provide your feedback, e.g.: `/ux feedback make tables more compact`")
            return
        current_style = await db.get_user_ux_style(user_id)
        await db.save_ux_feedback(
            user_id=user_id,
            rating="restyle",
            note=feedback_text,
            style_preset=current_style,
        )
        if update.effective_message:
            await update.effective_message.reply_text(
                "🎩 **Feedback Recorded.**\n\n"
                f"Your note: *\"{feedback_text}\"*\n"
                "This has been queued for our continuous presentation refinement loop."
            )
        return

    current_style = await db.get_user_ux_style(user_id)
    cfg = get_style_config(current_style)
    stats = await db.get_ux_feedback_stats()
    pos = stats.get("counts", {}).get("positive", 0)
    neg = stats.get("counts", {}).get("negative", 0)
    restyle = stats.get("counts", {}).get("restyle", 0)

    lines = [
        format_header("UX Presentation & Design Studio", badge="UX LAB", emoji="🎨"),
        f"**Active Preset**: {cfg.emoji} **{cfg.name}**",
        f"_{cfg.description}_\n",
        "📊 **Presentation Feedback Telemetry**:",
        f"• 👍 Positive Ratings: `{pos}`",
        f"• 👎 Reformat Requests: `{neg}`",
        f"• 📝 Custom Notes: `{restyle}`\n",
        DIVIDER_LINE,
        "**Available Actions**:\n"
        "• Tap a preset below to switch presentation style immediately.\n"
        "• Send `/ux feedback <critique>` to submit specific layout guidance.",
    ]

    if update.effective_message:
        await update.effective_message.reply_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=get_style_picker_keyboard(),
        )
