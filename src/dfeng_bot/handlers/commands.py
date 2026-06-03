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
from .. import metrics
from .base import is_admin, reply_in_thread, thread_id_of
from .link_restrictions import cmd_trust
from .onboarding import cmd_profile
from .qualification import cmd_qualify


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Acknowledge /start, or begin DM PII capture for the ``profile`` deep link.

    ``/start profile`` in a PRIVATE chat (from the "Share privately" button in the
    group offer) hands off to the private phone/plate capture; everything else
    just acknowledges.
    """
    args = context.args or []
    chat_type = getattr(update.effective_chat, "type", None)
    if chat_type == "private" and args and args[0].strip().lower() == "profile":
        from . import onboarding

        await onboarding.start_dm_pii_capture(update, context)
        return

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


def _get_write_queue_for_status(context: ContextTypes.DEFAULT_TYPE):
    """Return the shared write queue from ``bot_data`` (VOL-206), or None."""
    from ..services.write_queue import WRITE_QUEUE_KEY

    return context.application.bot_data.get(WRITE_QUEUE_KEY)


async def cmd_sheets_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin-only ``/sheets_status`` — show the Sheets write-queue stats (VOL-206).

    Surfaces pending / in-flight / dead-letter counts so the queue is observable
    out-of-band even when Sheets is down. Admin-gated via :func:`is_admin`. Never
    prints PII (phone/plate) — only counts.
    """

    if not is_admin(update, context):
        log_event("cmd_sheets_status", update, level=30, outcome="denied")
        await reply_in_thread(update, "Not authorised.", context=context)
        return

    queue = _get_write_queue_for_status(context)
    if queue is None:
        log_event("cmd_sheets_status", update, outcome="disabled")
        await reply_in_thread(
            update,
            "Sheets write queue is disabled (writes use the direct path).",
            context=context,
        )
        return

    stats = queue.stats()
    log_event("cmd_sheets_status", update, outcome="ok", **stats)
    text = (
        "Sheets write queue:\n"
        f"• running: {stats['running']}\n"
        f"• pending: {stats['pending']}\n"
        f"• in-flight: {stats['inflight']}\n"
        f"• dead-letter: {stats['dead_letter']}\n"
        f"• persisted OK: {stats['processed_ok']}\n"
        f"• enqueued total: {stats['enqueued_total']}\n"
        f"• dropped (queue full): {stats['dropped_full']}\n"
        "\nUse /reconcile to list dead-lettered Telegram IDs."
    )
    await reply_in_thread(update, text, context=context)


async def cmd_reconcile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin-only ``/reconcile`` — list dead-lettered Telegram IDs (VOL-206).

    Lists the Telegram IDs (+ public username, attempt count, error class) of
    writes that exhausted all retries so an admin can manually backfill the sheet.
    NEVER prints phone/plate (``schema.PII_COLUMNS``) — the dead-letter records
    don't even carry them.
    """

    if not is_admin(update, context):
        log_event("cmd_reconcile", update, level=30, outcome="denied")
        await reply_in_thread(update, "Not authorised.", context=context)
        return

    queue = _get_write_queue_for_status(context)
    if queue is None:
        await reply_in_thread(
            update, "Sheets write queue is disabled.", context=context
        )
        return

    dead = queue.dead_letters()
    log_event("cmd_reconcile", update, outcome="ok", dead_letter=len(dead))
    if not dead:
        await reply_in_thread(update, "No dead-lettered writes. ✅", context=context)
        return

    lines = ["Dead-lettered writes needing reconciliation:"]
    for dl in dead[:50]:  # cap the message length
        handle = f"@{dl.username}" if dl.username else "(no username)"
        lines.append(
            f"• id={dl.telegram_id} {handle} attempts={dl.attempts} err={dl.error_type}"
        )
    if len(dead) > 50:
        lines.append(f"… and {len(dead) - 50} more.")
    await reply_in_thread(update, "\n".join(lines), context=context)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin-only ``/stats`` — report process-lifetime metric counters (VOL-212).

    Reports the cheaply-computable launch metrics tallied in-memory since the
    process last started: onboarding completion (started/completed + rate),
    support-redirect count, automated spam-removal count, and message-activity
    totals (owner/prospect breakdown). These are PII-free integers and are NOT
    historical — they reset on restart. For authoritative, time-windowed figures
    see ``docs/metrics-and-reporting.md`` (structured logs + Sheets workbook).
    """

    if not is_admin(update, context):
        log_event("cmd_stats", update, level=30, outcome="denied")
        await reply_in_thread(update, "Not authorised.", context=context)
        return

    counters = metrics.get_counters(context.application.bot_data)
    d = counters.as_dict()
    rate = counters.onboarding_completion_rate()
    rate_str = f"{rate * 100:.0f}%" if rate is not None else "n/a (none started)"

    log_event("cmd_stats", update, outcome="ok", **d)
    text = (
        "Process-lifetime metrics (since last restart — NOT historical):\n"
        f"• onboarding: {d['qualification_complete']}/{d['qualification_started']} "
        f"completed ({rate_str})\n"
        f"• support redirects: {d['support_redirect']}\n"
        f"• automated spam removals: {d['spam_action']}\n"
        f"• messages seen: {d['activity_total']} "
        f"(owner {d['activity_owner']}, prospect {d['activity_prospect']})\n"
        "\nFor historical / weekly figures see docs/metrics-and-reporting.md."
    )
    await reply_in_thread(update, text, context=context)


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
        # VOL-205 manual optional-profile (re)capture: /profile (re)opens the
        # PDPA-gated phone/plate capture at any time. Gated by the feature flag
        # inside; persists required fields even when optional is declined.
        CommandHandler("profile", cmd_profile),
        # VOL-209 admin-only manual trust/approve: reply with /trust or
        # /trust <user_id> to let a member post links. Gated by is_admin inside.
        CommandHandler("trust", cmd_trust),
        # VOL-206 admin-only Sheets write-queue observability: /sheets_status shows
        # pending/in-flight/dead-letter counts; /reconcile lists dead-lettered
        # Telegram IDs for manual backfill. Both gate on is_admin inside; never
        # print PII (phone/plate).
        CommandHandler("sheets_status", cmd_sheets_status),
        CommandHandler("reconcile", cmd_reconcile),
        # VOL-212 admin-only launch metrics: /stats reports process-lifetime
        # counters (onboarding completion, support redirects, automated spam
        # removals, message activity). Gates on is_admin inside; PII-free.
        CommandHandler("stats", cmd_stats),
    ]
