"""Admin moderation commands (VOL-211).

Bot commands that COMPLEMENT the native Telegram admin actions (long-press → pin
/ delete / restrict / ban, and approving join requests). They exist so a
moderator can act quickly by replying to a message, and so every action lands in
the bot's structured logs alongside the automated moderation events
(``antispam_action`` / ``flood_control`` / ``link_restriction``). See
``docs/moderation-runbook.md`` for when to use bot commands vs native actions and
the Telegram admin rights each command needs.

Commands (ALL admin-only via :func:`~dfeng_bot.handlers.base.is_admin`)
---------------------------------------------------------------------
* ``/pin``                 — reply to a message to pin it (silent pin).
* ``/del`` / ``/delete``   — reply to a message to delete it (spam removal).
* ``/mute <minutes>``      — reply or ``/mute <minutes> <user_id>``: time-bounded,
                             reversible mute via ``restrict_chat_member`` with
                             ``until_date``. ``0``/omitted minutes → permanent
                             mute (no ``until_date``) where Telegram permits.
* ``/unmute``              — reply or ``/unmute <user_id>``: restore default send
                             permissions.
* ``/ban``                 — reply or ``/ban <user_id>``: ban a member.
* ``/unban``               — reply or ``/unban <user_id>``: lift a ban.
* ``/approve``             — reply or ``/approve <user_id>``: approve a pending
                             chat join request (invite-only / approval flow).
* ``/modhelp``             — list the admin moderation commands.

Design
------
Every handler:
    1. verifies ``is_admin`` FIRST and, on a non-admin attempt, logs a rejection
       (``action=cmd_<name> outcome=denied``) and replies a brief "Not
       authorised." — mirroring ``cmd_admin_health`` / ``cmd_trust``;
    2. resolves the TARGET from the replied-to message or a ``<user_id>`` arg;
    3. performs the Telegram Bot API call inside ``try/except`` so a missing
       admin right (or any API error) is LOGGED and answered with a friendly
       failure rather than crashing the bot (the global error handler is the last
       resort, not the first);
    4. logs the outcome via :func:`log_event` (admin id is the update's
       ``telegram_id``; target user/message id + action + outcome as fields). No
       PII or message bodies are logged — only ids, actions, and outcomes.

The handlers are registered through :func:`build_moderation_handlers`, wired into
``register_handlers`` (``handlers/__init__.py``) alongside the other commands —
``app.py`` is never touched.
"""

from __future__ import annotations

from typing import Optional

from telegram import ChatPermissions, Update
from telegram.ext import CommandHandler, ContextTypes

from ..logging_setup import log_event
from .base import is_admin, reply_in_thread, thread_id_of

# Default member send-permissions restored by /unmute. ``can_send_messages``
# False is the single flag we toggle for a mute; restoring it (plus the common
# media/other flags) returns the member to ordinary posting. Group-wide member
# permissions still apply on top of these.
_UNMUTE_PERMISSIONS = ChatPermissions(
    can_send_messages=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_invite_users=True,
)

# Mute strips the ability to send messages. Telegram derives the media/other
# flags from this when False, so the single flag is enough for a full text mute.
_MUTE_PERMISSIONS = ChatPermissions(can_send_messages=False)


async def _deny(update: Update, context: ContextTypes.DEFAULT_TYPE, command: str) -> None:
    """Log + reply to a non-admin attempt at an admin command."""
    log_event(f"cmd_{command}", update, level=30, outcome="denied")  # WARNING
    await reply_in_thread(update, "Not authorised.", context=context)


def _resolve_target_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    """Resolve a target user id from a replied-to message or a trailing ``<user_id>`` arg.

    Reply target wins. Otherwise the LAST integer arg is treated as a user id, so
    ``/mute 10 123456`` (minutes then id) and ``/ban 123456`` both work.
    """

    message = update.effective_message
    reply_to = getattr(message, "reply_to_message", None) if message else None
    if reply_to is not None and getattr(reply_to, "from_user", None) is not None:
        return reply_to.from_user.id

    for arg in reversed(context.args or []):
        try:
            return int(arg)
        except ValueError:
            continue
    return None


def _parse_minutes(context: ContextTypes.DEFAULT_TYPE) -> int:
    """Parse the leading ``<minutes>`` arg for /mute. 0 (or absent/invalid) => permanent."""
    for arg in context.args or []:
        try:
            return max(0, int(arg))
        except ValueError:
            continue
    return 0


