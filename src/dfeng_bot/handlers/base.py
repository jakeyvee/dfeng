"""Shared handler helpers used across the handlers package.

These are the primitives future tickets reuse: replying into the originating
topic/thread, admin checks, and pulling the :class:`Config` out of the bot's
shared application data.
"""

from __future__ import annotations

from typing import Optional

from telegram import ChatPermissions, Message, Update
from telegram.ext import ContextTypes

from ..config import Config
from ..logging_setup import log_event

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


async def mute_member(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int
) -> bool:
    """Restrict a member from sending messages (gate until qualified).

    Inline-button taps still work while muted, so the user can still answer the
    qualification with a tap. Best-effort — needs the bot's *Restrict Members*
    right; on failure we log and fail OPEN (the member is simply not gated rather
    than the bot crashing). Returns True on success.
    """

    try:
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(can_send_messages=False),
        )
        return True
    except Exception as exc:  # noqa: BLE001 - gating must never crash a join
        log_event(
            "mute_member_failed",
            None,
            member_id=user_id,
            chat_id=chat_id,
            error_type=type(exc).__name__,
            outcome="mute_error",
        )
        return False


async def unmute_member(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int
) -> bool:
    """Lift a member's restriction, restoring the group's default member permissions.

    Re-applies the chat's own default permissions (so the member ends up exactly
    like everyone else); falls back to a permissive set if the chat can't be
    fetched. Best-effort; logs on failure. Returns True on success.
    """

    perms = None
    try:
        chat = await context.bot.get_chat(chat_id)
        perms = getattr(chat, "permissions", None)
    except Exception:  # noqa: BLE001 - fall back to a permissive default below
        perms = None
    if perms is None:
        perms = ChatPermissions(
            can_send_messages=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_invite_users=True,
        )
    try:
        await context.bot.restrict_chat_member(
            chat_id=chat_id, user_id=user_id, permissions=perms
        )
        return True
    except Exception as exc:  # noqa: BLE001 - never block completion on an unmute
        log_event(
            "unmute_member_failed",
            None,
            member_id=user_id,
            chat_id=chat_id,
            error_type=type(exc).__name__,
            outcome="unmute_error",
        )
        return False
