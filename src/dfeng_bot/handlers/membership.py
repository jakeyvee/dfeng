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
from ..services.entry_source import resolve_entry_source
from .base import get_config
from .link_restrictions import record_join
from .welcome import send_welcome

# Key under which the resolved entry source is stashed in ``context.user_data``
# for the persistence layer (VOL-205) to read and write into the workbook's
# "Entry source" column. user_data is keyed per (user, chat) by PTB.
ENTRY_SOURCE_KEY = "entry_source"


def _invite_link_string(cmu: ChatMemberUpdated) -> str | None:
    """Pull the invite-link string off a ``chat_member`` update, if present.

    Telegram populates ``ChatMemberUpdated.invite_link`` only when the join went
    through a *named/primary* invite link the bot can see (it must hold the
    *Invite via Link* admin right). Returns ``None`` otherwise (e.g. the member
    was added by someone, or the join came via a request handled elsewhere).
    """

    link = getattr(cmu, "invite_link", None)
    return getattr(link, "invite_link", None) if link is not None else None


async def on_new_member(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    member: User,
    *,
    entry_source: str | None = None,
) -> str:
    """EXTENSION HOOK — runs once per newly joined member.

    Orchestration only — real logic lives in dedicated modules:
        * VOL-203 welcome: ``welcome.send_welcome`` (feature-flagged + deduped;
          it also hands off to the qualification seam after welcoming).
        * VOL-198/205/206 sheets: persist the new member (call from here). The
          resolved ``entry_source`` returned here / stashed in
          ``context.user_data[ENTRY_SOURCE_KEY]`` is the value for the workbook's
          "Entry source" column.
        * VOL-209 link restriction: ``record_join`` stamps the member's join time
          in the trust store so the link-restriction trust threshold (join age /
          clean-message progression) starts from this moment.

    Args:
        entry_source: Pre-resolved entry source from the caller (the join handler
            already read ``invite_link``). When ``None`` we resolve from the
            update's invite link here so every join path yields a value.

    Returns:
        The canonical entry-source id (see ``services.schema.ENTRY_SOURCES``),
        also stashed in ``context.user_data[ENTRY_SOURCE_KEY]`` for VOL-205.

    Note: ``send_welcome`` performs its own dedupe and ``features.welcome`` gate,
    so duplicate join signals for the same user yield at most one welcome.
    """

    config = get_config(context)

    # VOL-202: resolve the entry source and make it available to persistence.
    if entry_source is None:
        cmu = getattr(update, "chat_member", None)
        link = _invite_link_string(cmu) if cmu is not None else None
        entry_source = resolve_entry_source(link)
    if context.user_data is not None:
        context.user_data[ENTRY_SOURCE_KEY] = entry_source

    # VOL-209: record join time so the link-restriction trust threshold (join age
    # / clean-message progression) starts counting from the moment of join.
    record_join(member.id)

    log_event(
        "new_member_hook",
        update,
        member_id=member.id,
        member_username=member.username,
        outcome="dispatched",
        welcome_enabled=config.features.welcome,
        entry_source=entry_source,
    )

    # VOL-203 welcome onboarding (no-op when DFENG_FEATURE_WELCOME is off).
    await send_welcome(update, context, member)
    return entry_source


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

    # VOL-202: this update can carry the named invite link the member used.
    entry_source = resolve_entry_source(_invite_link_string(cmu))
    log_event(
        "new_member",
        update,
        member_id=member.id,
        source="chat_member_update",
        entry_source=entry_source,
    )
    await on_new_member(update, context, member, entry_source=entry_source)


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
