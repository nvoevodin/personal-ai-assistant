"""Security filters and authorization middleware for Telegram interactions."""

import functools
import logging
from typing import Any, Callable, Coroutine
from telegram import Message, Update
from telegram.ext import ContextTypes
from telegram.ext.filters import MessageFilter

from core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class UserWhitelistFilter(MessageFilter):
    """Telegram message filter ensuring updates only process for whitelisted user IDs."""

    def __init__(self, allowed_user_ids: set[int]) -> None:
        super().__init__()
        self.allowed_user_ids = allowed_user_ids

    def filter(self, message: Message) -> bool:
        if not message.from_user:
            return False
        return message.from_user.id in self.allowed_user_ids


def authorized_only(
    func: Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[Any, Any, None]]
) -> Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[Any, Any, None]]:
    """Decorator guarding handler entrypoints against unauthorized Telegram users."""

    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        settings: Settings = get_settings()
        user = update.effective_user
        user_id = user.id if user else None

        if not settings.is_user_allowed(user_id):
            logger.warning(
                "Unauthorized access attempt rejected. User ID: %s, Username: %s",
                user_id,
                user.username if user else "Unknown",
            )
            if update.effective_message:
                await update.effective_message.reply_text(
                    "⛔ **Access Denied**: Your Telegram User ID is not authorized to interact with this personal assistant.",
                )
            return

        await func(update, context)

    return wrapper
