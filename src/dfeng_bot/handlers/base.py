"""Shared handler helpers used across the handlers package.

These are the primitives future tickets reuse: replying into the originating
topic/thread, admin checks, and pulling the :class:`Config` out of the bot's
shared application data.
"""

from __future__ import annotations

from typing import Optional

from telegram import Message, Update
from telegram.ext import ContextTypes

from ..config import Config

# Key under which the Config is stored in ``application.bot_data``.
CONFIG_KEY = "config"


def get_config(context: ContextTypes.DEFAULT_TYPE) -> Config:
    """Return the Config stored on the application (set in app.py)."""
    config = context.application.bot_data.get(CONFIG_KEY)
    if config is None:  # pragma: no cover - defensive; app.py always sets it
        raise RuntimeError("Config not found in application.bot_data")
    return config


def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """True if the update's effective user is a configured admin/moderator."""
    user = update.effective_user
    return get_config(context).is_admin(user.id if user else None)


def thread_id_of(update: Update) -> Optional[int]:
    """Return the forum topic / thread id of the triggering message, if any."""
    message = update.effective_message
    return getattr(message, "message_thread_id", None) if message else None


async def reply_in_thread(
    update: Update,
    text: str,
    *,
    context: Optional[ContextTypes.DEFAULT_TYPE] = None,
    **kwargs,
) -> Optional[Message]:
    """Reply to the triggering message in the SAME topic/thread.

    Passing ``message_thread_id`` ensures replies land in the originating forum
    topic rather than the group's General topic. This is the canonical way for
    any handler to talk back to the user.

    Args:
        update: The incoming update.
        text: Reply text.
        context: Optional context; used as a fallback to send via ``bot`` when
            there is no message to reply to directly.
        **kwargs: Extra ``send_message`` kwargs (parse_mode, reply_markup, ...).
    """

    message = update.effective_message
    thread_id = thread_id_of(update)

    if message is not None:
        return await message.reply_text(
            text,
            message_thread_id=thread_id,
            **kwargs,
        )

    # No message to reply to (e.g. some chat_member updates) — send directly.
    if context is not None and update.effective_chat is not None:
        return await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            message_thread_id=thread_id,
            **kwargs,
        )
    return None
