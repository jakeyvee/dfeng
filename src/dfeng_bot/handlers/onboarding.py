"""PDPA-gated optional profile capture + member persistence (VOL-205).

This module is the bridge between the qualification flow (VOL-204, which assigns
a tag) and the member workbook (``services/sheets.py``). It does three things:

    1. **Optional profile capture** — AFTER qualification resolves a tag, offer
       to collect two OPTIONAL, consent-gated personal fields: phone and vehicle
       plate. The EXACT PDPA notice (``policy.PDPA_CONSENT_NOTICE``) is shown
       BEFORE either field is ever requested. Phone and plate are each
       INDIVIDUALLY skippable; declining never blocks onboarding.

    2. **Pure record building** — :func:`build_member_record` maps the captured
       values onto the canonical schema columns (``schema.MEMBER_COLUMNS`` order),
       so persistence never hardcodes column names. Fully unit-testable.

    3. **Idempotent persistence** — :func:`persist_member` is the SINGLE write
       seam: ``ensure_header`` -> ``find_row_by_telegram_id`` ->
       ``update_member_row`` (if present) ELSE ``append_member_row``. Keyed on
       Telegram ID so duplicate onboarding attempts UPDATE rather than duplicate.

Consent-timestamp rule (matches docs/pdpa-policy.md §4)
------------------------------------------------------
A consent timestamp is stored **only when at least one optional field (phone OR
plate) is actually provided** after the notice was shown. If the member consents
but then skips BOTH fields, we treat it as "no optional data provided" and store
NO consent timestamp (and no phone/plate). :func:`build_member_record` enforces
this: an empty phone AND empty plate force ``consent_ts`` blank regardless of what
is passed in, so the rule cannot be violated by a caller.

The VOL-206 seam
----------------
ALL Sheets writes funnel through :func:`persist_member`. VOL-206 (retry queue +
exponential backoff) can wrap/route this single function through a queue without
touching the capture flow. The gspread client is synchronous, so the async caller
(:func:`_finish_and_persist`) wraps the call in ``asyncio.to_thread`` per CLAUDE.md.

Callback-data namespaces
------------------------
This flow owns two prefixes so it never collides with qualification's ``qual:``:

    pdpa:consent:yes / pdpa:consent:no     -- the consent choice
    profile:phone:skip                     -- skip the phone step
    profile:plate:skip                     -- skip the plate step

user_data contract (consumed from upstream tickets)
---------------------------------------------------
    qualification.TAG_KEY ("tag")          -- resolved tag (default "Prospect")
    membership.ENTRY_SOURCE_KEY            -- resolved entry source

Run the inline self-tests::

    python3 -m dfeng_bot.handlers.onboarding
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, User
from telegram.ext import ContextTypes

from .. import policy
from ..logging_setup import log_event
from ..services import schema
from .base import address, get_config, reply_in_thread

# --- callback-data namespaces (must not collide with qualification's "qual:") -
CONSENT_PREFIX = "pdpa:"
PROFILE_PREFIX = "profile:"

# --- internal flow state ----------------------------------------------------
# Per-(user, chat) capture state machine, mirroring qualification's approach
# (a lightweight user_data dict routed via callbacks / text rather than a
# ConversationHandler, since entry is via the qualification hand-off, not a
# /command). Distinct keys from qualification so the two flows never clash.
STATE_KEY = "profile_state"

STATE_AWAITING_CONSENT = "awaiting_consent"
STATE_AWAITING_PHONE = "awaiting_phone"
STATE_AWAITING_PLATE = "awaiting_plate"
STATE_DONE = "done"

# Temp holding keys for captured-but-not-yet-persisted optional values. These are
# PII (phone/plate) and are NEVER logged; only their presence is logged as bools.
PHONE_KEY = "profile_phone"
PLATE_KEY = "profile_plate"

# Light validation bounds — keep PERMISSIVE; store as given (trim only).
MAX_FIELD_LEN = 64

# --- copy -------------------------------------------------------------------
CONSENT_INTRO = (
    "One more optional step — and there are perks 🧡\n"
    "Share your contact number and car plate and we can:\n"
    "• invite you to events & exclusive owner perks\n"
    "• give you faster, more personal ownership support\n"
    "• recognise your car at meetups & servicing\n\n"
    "Totally optional — you're already in either way."
)
# Same benefits, but for the DM-handoff offer posted in the group.
PII_BENEFITS_DM = (
    "One more optional step — and there are perks 🧡\n"
    "Share your contact number and car plate (privately, just with me) and we can:\n"
    "• invite you to events & exclusive owner perks\n"
    "• give you faster, more personal ownership support\n"
    "• recognise your car at meetups & servicing\n\n"
    "Tap below to continue in a private chat — or No thanks, you're already in."
)
PHONE_PROMPT = (
    "Please type your contact number, or tap Skip.\n"
    "(I'll delete your message right after so it stays private 🧡)"
)
PLATE_PROMPT = (
    "Please type your vehicle plate, or tap Skip.\n"
    "(I'll remove your message right after for privacy 🧡)"
)
DECLINED_DONE = "No problem — you're all set. 🚗"
CAPTURE_DONE = "Thanks! You're all set. 🚗"


# --- keyboards --------------------------------------------------------------
# ``uid`` is embedded in callback data so only the user the prompt was posted for
# can act on these buttons (taps from other users are ignored in handle_callback).
def _consent_keyboard(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Share phone & plate", callback_data=f"{CONSENT_PREFIX}consent:yes:{uid}"
                ),
                InlineKeyboardButton("Skip", callback_data=f"{CONSENT_PREFIX}consent:no:{uid}"),
            ]
        ]
    )


def _phone_keyboard(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Skip", callback_data=f"{PROFILE_PREFIX}phone:skip:{uid}")]]
    )


def _plate_keyboard(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Skip", callback_data=f"{PROFILE_PREFIX}plate:skip:{uid}")]]
    )


# --- pure helpers (unit-testable) -------------------------------------------
def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string (seconds precision)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sanitize_optional(value: Optional[str]) -> str:
    """Trim + length-cap an optional free-text field; store as given otherwise.

    Validation is deliberately LIGHT (per ticket): strip surrounding whitespace
    and cap length so a pasted essay can't bloat a cell. Never raises; an empty /
    whitespace-only value normalises to "" (treated as "not provided").

    >>> sanitize_optional("  +65 9123 4567 ")
    '+65 9123 4567'
    >>> sanitize_optional("   ")
    ''
    >>> sanitize_optional(None)
    ''
    >>> sanitize_optional("X" * 100) == "X" * 64
    True
    """

    if not value:
        return ""
    return value.strip()[:MAX_FIELD_LEN]


def build_member_record(
    telegram_id: int,
    username: Optional[str],
    tag: str,
    phone: Optional[str],
    plate: Optional[str],
    consent_ts: Optional[str],
    entry_source: str,
    joined_ts: str,
) -> dict[str, str]:
    """Build a member record dict keyed by canonical ``schema`` column names.

    Returns a dict whose keys are EXACTLY the bot-owned schema columns (admin
    columns are intentionally absent — the bot never writes them). The Sheets
    client positions these onto the row using ``schema.MEMBER_COLUMNS`` order.

    Consent-timestamp rule (docs/pdpa-policy.md §4): the consent timestamp is
    kept ONLY when at least one optional field (phone or plate) is actually
    provided. If BOTH are empty, ``Consent timestamp`` is forced blank here even
    if a ``consent_ts`` was passed — so "consented then skipped everything" can
    never leak a timestamp with no optional data behind it.

    Phone/plate are sanitised (trim + length cap) but otherwise stored verbatim.

    >>> r = build_member_record(
    ...     42, "alice", "BOX Owner", "  91234567 ", "SGX1234A",
    ...     "2026-05-31T00:00:00+00:00", "showroom QR", "2026-05-30T00:00:00+00:00",
    ... )
    >>> [r[c] for c in schema.BOT_COLUMNS]
    ['42', 'alice', 'BOX Owner', '91234567', 'SGX1234A', '2026-05-31T00:00:00+00:00', 'showroom QR', '2026-05-30T00:00:00+00:00']
    >>> set(r) == set(schema.BOT_COLUMNS)
    True

    Declined optional data -> empty phone/plate AND empty consent timestamp,
    while required fields still persist:

    >>> d = build_member_record(
    ...     7, None, "Prospect", None, None,
    ...     "2026-05-31T00:00:00+00:00", "salesperson", "2026-05-30T00:00:00+00:00",
    ... )
    >>> d["Optional phone"], d["Optional plate"], d["Consent timestamp"]
    ('', '', '')
    >>> d["Telegram ID"], d["Tag"], d["Entry source"], d["Joined timestamp"]
    ('7', 'Prospect', 'salesperson', '2026-05-30T00:00:00+00:00')
    """

    phone_s = sanitize_optional(phone)
    plate_s = sanitize_optional(plate)

    # Enforce the consent-timestamp rule at the data layer: no optional data ->
    # no consent timestamp, regardless of what the caller passed.
    if not phone_s and not plate_s:
        consent_value = ""
    else:
        consent_value = consent_ts or ""

    return {
        "Telegram ID": str(telegram_id),
        "Telegram username": username or "",
        "Tag": tag,
        "Optional phone": phone_s,
        "Optional plate": plate_s,
        "Consent timestamp": consent_value,
        "Entry source": entry_source,
        "Joined timestamp": joined_ts,
    }


# --- persistence seam (the SINGLE write path VOL-206 will wrap) --------------
def persist_member(service: Any, record: Mapping[str, str]) -> str:
    """Idempotently upsert *record* into the member workbook. Returns the action.

    THE single, synchronous write seam — VOL-206 (retry queue + exponential
    backoff) can wrap/route this one function through a queue without touching the
    capture flow. Steps:

        1. ``ensure_header``                     (idempotent header reconcile)
        2. ``find_row_by_telegram_id(tid)``      (key = schema.KEY_COLUMN)
        3. present -> ``update_member_row``      (bot-owned cells only)
           absent  -> ``append_member_row``

    Because the lookup keys on Telegram ID, a duplicate onboarding attempt for the
    same member UPDATES the existing row instead of appending a new one (idempotent
    upsert). With :class:`NullSheetsService` every call is a no-op, so the flow
    still completes when Sheets is unconfigured.

    Returns ``"appended"`` or ``"updated"`` (``"noop"`` is never returned — the
    Null service's methods are no-ops but we still report which branch ran). This
    is sync/blocking (gspread); async callers wrap it in ``asyncio.to_thread``.
    """

    tid = int(record[schema.KEY_COLUMN])
    service.ensure_header()
    existing_row = service.find_row_by_telegram_id(tid)
    if existing_row is not None:
        service.update_member_row(tid, record)
        return "updated"
    service.append_member_row(record)
    return "appended"


# --- write-queue accessor (VOL-206) -----------------------------------------
def _get_write_queue(context: ContextTypes.DEFAULT_TYPE) -> Any:
    """Return the shared write queue from ``bot_data``, or None if unavailable.

    The queue is started in ``app.py`` post_init and stored under
    ``write_queue.WRITE_QUEUE_KEY``. Returns None when the feature is disabled or
    the application has no bot_data (e.g. unit tests), so callers can fall back to
    the direct write path. Never raises.
    """

    try:
        from ..services.write_queue import WRITE_QUEUE_KEY

        app = getattr(context, "application", None)
        bot_data = getattr(app, "bot_data", None) if app is not None else None
        if not bot_data:
            return None
        return bot_data.get(WRITE_QUEUE_KEY)
    except Exception:  # noqa: BLE001 - never block persistence on queue lookup
        return None


# --- internal state helpers --------------------------------------------------
def _set_state(context: ContextTypes.DEFAULT_TYPE, state: Optional[str]) -> None:
    if context.user_data is None:
        return
    if state is None:
        context.user_data.pop(STATE_KEY, None)
    else:
        context.user_data[STATE_KEY] = state


def _get_state(context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    if context.user_data is None:
        return None
    return context.user_data.get(STATE_KEY)


def _resolve_joined_ts(context: ContextTypes.DEFAULT_TYPE, telegram_id: int) -> str:
    """Resolve the member's join timestamp (ISO-8601 UTC).

    Prefers the join time recorded by VOL-209 (``link_restrictions`` TrustStore,
    stamped in ``membership.on_new_member``); falls back to "now" when unknown
    (e.g. a manual ``/profile`` from an established member). Imported locally to
    avoid any import-order coupling.
    """

    try:
        from .link_restrictions import get_store

        state = get_store().get(telegram_id)
        joined_at = getattr(state, "joined_at", None) if state is not None else None
        if joined_at is not None:
            return (
                datetime.fromtimestamp(float(joined_at), tz=timezone.utc)
                .replace(microsecond=0)
                .isoformat()
            )
    except Exception:  # noqa: BLE001 - never block persistence on a timestamp lookup
        pass
    return utc_now_iso()


# --- entry point (called from qualification completion) ----------------------
async def start_profile_capture(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Begin optional profile capture after qualification assigned a tag.

    Hand-off seam mirroring welcome -> qualification: qualification calls this
    once it has stashed the tag in ``user_data[qualification.TAG_KEY]``.

    Gated by ``config.features.optional_capture`` (default ON). When the feature
    is OFF we SKIP the PDPA notice / optional capture entirely and persist the
    required fields straight away (so members are still recorded). Never raises
    into the caller — a failed prompt must not block onboarding; we fall back to
    persisting required fields only.
    """

    config = get_config(context)

    # Record the member NOW with the required fields (tag + entry source), so a
    # classified member is never lost — even if they ignore the optional step or
    # bail out of the private DM. persist_member is an idempotent upsert keyed on
    # Telegram ID, so a later phone/plate capture just UPDATES the same row.
    await _finish_and_persist(update, context, announce=False)

    if not config.features.optional_capture:
        return

    user = update.effective_user
    uid = getattr(user, "id", 0)

    # DM mode: collect phone/plate PRIVATELY in the bot's 1:1 chat (never typed in
    # a public topic). We post a benefit-led offer here with a deep-link button;
    # the actual PDPA notice + capture happen in the DM (start_dm_pii_capture).
    if config.features.dm_pii_capture and config.bot_username:
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📲 Share privately with the bot",
                        url=f"https://t.me/{config.bot_username}?start=profile",
                    )
                ],
                # uid-locked so only this member can decline (others ignored).
                [InlineKeyboardButton("No thanks", callback_data=f"{PROFILE_PREFIX}decline:{uid}")],
            ]
        )
        try:
            await reply_in_thread(
                update, f"{address(user)} {PII_BENEFITS_DM}", context=context, reply_markup=keyboard
            )
            log_event("profile_offer_dm", update, outcome="offered")
        except Exception as exc:  # noqa: BLE001 - never block onboarding on a prompt
            log_event(
                "profile_capture_failed",
                update,
                level=40,
                error_type=type(exc).__name__,
                outcome="prompt_error",
            )
        return

    # In-group mode (default): benefit-led intro + the EXACT locked PDPA notice
    # BEFORE asking for any optional data. policy.PDPA_CONSENT_NOTICE is the single
    # source of truth — never retyped here.
    try:
        _set_state(context, STATE_AWAITING_CONSENT)
        await reply_in_thread(update, f"{address(user)} {CONSENT_INTRO}", context=context)
        await reply_in_thread(
            update,
            policy.PDPA_CONSENT_NOTICE,
            context=context,
            reply_markup=_consent_keyboard(uid),
        )
        log_event("profile_capture_started", update, outcome="asked_consent")
    except Exception as exc:  # noqa: BLE001 - never block onboarding on a prompt
        log_event(
            "profile_capture_failed",
            update,
            level=40,
            error_type=type(exc).__name__,
            outcome="prompt_error",
        )