# --- /pin --------------------------------------------------------------------


async def cmd_pin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pin the replied-to message. Needs the bot's *Pin Messages* admin right."""

    if not is_admin(update, context):
        await _deny(update, context, "pin")
        return

    message = update.effective_message
    reply_to = getattr(message, "reply_to_message", None) if message else None
    chat = update.effective_chat
    thread_id = thread_id_of(update)

    if reply_to is None or chat is None:
        log_event("cmd_pin", update, outcome="no_target")
        await reply_in_thread(update, "Reply to the message you want to pin with /pin.", context=context)
        return

    try:
        await context.bot.pin_chat_message(
            chat_id=chat.id,
            message_id=reply_to.message_id,
            disable_notification=True,
        )
    except Exception as exc:  # noqa: BLE001 - missing perms must not crash the bot
        log_event(
            "cmd_pin",
            update,
            level=30,
            target_message_id=reply_to.message_id,
            thread_id=thread_id,
            error_type=type(exc).__name__,
            outcome="failed",
        )
        await reply_in_thread(
            update,
            "Couldn't pin that — the bot may be missing the 'Pin Messages' admin right.",
            context=context,
        )
        return

    log_event(
        "cmd_pin",
        update,
        target_message_id=reply_to.message_id,
        thread_id=thread_id,
        outcome="pinned",
    )
    await reply_in_thread(update, "Pinned. 📌", context=context)


# --- /del, /delete -----------------------------------------------------------


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete the replied-to message (spam removal). Needs *Delete Messages*."""

    if not is_admin(update, context):
        await _deny(update, context, "delete")
        return

    message = update.effective_message
    reply_to = getattr(message, "reply_to_message", None) if message else None
    chat = update.effective_chat
    thread_id = thread_id_of(update)

    if reply_to is None or chat is None:
        log_event("cmd_delete", update, outcome="no_target")
        await reply_in_thread(update, "Reply to the message you want to delete with /del.", context=context)
        return

    target_user = getattr(reply_to, "from_user", None)
    target_id = target_user.id if target_user else None

    try:
        await context.bot.delete_message(chat_id=chat.id, message_id=reply_to.message_id)
    except Exception as exc:  # noqa: BLE001 - missing perms must not crash the bot
        log_event(
            "cmd_delete",
            update,
            level=30,
            target_message_id=reply_to.message_id,
            target_id=target_id,
            thread_id=thread_id,
            error_type=type(exc).__name__,
            outcome="failed",
        )
        await reply_in_thread(
            update,
            "Couldn't delete that — the bot may be missing the 'Delete Messages' admin right.",
            context=context,
        )
        return

    log_event(
        "cmd_delete",
        update,
        target_message_id=reply_to.message_id,
        target_id=target_id,
        thread_id=thread_id,
        outcome="deleted",
    )
    # The /del command message itself stays as the audit trail; acknowledge briefly.
    await reply_in_thread(update, "Message removed. 🧹", context=context)


# --- /mute -------------------------------------------------------------------


async def cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mute a member: reply (or ``/mute <minutes> <user_id>``).

    ``<minutes>`` bounds the mute via ``restrict_chat_member(until_date=...)`` so
    Telegram auto-lifts it — reversible and time-bounded. ``0`` / omitted minutes
    requests a PERMANENT mute (no ``until_date``); whether a truly permanent mute
    sticks depends on the group's default permissions, so use ``/unmute`` to
    restore explicitly. Needs the *Ban / Restrict Members* admin right.
    """

    if not is_admin(update, context):
        await _deny(update, context, "mute")
        return

    chat = update.effective_chat
    thread_id = thread_id_of(update)
    target_id = _resolve_target_id(update, context)
    minutes = _parse_minutes(context)

    if chat is None or not target_id:
        log_event("cmd_mute", update, outcome="no_target")
        await reply_in_thread(
            update,
            "Usage: reply to the member with /mute <minutes>, or /mute <minutes> <user_id>. "
            "Omit minutes (or use 0) for a permanent mute.",
            context=context,
        )
        return

    # until_date must be 30s..366d for a temporary restriction; None => permanent.
    until_date: Optional[int] = None
    if minutes > 0:
        import time

        until_date = int(time.time()) + minutes * 60

    try:
        await context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=target_id,
            permissions=_MUTE_PERMISSIONS,
            until_date=until_date,
        )
    except Exception as exc:  # noqa: BLE001 - missing perms must not crash the bot
        log_event(
            "cmd_mute",
            update,
            level=30,
            target_id=target_id,
            minutes=minutes,
            thread_id=thread_id,
            error_type=type(exc).__name__,
            outcome="failed",
        )
        await reply_in_thread(
            update,
            "Couldn't mute — the bot may be missing the 'Ban / Restrict Members' admin right.",
            context=context,
        )
        return

    log_event(
        "cmd_mute",
        update,
        target_id=target_id,
        minutes=minutes,
        permanent=until_date is None,
        thread_id=thread_id,
        outcome="muted",
    )
    if until_date is None:
        await reply_in_thread(update, f"Muted user {target_id} (permanent — /unmute to lift). 🔇", context=context)
    else:
        await reply_in_thread(update, f"Muted user {target_id} for {minutes} min. 🔇", context=context)


