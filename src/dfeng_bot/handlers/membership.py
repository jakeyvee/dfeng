"""New-member join handling.

VOL-197 scope: detect joins, log them structurally, and expose an
:func:`on_new_member` hook. The welcome ticket (VOL-203) and qualification
ticket (VOL-204) fill in the actual behaviour — they should edit
``on_new_member`` (or register additional handlers) rather than this dispatch
plumbing.

Two join signals are handled:
    * ``StatusUpdate.NEW_CHAT_MEMBERS`` service messages (classic joins).
    * ``ChatMemberHandler`` updates (covers joins via invite links / approvals
      where no service message is posted). Registered in ``__init__.py``.
"""

from __future__ import annotations

from telegram import ChatMember, ChatMemberUpdated, Update, User
from telegram.ext import ContextTypes

from ..logging_setup import log_event
from .base import get_config
from .welcome import send_welcome


async def on_new_member(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    member: User,
) -> None:
    """EXTENSION HOOK — runs once per newly joined member.

    Orchestration only — real logic lives in dedicated modules:
        * VOL-203 welcome: ``welcome.send_welcome`` (feature-flagged + deduped;
          it also hands off to the qualification seam after welcoming).
        * VOL-198/205/206 sheets: persist the new member (call from here).
        * anti-spam: apply join-time restrictions for untrusted users.

    Note: ``send_welcome`` performs its own dedupe and ``features.welcome`` gate,
    so duplicate join signals for the same user yield at most one welcome.
    """

    config = get_config(context)
    log_event(
        "new_member_hook",
        update,
        member_id=member.id,
        member_username=member.username,
        outcome="dispatched",
        welcome_enabled=config.features.welcome,
    )

    # VOL-203 welcome onboarding (no-op when DFENG_FEATURE_WELCOME is off).
    await send_welcome(update, context, member)


async def handle_new_chat_members(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle ``new_chat_members`` service messages (classic joins)."""

    message = update.effective_message
    if message is None or not message.new_chat_members:
        return

    for member in message.new_chat_members:
        if member.is_bot:
            log_event("new_member_skipped_bot", update, member_id=member.id)
            continue
        log_event("new_member", update, member_id=member.id, source="service_message")
        await on_new_member(update, context, member)


async def handle_chat_member_update(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle ``chat_member`` updates to catch joins without service messages."""

    cmu: ChatMemberUpdated | None = update.chat_member
    if cmu is None:
        return

    if not _became_member(cmu):
        # Leaves, bans, role changes — log lightly; future moderation ticket
        # can branch on these transitions.
        log_event(
            "chat_member_transition",
            update,
            old_status=cmu.old_chat_member.status,
            new_status=cmu.new_chat_member.status,
        )
        return

    member = cmu.new_chat_member.user
    if member.is_bot:
        return
    log_event("new_member", update, member_id=member.id, source="chat_member_update")
    await on_new_member(update, context, member)


def _became_member(cmu: ChatMemberUpdated) -> bool:
    """True when a status transition represents a fresh join."""
    was_in = cmu.old_chat_member.status in {
        ChatMember.MEMBER,
        ChatMember.ADMINISTRATOR,
        ChatMember.OWNER,
        ChatMember.RESTRICTED,
    }
    is_in = cmu.new_chat_member.status in {
        ChatMember.MEMBER,
        ChatMember.ADMINISTRATOR,
        ChatMember.OWNER,
    }
    return is_in and not was_in