async def start_dm_pii_capture(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Begin phone/plate capture in the bot's PRIVATE chat (DM PII handoff).

    Triggered by ``/start profile`` (the deep-link button in the group offer).
    Shows the locked PDPA notice, then asks for phone (skippable) -> plate
    (skippable) -> persists. The member's tag + entry source are already in
    ``user_data`` (per-user, shared across chats) from the in-group qualification,
    so the existing capture/persist path completes the same row.
    """

    config = get_config(context)
    if not (config.features.optional_capture and config.features.dm_pii_capture):
        await reply_in_thread(update, "Nothing to do here — you're all set 🧡", context=context)
        return

    try:
        await reply_in_thread(update, policy.PDPA_CONSENT_NOTICE, context=context)
        _set_state(context, STATE_AWAITING_PHONE)
        await reply_in_thread(
            update,
            PHONE_PROMPT,
            context=context,
            reply_markup=_phone_keyboard(getattr(update.effective_user, "id", 0)),
        )
        log_event("profile_capture_started", update, outcome="dm_asked_phone")
    except Exception as exc:  # noqa: BLE001 - never block on a prompt
        log_event(
            "profile_capture_failed",
            update,
            level=40,
            error_type=type(exc).__name__,
            outcome="prompt_error",
        )


async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manual ``/profile`` command — (re)open optional profile capture.

    Lets a member add/update their optional phone/plate at any time. Respects the
    feature flag; clears any stale capture state first.
    """

    config = get_config(context)
    if not config.features.optional_capture:
        await reply_in_thread(
            update, "Optional profile capture is currently disabled.", context=context
        )
        return

    if context.user_data is not None:
        context.user_data.pop(PHONE_KEY, None)
        context.user_data.pop(PLATE_KEY, None)
    _set_state(context, None)
    await start_profile_capture(update, context)
    log_event("profile_capture_started", update, outcome="manual")


# --- callback routing (called from messages.handle_callback_query) -----------
def owns_callback(data: Optional[str]) -> bool:
    """True if ``data`` belongs to this flow (``pdpa:`` / ``profile:``)."""
    return bool(data) and (
        data.startswith(CONSENT_PREFIX) or data.startswith(PROFILE_PREFIX)
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle a ``pdpa:`` / ``profile:`` callback. Returns True if consumed.

    The shared ``messages.handle_callback_query`` already answered the callback;
    here we only act on the routed data.
    """

    query = update.callback_query
    if query is None or not owns_callback(query.data):
        return False

    data = query.data

    # Buttons carry a trailing ":<uid>" so only the user the prompt was posted for
    # may act on them. If someone else taps, silently ignore (spinner already
    # dismissed). ``core`` is the data without that uid for the value compares.
    tapper = query.from_user
    core = data
    tail = data.rsplit(":", 1)
    if len(tail) == 2 and tail[1].isdigit():
        core = tail[0]
        if tapper is None or str(tapper.id) != tail[1]:
            log_event(
                "profile_callback_ignored",
                update,
                tapper_id=getattr(tapper, "id", None),
                target=tail[1],
                outcome="not_target",
            )
            return True
    uid = getattr(tapper, "id", 0)

    # pdpa:consent:yes / pdpa:consent:no
    if core.startswith(CONSENT_PREFIX):
        value = core[len(CONSENT_PREFIX):]
        if value == "consent:yes":
            _set_state(context, STATE_AWAITING_PHONE)
            await reply_in_thread(
                update, PHONE_PROMPT, context=context, reply_markup=_phone_keyboard(uid)
            )
            log_event("profile_consent", update, consent=True, outcome="asked_phone")
        else:  # consent:no / anything else -> decline, persist required only
            log_event("profile_consent", update, consent=False, outcome="declined")
            await _finish_and_persist(update, context, announce=True)
        return True

    # profile:decline (DM offer) / profile:phone:skip / profile:plate:skip
    if core.startswith(PROFILE_PREFIX):
        value = core[len(PROFILE_PREFIX):]
        if value == "decline":
            # DM offer declined — required fields were already persisted at the
            # start of capture, so just acknowledge.
            log_event("profile_offer_declined", update, outcome="declined")
            await reply_in_thread(update, DECLINED_DONE, context=context)
        elif value == "phone:skip":
            await _advance_to_plate(update, context)
        elif value == "plate:skip":
            await _finish_and_persist(update, context, announce=True)
        else:  # unknown profile subcommand — consume safely
            await _finish_and_persist(update, context, announce=True)
        return True

    return False


# --- text fallback (called from messages.handle_message) ---------------------
async def _delete_typed_pii(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Best-effort remove the user's just-typed phone/plate message from the topic.

    Capture happens in a public topic, so the value the user types is briefly
    visible to everyone. Deleting it immediately keeps PII out of the public
    timeline (Issue 2). Requires the bot's *Delete Messages* admin right; never
    raises into the flow, and the value itself is never logged (PII).
    """

    message = update.effective_message
    if message is None:
        return
    try:
        await message.delete()
    except Exception as exc:  # noqa: BLE001 - privacy cleanup must never block
        log_event(
            "profile_pii_delete_failed",
            update,
            level=30,
            error_type=type(exc).__name__,
            outcome="delete_error",
        )


async def advance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Advance an in-progress capture using a free-text answer. Returns True if consumed.

    Only acts when the user is mid-capture AND awaiting a typed field (phone /
    plate). Anyone not in those states is ignored (returns False) so normal chat
    is untouched. The PDPA notice + buttons drive the consent step, so a stray
    text message while awaiting consent is NOT consumed here.
    """

    state = _get_state(context)
    if state not in {STATE_AWAITING_PHONE, STATE_AWAITING_PLATE}:
        return False

    message = update.effective_message
    text = message.text if message is not None else None
    value = sanitize_optional(text)

    # Privacy (Issue 2): in a PUBLIC topic, the user's typed phone/plate is visible
    # to everyone — delete it right after reading. In a private DM there's nothing
    # to hide (and deleting the user's own DM message is odd), so skip it there.
    chat = update.effective_chat
    in_private = getattr(chat, "type", None) == "private"
    if not in_private and message is not None and (message.text or "").strip():
        await _delete_typed_pii(update, context)

    if state == STATE_AWAITING_PHONE:
        if value and context.user_data is not None:
            context.user_data[PHONE_KEY] = value
        # Even an empty/garbage message advances (treated as no phone given).
        log_event(
            "profile_field_captured",
            update,
            field="phone",
            phone_provided=bool(value),
            outcome="captured",
        )
        await _advance_to_plate(update, context)
        return True

    # STATE_AWAITING_PLATE
    if value and context.user_data is not None:
        context.user_data[PLATE_KEY] = value
    log_event(
        "profile_field_captured",
        update,
        field="plate",
        plate_provided=bool(value),
        outcome="captured",
    )
    await _finish_and_persist(update, context, announce=True)
    return True


async def _advance_to_plate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _set_state(context, STATE_AWAITING_PLATE)
    await reply_in_thread(
        update,
        PLATE_PROMPT,
        context=context,
        reply_markup=_plate_keyboard(getattr(update.effective_user, "id", 0)),
    )


# --- finish + persist --------------------------------------------------------
async def _finish_and_persist(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, announce: bool
) -> None:
    """Build the member record and write it idempotently, then confirm.

    Reads the tag (qualification.TAG_KEY, defaulted via ``resolve_tag``) and the
    entry source (membership.ENTRY_SOURCE_KEY) from ``user_data``. The consent
    timestamp is set ONLY when at least one optional field was provided — and
    :func:`build_member_record` enforces that invariant regardless. The gspread
    write is synchronous, so it runs in a worker thread per CLAUDE.md. Persistence
    failures NEVER block the flow; they are logged and the member is still
    confirmed.
    """

    _set_state(context, STATE_DONE)
    config = get_config(context)

    user: Optional[User] = update.effective_user
    telegram_id = getattr(user, "id", None)
    username = getattr(user, "username", None)

    # Local import keeps the onboarding <-> qualification/membership deps
    # one-directional (qualification imports onboarding, not vice versa at module
    # load time) and avoids any circular-import risk.
    from . import membership, qualification

    ud = context.user_data or {}
    tag = qualification.resolve_tag(ud.get(qualification.TAG_KEY))
    entry_source = ud.get(membership.ENTRY_SOURCE_KEY) or "salesperson"
    phone = ud.get(PHONE_KEY)
    plate = ud.get(PLATE_KEY)

    has_optional = bool(sanitize_optional(phone) or sanitize_optional(plate))
    consent_ts = utc_now_iso() if has_optional else ""

    if announce:
        try:
            await reply_in_thread(
                update,
                CAPTURE_DONE if has_optional else DECLINED_DONE,
                context=context,
            )
        except Exception as exc:  # noqa: BLE001 - confirmation must never block
            log_event(
                "profile_reply_failed",
                update,
                level=40,
                error_type=type(exc).__name__,
                outcome="send_error",
            )

    if telegram_id is None:
        log_event("member_persist_skipped", update, outcome="no_user")
        return

    joined_ts = _resolve_joined_ts(context, telegram_id)
    record = build_member_record(
        telegram_id=telegram_id,
        username=username,
        tag=tag,
        phone=phone,
        plate=plate,
        consent_ts=consent_ts,
        entry_source=entry_source,
        joined_ts=joined_ts,
    )

    # Clear PII from user_data now that it is captured into the record — keep the
    # holding store small and avoid lingering personal data in process memory.
    if context.user_data is not None:
        context.user_data.pop(PHONE_KEY, None)
        context.user_data.pop(PLATE_KEY, None)

    # VOL-206: route the write through the resilient async queue when one is wired
    # up (started in app.py post_init). enqueue() returns IMMEDIATELY — the
    # background worker persists with retries/backoff and dead-letters on
    # exhaustion — so a Sheets outage never blocks this onboarding flow. When the
    # queue is absent/disabled, fall back to VOL-205's direct write path.
    queue = _get_write_queue(context)
    if queue is not None:
        queue.enqueue(record)
        log_event(
            "member_enqueued",
            update,
            member_id=telegram_id,
            member_username=username,
            tag=tag,
            entry_source=entry_source,
            # PII-safe: presence only, never the values (schema.PII_COLUMNS).
            phone_provided=bool(record["Optional phone"]),
            plate_provided=bool(record["Optional plate"]),
            consent_recorded=bool(record["Consent timestamp"]),
            outcome="queued",
        )
        return

    # Direct path (VOL-205 fallback): build the Sheets service from config
    # (NullSheetsService when unconfigured) and write in a worker thread.
    from ..services.sheets import build_sheets_service

    service = build_sheets_service(config)

    try:
        action = await asyncio.to_thread(persist_member, service, record)
        log_event(
            "member_persisted",
            update,
            member_id=telegram_id,
            member_username=username,
            tag=tag,
            entry_source=entry_source,
            # PII-safe: presence only, never the values (schema.PII_COLUMNS).
            phone_provided=bool(record["Optional phone"]),
            plate_provided=bool(record["Optional plate"]),
            consent_recorded=bool(record["Consent timestamp"]),
            action=action,
            outcome="persisted",
        )
    except Exception as exc:  # noqa: BLE001 - persistence must not block onboarding
        log_event(
            "member_persist_failed",
            update,
            level=40,
            member_id=telegram_id,
            tag=tag,
            entry_source=entry_source,
            phone_provided=bool(record["Optional phone"]),
            plate_provided=bool(record["Optional plate"]),
            error_type=type(exc).__name__,
            outcome="write_error",
        )


# --- inline self-tests -------------------------------------------------------
def _selftest() -> None:
    """Inline self-tests for the pure parts. Run via __main__."""

    import doctest

    failures, _ = doctest.testmod(verbose=False)
    assert failures == 0, f"{failures} doctest failure(s)"

    # The consent string used here is BYTE-FOR-BYTE the locked policy constant.
    assert CONSENT_PREFIX == "pdpa:"
    assert (
        policy.PDPA_CONSENT_NOTICE
        == "By providing your information, you consent to Dongfeng Singapore storing "
        "and using the information solely for community management, support and "
        "engagement purposes in accordance with applicable PDPA requirements."
    )

    # build_member_record maps to the correct schema columns / order.
    rec = build_member_record(
        42,
        "alice",
        "BOX Owner",
        "91234567",
        "SGX1234A",
        "2026-05-31T00:00:00+00:00",
        "showroom QR",
        "2026-05-30T00:00:00+00:00",
    )
    assert set(rec) == set(schema.BOT_COLUMNS), rec
    ordered = [rec[c] for c in schema.BOT_COLUMNS]
    assert ordered == [
        "42",
        "alice",
        "BOX Owner",
        "91234567",
        "SGX1234A",
        "2026-05-31T00:00:00+00:00",
        "showroom QR",
        "2026-05-30T00:00:00+00:00",
    ], ordered

    # Declined optional -> required fields persist; phone/plate/consent blank.
    declined = build_member_record(
        7,
        None,
        "Prospect",
        None,
        None,
        "2026-05-31T00:00:00+00:00",  # passed, but must be dropped (no optional data)
        "salesperson",
        "2026-05-30T00:00:00+00:00",
    )
    assert declined["Optional phone"] == ""
    assert declined["Optional plate"] == ""
    assert declined["Consent timestamp"] == ""  # rule: no optional data -> no consent ts
    assert declined["Telegram ID"] == "7"
    assert declined["Tag"] == "Prospect"
    assert declined["Entry source"] == "salesperson"
    assert declined["Joined timestamp"] == "2026-05-30T00:00:00+00:00"

    # Consent ts kept when ANY optional field is provided.
    phone_only = build_member_record(
        9, "bob", "Prospect", "91234567", None,
        "2026-05-31T00:00:00+00:00", "salesperson", "2026-05-30T00:00:00+00:00",
    )
    assert phone_only["Consent timestamp"] == "2026-05-31T00:00:00+00:00"
    assert phone_only["Optional plate"] == ""

    # Idempotency: persist_member finds-then-updates vs appends through one seam.
    class _FakeService:
        def __init__(self) -> None:
            self.rows: dict[int, dict] = {}
            self.header_calls = 0

        def ensure_header(self) -> None:
            self.header_calls += 1

        def find_row_by_telegram_id(self, tid: int):
            return tid if tid in self.rows else None

        def append_member_row(self, record):
            tid = int(record[schema.KEY_COLUMN])
            assert tid not in self.rows, "append must not duplicate an existing row"
            self.rows[tid] = dict(record)

        def update_member_row(self, tid, record):
            self.rows[tid] = dict(record)

    svc = _FakeService()
    r1 = build_member_record(
        42, "alice", "Prospect", None, None, "", "salesperson", "2026-05-30T00:00:00+00:00"
    )
    assert persist_member(svc, r1) == "appended"
    assert len(svc.rows) == 1
    # Duplicate onboarding for the SAME id -> update, not a new row.
    r2 = build_member_record(
        42, "alice", "BOX Owner", "91234567", None,
        "2026-05-31T00:00:00+00:00", "salesperson", "2026-05-30T00:00:00+00:00",
    )
    assert persist_member(svc, r2) == "updated"
    assert len(svc.rows) == 1  # still one row -> idempotent
    assert svc.rows[42]["Tag"] == "BOX Owner"
    assert svc.header_calls == 2  # ensure_header called each write (idempotent)

    # NullSheetsService: persistence is a no-op that still completes.
    from ..services.sheets import NullSheetsService

    assert persist_member(NullSheetsService(), r1) == "appended"

    # Namespaces don't collide with qualification's "qual:".
    assert owns_callback("pdpa:consent:yes")
    assert owns_callback("profile:phone:skip")
    assert not owns_callback("qual:role:owner")
    assert not owns_callback(None)

    print("onboarding self-tests passed")


if __name__ == "__main__":  # pragma: no cover - manual/dev entry point
    _selftest()