# --- /unmute -----------------------------------------------------------------


async def cmd_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Restore a muted member's default send permissions (reply or ``/unmute <user_id>``).

    Needs the *Ban / Restrict Members* admin right.
    """

    if not is_admin(update, context):
        await _deny(update, context, "unmute")
        return

    chat = update.effective_chat
    thread_id = thread_id_of(update)
    target_id = _resolve_target_id(update, context)

    if chat is None or not target_id:
        log_event("cmd_unmute", update, outcome="no_target")
        await reply_in_thread(
            update,
            "Usage: reply to the member with /unmute, or /unmute <user_id>.",
            context=context,
        )
        return

    try:
        await context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=target_id,
            permissions=_UNMUTE_PERMISSIONS,
        )
    except Exception as exc:  # noqa: BLE001 - missing perms must not crash the bot
        log_event(
            "cmd_unmute",
            update,
            level=30,
            target_id=target_id,
            thread_id=thread_id,
            error_type=type(exc).__name__,
            outcome="failed",
        )
        await reply_in_thread(
            update,
            "Couldn't unmute — the bot may be missing the 'Ban / Restrict Members' admin right.",
            context=context,
        )
        return

    log_event("cmd_unmute", update, target_id=target_id, thread_id=thread_id, outcome="unmuted")
    await reply_in_thread(update, f"Unmuted user {target_id}. 🔊", context=context)


# --- /ban --------------------------------------------------------------------


async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ban a member (reply or ``/ban <user_id>``). Needs *Ban / Restrict Members*."""

    if not is_admin(update, context):
        await _deny(update, context, "ban")
        return

    chat = update.effective_chat
    thread_id = thread_id_of(update)
    target_id = _resolve_target_id(update, context)

    if chat is None or not target_id:
        log_event("cmd_ban", update, outcome="no_target")
        await reply_in_thread(
            update,
            "Usage: reply to the member with /ban, or /ban <user_id>.",
            context=context,
        )
        return

    try:
        await context.bot.ban_chat_member(chat_id=chat.id, user_id=target_id)
    except Exception as exc:  # noqa: BLE001 - missing perms must not crash the bot
        log_event(
            "cmd_ban",
            update,
            level=30,
            target_id=target_id,
            thread_id=thread_id,
            error_type=type(exc).__name__,
            outcome="failed",
        )
        await reply_in_thread(
            update,
            "Couldn't ban — the bot may be missing the 'Ban / Restrict Members' admin right.",
            context=context,
        )
        return

    log_event("cmd_ban", update, target_id=target_id, thread_id=thread_id, outcome="banned")
    await reply_in_thread(update, f"Banned user {target_id}. 🚫", context=context)


# --- /unban ------------------------------------------------------------------


