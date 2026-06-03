"""Welcome onboarding on member join (VOL-203).

When a new member joins the configured supergroup, the bot posts a single
welcome message that points them to the six community topics. It must never
block entry or require any user action.

Where the welcome appears
-------------------------
Telegram delivers a new member's join as either a ``new_chat_members`` service
message or a ``chat_member`` update. In a forum supergroup these join signals
land in the group's "General" topic (``message_thread_id`` 1) — Telegram does
not let a join originate inside an arbitrary topic. So by default we reply where
the join is observed (the General topic), via :func:`reply_in_thread`.

If the deployment configures a dedicated welcome topic (``config.welcome_topic``
> 0, env ``DFENG_WELCOME_TOPIC``) we PREFER posting the welcome there instead, so
onboarding lives in a predictable place rather than the noisy General topic. This
is done by sending directly to ``config.group_id`` with that ``message_thread_id``.

Dedupe
------
Telegram can deliver duplicate join signals for the same user (e.g. both a
service message and a ``chat_member`` update, or retried updates). We keep a
simple in-memory ``{telegram_id: last_welcomed_monotonic_ts}`` map and skip a
welcome if we already welcomed that user within :data:`DEDUPE_TTL_SECONDS`.

This dedupe is per-process and NOT shared across instances — acceptable for the
v1 single-instance deployment. A multi-instance deployment would need a shared
store (Redis, the Sheets row, etc.).

Hand-off to qualification (VOL-204)
-----------------------------------
After welcoming, :func:`start_qualification` is invoked as an extension seam.
The real flow lives in ``handlers/qualification.py``; this module's
:func:`start_qualification` is a thin delegate to it. Welcome imports
qualification (one direction only) to avoid a circular import — qualification
must NOT import welcome.
"""

from __future__ import annotations

import time

from telegram import Update, User
from telegram.ext import ContextTypes

from ..logging_setup import log_event
from .base import address, get_config, reply_in_thread

# Verbatim welcome copy (VOL-203). Stored as a constant so other tickets
# (e.g. VOL-201) can reference the exact wording. Do not edit without updating
# the ticket — acceptance criteria assert all six topics and this wording.
WELCOME_MESSAGE = (
    "Welcome to Dongfeng Experience Singapore 🚗 — Start here: "
    "📢 Announcements & Events / "
    "💬 General Community Chat / "
    "🚗 BOX Owners Lounge / "
    "🕶 007 Owners Club / "
    "🏕 VIGO Owners Circle / "
    "🛠 Need support? Head to Support & Assistance"
)

# In-memory dedupe window. If the same telegram_id is seen again within this
# many seconds, we skip the duplicate welcome. Per-process only (see module doc).
DEDUPE_TTL_SECONDS = 600

# telegram_id -> last welcomed timestamp (monotonic seconds).
_recent_welcomes: dict[int, float] = {}


def _already_welcomed(telegram_id: int, *, now: float | None = None) -> bool:
    """Return True if we welcomed ``telegram_id`` within the TTL window.

    Records ``now`` as the latest welcome time when returning False (i.e. when
    the caller should proceed to welcome). Also opportunistically evicts expired
    entries so the map does not grow without bound.
    """

    now = time.monotonic() if now is None else now

    # Evict expired entries to keep the map bounded (cheap; join rate is low).
    expired = [tid for tid, ts in _recent_welcomes.items() if now - ts > DEDUPE_TTL_SECONDS]
    for tid in expired:
        _recent_welcomes.pop(tid, None)

    last = _recent_welcomes.get(telegram_id)
    if last is not None and now - last <= DEDUPE_TTL_SECONDS:
        return True

    _recent_welcomes[telegram_id] = now
    return False


async def send_welcome(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    member: User,
) -> None:
    """Post the welcome message for a freshly joined ``member``.

    Gated by ``config.features.welcome``. Deduped per-process. Never raises into
    the caller (a failed welcome must not block entry); failures are logged.
    Hands off to :func:`start_qualification` after a successful welcome.
    """

    config = get_config(context)

    if not config.features.welcome:
        log_event(
            "welcome_skipped",
            update,
            member_id=member.id,
            member_username=member.username,
            outcome="feature_disabled",
        )
        return

    if _already_welcomed(member.id):
        log_event(
            "welcome_skipped",
            update,
            member_id=member.id,
            member_username=member.username,
            outcome="duplicate",
        )
        return

    # @-tag the joiner so it's clear who the bot is greeting (multiple members
    # may join around the same time and all land in General).
    text = f"{address(member)} 👋\n\n{WELCOME_MESSAGE}"

    welcome_topic = config.welcome_topic
    try:
        if welcome_topic and config.group_id:
            # Prefer the dedicated welcome topic when configured. Joins are
            # observed in General, so we send directly with the welcome thread id.
            await context.bot.send_message(
                chat_id=config.group_id,
                text=text,
                message_thread_id=welcome_topic,
            )
            posted_thread = welcome_topic
        else:
            # Fall back to replying where the join was observed (General topic).
            await reply_in_thread(update, text, context=context)
            posted_thread = getattr(
                getattr(update, "effective_message", None), "message_thread_id", None
            )
    except Exception as exc:  # noqa: BLE001 - welcome must never block entry
        log_event(
            "welcome_failed",
            update,
            level=40,  # logging.ERROR
            member_id=member.id,
            member_username=member.username,
            error_type=type(exc).__name__,
            outcome="send_error",
        )
        return

    log_event(
        "welcome_sent",
        update,
        member_id=member.id,
        member_username=member.username,
        thread_id=posted_thread,
        outcome="welcomed",
    )

    # Hand off to the future qualification flow (VOL-204). No-op stub today.
    await start_qualification(update, context, member)


async def start_qualification(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    member: User,
) -> None:
    """Hand off to the qualification flow (VOL-204).

    Thin delegate to ``handlers/qualification.start_qualification`` (imported
    locally to keep the welcome <-> qualification dependency one-directional and
    avoid a circular import). That implementation honours
    ``config.features.qualification`` and never blocks entry.
    """

    from .qualification import start_qualification as _start_qualification

    await _start_qualification(update, context, member)
