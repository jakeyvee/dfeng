"""Deep-link DM onboarding (Option A) — private, gated entry.

Instead of sharing a *group* invite link, the entry points (QR / Linktree /
salesperson) are BOT deep links ``https://t.me/<bot>?start=<source>``. The user
opens the bot in private and answers ALL onboarding questions there
(qualification + PDPA-gated phone/plate) — nothing is typed in a public topic.
Only on completion does the bot mint a SINGLE-USE invite link so they join the
group already vetted.

Why a deep link (the hard Telegram rule): a bot cannot DM a user who has not
pressed Start on it. The deep link IS that opt-in — clicking ``?start=...``
opens the bot chat and delivers the payload, after which the bot may DM freely.

Flow
----
1. ``/start <source>`` in a PRIVATE chat (handled by ``commands.cmd_start`` ->
   :func:`maybe_start_dm_onboarding`).
2. Resolve the entry source from the payload, stash it + a DM flag in
   ``user_data``, greet, and start the existing qualification flow — which then
   hands off to the existing PDPA/optional-capture flow, all in the DM.
3. When ``onboarding._finish_and_persist`` completes, it calls
   :func:`grant_access` (guarded by the DM flag), which creates a single-use
   ``createChatInviteLink`` and DMs it to the user.

Gated behind ``config.features.dm_onboarding`` (``DFENG_FEATURE_DM_ONBOARDING``,
default OFF). When OFF, onboarding runs in-group as before and ``/start`` just
acknowledges.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from ..logging_setup import log_event
from .base import get_config, reply_in_thread

# user_data flag marking that this user is onboarding via the private DM flow,
# so the persistence step knows to grant a single-use invite link on completion.
DM_ONBOARDING_FLAG = "dm_onboarding"

# /start deep-link payload token -> canonical entry source (schema.ENTRY_SOURCES).
# Tokens are URL-safe (Telegram start payloads allow [A-Za-z0-9_-], <=64 chars),
# so they map onto the human-readable source ids here.
START_PAYLOAD_TO_SOURCE: dict[str, str] = {
    "showroom": "showroom QR",
    "roadshow": "roadshow QR",
    "event": "event QR",
    "linktree": "Linktree",
    "salesperson": "salesperson",
    "website": "website placeholder",
}

# Default when the deep link carries no / an unknown payload.
DEFAULT_SOURCE = "salesperson"

GREETING = (
    "Welcome to Dongfeng Experience Singapore 🧡\n\n"
    "Let's get you set up — just a couple of quick questions here in private. "
    "Once you're done I'll send you your personal link to join the community 🚗"
)


def source_for_payload(token: str) -> str:
    """Map a ``/start`` payload token to a canonical entry source (pure)."""
    return START_PAYLOAD_TO_SOURCE.get((token or "").strip().lower(), DEFAULT_SOURCE)


async def maybe_start_dm_onboarding(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """Kick off DM onboarding for a private ``/start`` when the feature is on.

    Returns ``True`` if it handled the update (the caller should stop), or
    ``False`` so ``commands.cmd_start`` falls back to its default acknowledgement.
    """

    config = get_config(context)
    if not config.features.dm_onboarding:
        return False

    chat = update.effective_chat
    if chat is None or getattr(chat, "type", None) != "private":
        return False  # only the private bot chat — never gate group /start

    args = context.args or []
    token = args[0] if args else ""
    source = source_for_payload(token)

    if context.user_data is not None:
        # Stash where the persistence step (VOL-205) reads it.
        from .membership import ENTRY_SOURCE_KEY

        context.user_data[ENTRY_SOURCE_KEY] = source
        context.user_data[DM_ONBOARDING_FLAG] = True

    log_event(
        "dm_onboarding_start",
        update,
        entry_source=source,
        payload=(token.strip().lower() or None),
        outcome="started",
    )

    try:
        await reply_in_thread(update, GREETING, context=context)
    except Exception as exc:  # noqa: BLE001 - greeting must never block the flow
        log_event(
            "dm_onboarding_greet_failed",
            update,
            level=40,
            error_type=type(exc).__name__,
            outcome="greet_error",
        )

    # Begin the existing qualification flow IN THE DM. It hands off to the
    # PDPA/optional-capture flow, which finishes by calling grant_access().
    from .qualification import start_qualification

    await start_qualification(update, context, update.effective_user)
    return True


async def grant_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mint a single-use invite link and DM it — called on DM-onboarding completion.

    The user has answered every question privately, so we now let them in. A
    one-time link (``member_limit=1``, no join request) means they join instantly
    and already vetted. Never raises into the caller; on failure we log and ask
    the user to ping an admin.
    """

    config = get_config(context)
    user = update.effective_user
    user_id = getattr(user, "id", None)
    if user_id is None:
        return

    try:
        result = await context.bot.create_chat_invite_link(
            chat_id=config.group_id,
            member_limit=1,
            name=f"onboarded:{user_id}",
        )
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "You're all set 🧡 Tap to join the community:\n"
                f"{result.invite_link}\n\n"
                "This link is just for you and works once. See you inside! 🚗"
            ),
        )
        log_event(
            "dm_onboarding_granted",
            update,
            member_id=user_id,
            outcome="invite_sent",
        )
    except Exception as exc:  # noqa: BLE001 - completion must never crash
        log_event(
            "dm_onboarding_grant_failed",
            update,
            level=40,
            member_id=user_id,
            error_type=type(exc).__name__,
            outcome="grant_error",
        )
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="Thanks! An admin will send you the join link shortly 🧡",
            )
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":  # pragma: no cover - tiny self-test
    assert source_for_payload("showroom") == "showroom QR"
    assert source_for_payload("EVENT") == "event QR"
    assert source_for_payload("") == "salesperson"
    assert source_for_payload("nonsense") == "salesperson"
    print("dm_onboarding self-tests passed")
