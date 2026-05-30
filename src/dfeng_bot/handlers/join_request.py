"""Chat-join-request capture (VOL-202).

When a named invite link is created with ``creates_join_request=true`` (the
invite-only / approval flow — see ``docs/telegram-setup.md`` §6 and
``docs/entry-links.md``), a user clicking that link does NOT join immediately:
Telegram emits a ``chat_join_request`` update carrying the exact
``invite_link`` they used. This is the most reliable place to read the entry
source, because the link is guaranteed present on the request.

Scope of THIS module (VOL-202)
------------------------------
Capture the ``invite_link``, resolve it to a canonical entry source
(``services.entry_source.resolve_entry_source``), stash it in
``context.user_data`` keyed per (user, chat), and log it. We do **NOT** approve
or decline the request here, and we do **NOT** write to Sheets — both are out of
scope. Approval lands with the onboarding ticket (it would call
``update.chat_join_request.approve()``); when it does, the entry source resolved
here is already available for the post-approval persistence step.

Registered in ``handlers/__init__.py`` via ``ChatJoinRequestHandler``. Requires
``Update.CHAT_JOIN_REQUEST`` in ``app.ALLOWED_UPDATES`` and the bot to hold the
*Invite via Link* admin right.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from ..logging_setup import log_event
from ..services.entry_source import resolve_entry_source

# Same key the membership handler uses, so downstream persistence (VOL-205) reads
# one place regardless of whether the join arrived via request or direct join.
from .membership import ENTRY_SOURCE_KEY


async def handle_chat_join_request(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Resolve and stash the entry source for an incoming join request.

    Does not approve/decline (out of scope for VOL-202) — it only records the
    resolved entry source so the future approval + persistence step can use it.
    """

    request = update.chat_join_request
    if request is None:
        return

    link = getattr(request, "invite_link", None)
    link_str = getattr(link, "invite_link", None) if link is not None else None
    entry_source = resolve_entry_source(link_str)

    if context.user_data is not None:
        context.user_data[ENTRY_SOURCE_KEY] = entry_source

    log_event(
        "chat_join_request",
        update,
        member_id=request.from_user.id,
        member_username=request.from_user.username,
        entry_source=entry_source,
        outcome="source_resolved",
    )