async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lift a ban (reply or ``/unban <user_id>``). Needs *Ban / Restrict Members*.

    ``only_if_banned=True`` so unbanning is a no-op for non-banned users and never
    accidentally re-adds someone to the group.
    """

    if not is_admin(update, context):
        await _deny(update, context, "unban")
        return

    chat = update.effective_chat
    thread_id = thread_id_of(update)
    target_id = _resolve_target_id(update, context)

    if chat is None or not target_id:
        log_event("cmd_unban", update, outcome="no_target")
        await reply_in_thread(
            update,
            "Usage: reply to the member with /unban, or /unban <user_id>.",
            context=context,
        )
        return

    try:
        await context.bot.unban_chat_member(
            chat_id=chat.id, user_id=target_id, only_if_banned=True
        )
    except Exception as exc:  # noqa: BLE001 - missing perms must not crash the bot
        log_event(
            "cmd_unban",
            update,
            level=30,
            target_id=target_id,
            thread_id=thread_id,
            error_type=type(exc).__name__,
            outcome="failed",
        )
        await reply_in_thread(
            update,
            "Couldn't unban — the bot may be missing the 'Ban / Restrict Members' admin right.",
            context=context,
        )
        return

    log_event("cmd_unban", update, target_id=target_id, thread_id=thread_id, outcome="unbanned")
    await reply_in_thread(update, f"Unbanned user {target_id}. ✅", context=context)


# --- /approve ----------------------------------------------------------------


async def cmd_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Approve a pending chat join request (reply or ``/approve <user_id>``).

    For the invite-only / approval flow (``docs/telegram-setup.md`` §6). Needs the
    *Invite Users via Link* admin right. If the group does NOT use join requests,
    or the request already cleared, the call fails gracefully and the runbook
    notes approvals can also be done natively in the app.
    """

    if not is_admin(update, context):
        await _deny(update, context, "approve")
        return

    chat = update.effective_chat
    thread_id = thread_id_of(update)
    target_id = _resolve_target_id(update, context)

    if chat is None or not target_id:
        log_event("cmd_approve", update, outcome="no_target")
        await reply_in_thread(
            update,
            "Usage: reply to the join-request notice with /approve, or /approve <user_id>.",
            context=context,
        )
        return

    try:
        await context.bot.approve_chat_join_request(chat_id=chat.id, user_id=target_id)
    except Exception as exc:  # noqa: BLE001 - missing perms / no pending request must not crash
        log_event(
            "cmd_approve",
            update,
            level=30,
            target_id=target_id,
            thread_id=thread_id,
            error_type=type(exc).__name__,
            outcome="failed",
        )
        await reply_in_thread(
            update,
            "Couldn't approve — there may be no pending request, or the bot is missing the "
            "'Invite Users via Link' admin right. You can also approve natively in Telegram.",
            context=context,
        )
        return

    log_event("cmd_approve", update, target_id=target_id, thread_id=thread_id, outcome="approved")
    await reply_in_thread(update, f"Approved join request for user {target_id}. 🧡", context=context)


# --- /modhelp ----------------------------------------------------------------


_MODHELP_TEXT = (
    "Admin moderation commands (admins only):\n"
    "• /pin — reply to a message to pin it\n"
    "• /del or /delete — reply to a message to delete it\n"
    "• /mute <minutes> — reply or /mute <minutes> <user_id> (0/omitted = permanent)\n"
    "• /unmute — reply or /unmute <user_id>\n"
    "• /ban — reply or /ban <user_id>\n"
    "• /unban — reply or /unban <user_id>\n"
    "• /approve — reply or /approve <user_id> (pending join request)\n"
    "• /trust — reply or /trust <user_id> (let a new member post links)\n"
    "\nNative app actions (long-press a message, or the join-requests screen) work too. "
    "See docs/moderation-runbook.md."
)


async def cmd_modhelp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List the admin moderation commands. Admin-only."""

    if not is_admin(update, context):
        await _deny(update, context, "modhelp")
        return

    log_event("cmd_modhelp", update, outcome="ok")
    await reply_in_thread(update, _MODHELP_TEXT, context=context)


# --- registration ------------------------------------------------------------


def build_moderation_handlers() -> list[CommandHandler]:
    """Return the admin moderation command handlers for registration.

    Wired into ``register_handlers`` (``handlers/__init__.py``) in
    ``GROUP_COMMANDS`` alongside ``build_command_handlers`` — mirrors how the core
    commands are registered, without touching ``app.py``. Every handler gates on
    ``is_admin`` internally and logs both actions and rejected attempts.
    """

    return [
        CommandHandler("pin", cmd_pin),
        CommandHandler("del", cmd_delete),
        CommandHandler("delete", cmd_delete),
        CommandHandler("mute", cmd_mute),
        CommandHandler("unmute", cmd_unmute),
        CommandHandler("ban", cmd_ban),
        CommandHandler("unban", cmd_unban),
        CommandHandler("approve", cmd_approve),
        CommandHandler("modhelp", cmd_modhelp),
    ]
