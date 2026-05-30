"""Central handler registration — the dispatcher future tickets extend.

``register_handlers(application, config)`` is the single integration point. New
feature tickets add their handlers here (or via the per-module factory funcs)
rather than touching ``app.py``.

Handler group ordering note:
    python-telegram-bot runs handlers in ascending *group* number, and within a
    group stops at the first that doesn't raise ``ApplicationHandlerStop``.
    We register message handlers in a higher group than commands so commands
    always match first. Anti-spam / flood control (future) should register in a
    LOW group (e.g. -1) so they run before normal message handling and can call
    ``raise ApplicationHandlerStop`` to consume abusive updates.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatJoinRequestHandler,
    ChatMemberHandler,
    MessageHandler,
    filters,
)

from ..config import Config
from ..logging_setup import get_logger
from . import antispam, flood_control, link_restrictions
from .commands import build_command_handlers
from .join_request import handle_chat_join_request
from .moderation import build_moderation_handlers
from .membership import handle_chat_member_update, handle_new_chat_members
from .messages import handle_callback_query, handle_message

# Handler groups (lower runs first).
GROUP_PREFILTER = -1  # reserved for future anti-spam / flood control
GROUP_COMMANDS = 0
GROUP_MEMBERSHIP = 0
GROUP_MESSAGES = 1


def register_handlers(application: Application, config: Config) -> None:
    """Register all handlers on the application.

    Args:
        application: The built PTB Application.
        config: Runtime configuration (also stored in ``bot_data`` by app.py).
    """

    log = get_logger()

    # --- Prefilter: anti-spam / flood control (GROUP_PREFILTER, runs first) ---
    # These run before commands/messages so they can consume abusive updates via
    # ApplicationHandlerStop. This is the SHARED prefilter seam: VOL-208 owns the
    # anti-spam handler below; VOL-209 (new-user link restriction) and VOL-210
    # (flood control) add their OWN MessageHandler(s) in this same group with a
    # similar filter. Order within the group is registration order — register
    # cheaper/earlier-deciding checks first. Each handler must be self-contained
    # and only raise ApplicationHandlerStop when it actually actions the update,
    # so siblings (and normal handlers) still see non-spam messages.
    #
    # VOL-208 anti-spam: inspect text/caption messages, delete spam, stop.
    application.add_handler(
        MessageHandler(
            (filters.TEXT | filters.CAPTION) & ~filters.StatusUpdate.ALL,
            antispam.check,
        ),
        group=GROUP_PREFILTER,
    )
    # VOL-209 link restriction: block links from new/low-trust members until they
    # cross the trust threshold (join age OR clean-message count OR qualified OR
    # admin-approved). Registered AFTER anti-spam (so it only sees non-spam, never
    # re-deleting what anti-spam removed) and BEFORE/with flood control in the same
    # group. link_restrictions.check raises ApplicationHandlerStop ONLY when it
    # actually removes a link message; a clean message passes through AND increments
    # the member's clean_message_count for trust progression. Matches text + caption
    # messages (links can ride captions on media). Default OFF (feature-flagged).
    application.add_handler(
        MessageHandler(
            (filters.TEXT | filters.CAPTION) & ~filters.StatusUpdate.ALL & ~filters.COMMAND,
            link_restrictions.check,
        ),
        group=GROUP_PREFILTER,
    )
    #
    # VOL-210 flood control: per-user message-rate cap across ALL topics.
    # Registered AFTER anti-spam in the SAME group so both prefilter handlers
    # coexist: anti-spam (content) runs first, flood control (rate) second.
    # flood_control.check raises ApplicationHandlerStop ONLY when it mutes/deletes
    # (a bare "warn" lets the chain continue), so it never double-stops with
    # anti-spam and lets non-flooding messages reach downstream handlers. We match
    # ALL non-status messages (not just text) since flooding is rate-based, not
    # content-based — every message a user sends counts toward their limit.
    application.add_handler(
        MessageHandler(
            ~filters.StatusUpdate.ALL & ~filters.COMMAND,
            flood_control.check,
        ),
        group=GROUP_PREFILTER,
    )

    # --- Commands (/start, /ping, /health, future admin commands) ------------
    for handler in build_command_handlers():
        application.add_handler(handler, group=GROUP_COMMANDS)

    # --- Admin moderation commands (VOL-211) ---------------------------------
    # /pin /del /delete /mute /unmute /ban /unban /approve /modhelp. Each gates on
    # is_admin internally (rejections logged) and handles missing-permission API
    # errors gracefully. Registered in GROUP_COMMANDS alongside the core commands,
    # mirroring build_command_handlers — app.py is untouched.
    for handler in build_moderation_handlers():
        application.add_handler(handler, group=GROUP_COMMANDS)

    # --- Membership: new-member joins ---------------------------------------
    # 1) Classic join service messages.
    application.add_handler(
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_chat_members),
        group=GROUP_MEMBERSHIP,
    )
    # 2) chat_member updates (invite-link / approval joins without a service msg).
    #    Requires the bot to be an admin and the chat_member update to be allowed.
    application.add_handler(
        ChatMemberHandler(handle_chat_member_update, ChatMemberHandler.CHAT_MEMBER),
        group=GROUP_MEMBERSHIP,
    )
    # 3) chat_join_request updates (VOL-202): for invite-only links created with
    #    creates_join_request=true, captures the invite_link to resolve the entry
    #    source. Does not approve/decline (onboarding ticket owns that). Requires
    #    Update.CHAT_JOIN_REQUEST in app.ALLOWED_UPDATES and the bot's Invite-via-
    #    Link admin right.
    application.add_handler(
        ChatJoinRequestHandler(handle_chat_join_request),
        group=GROUP_MEMBERSHIP,
    )

    # --- Callback queries (inline buttons for future welcome/qualification) ---
    application.add_handler(
        CallbackQueryHandler(handle_callback_query), group=GROUP_COMMANDS
    )

    # --- Generic messages (lowest priority; commands match first) ------------
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & ~filters.StatusUpdate.ALL,
            handle_message,
        ),
        group=GROUP_MESSAGES,
    )

    # --- EXTENSION POINTS for future tickets ---------------------------------
    # Register these in GROUP_PREFILTER (-1) so they run before normal handling
    # and can consume abusive updates via ApplicationHandlerStop:
    #   * anti-spam (VOL-208)             -> DONE: antispam.check (above)
    #   * new-user link restriction (VOL-209) -> DONE: link_restrictions.check (above)
    #   * flood control / rate limiting (VOL-210) -> DONE: flood_control.check (above)
    # Register normal feature handlers in their own groups:
    #   * onboarding / welcome (VOL-203)  -> DONE: membership.on_new_member ->
    #     welcome.send_welcome (no new handler needed; rides the join handlers)
    #   * qualification (VOL-204)         -> messages + callback queries
    #   * sheets persistence (VOL-198/..) -> services/sheets.py
    #   * support redirection (VOL-207)   -> DONE: messages.handle_message ->
    #     support_redirect.maybe_redirect (observer; rides the generic message
    #     handler, no new handler needed)

    log.info(
        "handlers_registered",
        extra={
            "action": "handlers_registered",
            "groups": [GROUP_PREFILTER, GROUP_COMMANDS, GROUP_MEMBERSHIP, GROUP_MESSAGES],
        },
    )


__all__ = ["register_handlers", "Update"]
