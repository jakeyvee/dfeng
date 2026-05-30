"""Bot command handlers: /start, /ping, and an admin extension point.

VOL-197 ships:
    * ``/start`` — basic acknowledgement.
    * ``/ping``  — health check that replies IN THE SAME topic/thread, proving
      the bot can read thread context and reply into it (acceptance criterion).

Future admin/moderation commands (ban, mute, trust, stats, reload) register
alongside these — see :func:`build_command_handlers`.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from ..logging_setup import log_event
from .base import is_admin, reply_in_thread, thread_id_of
from .qualification import cmd_qualify


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Acknowledge /start. Welcome content proper lives in VOL-203."""
    log_event("cmd_start", update, outcome="ack")
    await reply_in_thread(
        update,
        "Dongfeng Experience Community bot is online.",
        context=context,
    )


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Health check — replies 'pong' into the originating topic/thread.

    Demonstrates reading ``message_thread_id`` and replying in-thread.
    """
    thread_id = thread_id_of(update)
    log_event("cmd_ping", update, thread_id=thread_id, outcome="pong")
    await reply_in_thread(
        update,
        f"pong (thread_id={thread_id})" if thread_id else "pong",
        context=context,
    )


async def cmd_admin_health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin-only health/status command stub.

    Demonstrates the admin gate. Future moderation commands follow this pattern:
    check ``is_admin`` first, then act.
    """
    if not is_admin(update, context):
        log_event("cmd_admin_health", update, outcome="denied", level_hint="warn")
        await reply_in_thread(update, "Not authorised.", context=context)
        return

    log_event("cmd_admin_health", update, outcome="ok")
    await reply_in_thread(update, "OK: bot healthy, handlers registered.", context=context)


def build_command_handlers() -> list[CommandHandler]:
    """Return the command handlers for registration.

    EXTENSION POINT: append new ``CommandHandler`` entries here (admin/mod
    commands, qualification triggers, etc.). Keeping construction in one place
    keeps ``handlers/__init__.py`` thin.
    """
    return [
        CommandHandler("start", cmd_start),
        CommandHandler("ping", cmd_ping),
        CommandHandler("health", cmd_admin_health),
        # VOL-204 manual qualification (re)start. Documented retry path so a user
        # can (re)trigger the Owner/Prospect flow at any time.
        CommandHandler("qualify", cmd_qualify),
    ]
