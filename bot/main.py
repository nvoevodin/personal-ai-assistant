"""Async Telegram Bot entrypoint, Application builder, and lifecycle loop."""

import asyncio
import logging
import sys
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from agent.runner import AgentRunner
from bot.handlers import (
    error_handler,
    photo_message_handler,
    start_command,
    status_command,
    sync_command,
    text_message_handler,
)
from bot.security import UserWhitelistFilter
from connectors.base import ConnectorRegistry
from connectors.gmail import GmailConnector
from connectors.monarch import MonarchConnector
from core.config import Settings, get_settings
from core.gemini import GeminiClient
from core.rate_limit import RateLimiter

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("lifestream_bot")


async def unauthorized_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Security alert handler triggered when non-whitelisted users send updates."""
    user = update.effective_user
    user_id = user.id if user else "Unknown"
    username = user.username if user else "Unknown"
    logger.warning(
        "SECURITY: Blocked access attempt from unauthorized Telegram user ID: %s (@%s)",
        user_id,
        username,
    )
    if update.effective_message:
        await update.effective_message.reply_text(
            "⛔ **Access Denied**: Your Telegram User ID is not authorized to interact with this assistant.",
        )


def build_bot_application(
    settings: Settings | None = None,
    gemini_client: GeminiClient | None = None,
    registry: ConnectorRegistry | None = None,
) -> Application:
    """Factory creating and wiring the fully configured telegram Application instance."""
    resolved_settings = settings or get_settings()

    # 1. Initialize life-stream connectors
    if registry is None:
        registry = ConnectorRegistry()
        registry.register(MonarchConnector())
        registry.register(GmailConnector())

    # 2. Initialize Gemini Client & Agent Runner
    client = gemini_client or GeminiClient(
        api_key=resolved_settings.gemini_api_key_value,
        model=resolved_settings.gemini_model,
    )
    limiter = RateLimiter(
        max_calls=resolved_settings.rate_limit_calls_per_minute,
        window_seconds=60.0,
    )
    agent_runner = AgentRunner(
        gemini_client=client,
        registry=registry,
        rate_limiter=limiter,
    )

    # 3. Construct Telegram ApplicationBuilder
    app = (
        ApplicationBuilder()
        .token(resolved_settings.telegram_token_value)
        .build()
    )

    # Store shared dependencies in bot_data
    app.bot_data["settings"] = resolved_settings
    app.bot_data["connector_registry"] = registry
    app.bot_data["agent_runner"] = agent_runner
    app.bot_data["gemini_client"] = client

    # 4. Configure Security Whitelist Filter
    whitelist_filter = UserWhitelistFilter(allowed_user_ids=resolved_settings.allowed_telegram_user_ids)

    # 5. Register Authorized Command Handlers
    app.add_handler(CommandHandler("start", start_command, filters=whitelist_filter))
    app.add_handler(CommandHandler("status", status_command, filters=whitelist_filter))
    app.add_handler(CommandHandler("sync", sync_command, filters=whitelist_filter))

    # 6. Register Authorized Message Handlers
    app.add_handler(
        MessageHandler(
            filters.TEXT & (~filters.COMMAND) & whitelist_filter,
            text_message_handler,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.PHOTO & whitelist_filter,
            photo_message_handler,
        )
    )

    # 7. Register Security Fallback for Unauthorized Users (Group 99 ensures lowest priority)
    app.add_handler(
        MessageHandler(~whitelist_filter, unauthorized_user_handler),
        group=99,
    )

    # 8. Register Global Error Handler
    app.add_error_handler(error_handler)

    return app


async def post_init(application: Application) -> None:
    """Lifecycle hook called after bot startup to connect data streams."""
    registry: ConnectorRegistry = application.bot_data.get("connector_registry")
    if registry:
        logger.info("Initializing and connecting all life-stream connectors...")
        await registry.connect_all()
        logger.info("All life-stream connectors online.")


def main() -> None:
    """Main execution loop for the bot daemon."""
    settings = get_settings()
    logging.getLogger().setLevel(settings.log_level.upper())
    logger.info("Starting LifeStream Assistant Bot (Model: %s)...", settings.gemini_model)

    application = build_bot_application(settings=settings)
    application.post_init = post_init

    # Run Telegram long-polling loop
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
