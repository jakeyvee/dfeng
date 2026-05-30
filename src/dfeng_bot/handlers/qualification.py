"""Owner/Prospect qualification flow + member tagging (VOL-204).

After the welcome (VOL-203 hands off via :func:`start_qualification`) we ask the
member a short, NON-BLOCKING question to segment them:

    1. "Owner or Prospect?"                         (inline buttons + text fallback)
    2. if Prospect  -> tag "Prospect"
    3. if Owner     -> "Which model? (BOX / 007 / VIGO)"  (inline buttons + text)
    4. -> tag "BOX Owner" / "007 Owner" / "VIGO Owner"

Anything that is NOT a clean answer (skip, refuse, unrecognised after one retry,
or simply never completing) resolves to the **"Prospect" default**. Qualification
NEVER blocks entry or posting — it is purely additive segmentation data.

Tag = bot-owned profile data
-----------------------------
Telegram has no CRM-style member labels, so we treat the resolved tag as
bot-owned profile data for later persistence. The resolved tag is stashed in
``context.user_data[TAG_KEY]`` (and returned where practical) so the persistence
ticket (VOL-205) can write it to the workbook's "Tag" column alongside
``entry_source`` (see ``membership.ENTRY_SOURCE_KEY``) and the telegram id /
username. Tags are the four canonical strings from ``services.schema.TAGS`` —
imported, never hardcoded divergently.

State machine
-------------
A lightweight per-user state dict in ``context.user_data`` (PTB keys user_data
per (user, chat)) drives the flow, routed by inline-button ``callback_data``.
This integrates with the existing ``messages.handle_callback_query`` seam rather
than introducing a ConversationHandler, which fits the wiring better given the
flow is initiated by the welcome hand-off (not a ``/command``) and answers arrive
as callback queries.

    context.user_data[STATE_KEY] in:
        STATE_AWAITING_ROLE   -> waiting for Owner/Prospect
        STATE_AWAITING_MODEL  -> waiting for BOX/007/VIGO
        STATE_DONE            -> tagged; ignore further qual input

Each prompt also records a per-state retry count (RETRY_KEY) so an unrecognised
text answer re-shows the buttons ONCE, then defaults to Prospect.

Callback-data namespace
------------------------
All qualification buttons use the ``qual:`` prefix (:data:`CALLBACK_PREFIX`) so
``messages.handle_callback_query`` can hand qualification callbacks here and let
other/future callbacks pass through untouched. Forms:

    qual:role:owner / qual:role:prospect / qual:role:skip
    qual:model:BOX / qual:model:007 / qual:model:VIGO / qual:model:skip

Manual retry
------------
``/qualify`` (see :func:`cmd_qualify`, registered in ``commands.py``) lets a user
(re)start qualification at any time — satisfying "starts after welcome OR through
a documented manual retry command".

Timeout
-------
A true idle-timeout is best-effort/optional in v1. The guarantee is that any
NON-completion path (explicit Skip button, refusal, unrecognised-after-retry)
resolves to "Prospect". If the user simply walks away mid-flow, no tag is forced
eagerly, but the documented contract for VOL-205 is: an unresolved member is
persisted as "Prospect" (use :func:`resolve_tag` with the stashed value, which
maps a missing/in-progress tag to the Prospect default).

Run the inline self-tests::

    python3 -m dfeng_bot.handlers.qualification
"""

from __future__ import annotations

from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ..logging_setup import log_event
from .. import metrics
from ..services.schema import TAGS
from .base import get_config, reply_in_thread

# --- Canonical tags (imported, never hardcoded divergently) -----------------
# Pull the four canonical strings from the schema so this module and the
# workbook never drift. We bind named locals for readability; a startup-time
# assertion (below) guards against any future schema reorder/rename.
TAG_BOX = "BOX Owner"
TAG_007 = "007 Owner"
TAG_VIGO = "VIGO Owner"
TAG_PROSPECT = "Prospect"

# Fail loudly at import time if the canonical schema ever diverges from the
# strings this flow assigns. Keeps tags == schema.TAGS guaranteed.
assert set(TAGS) == {TAG_BOX, TAG_007, TAG_VIGO, TAG_PROSPECT}, (
    "schema.TAGS diverged from qualification tags"
)

# --- user_data keys (the contract with VOL-205 persistence) -----------------
# Resolved tag for downstream persistence. VOL-205 reads this (alongside
# membership.ENTRY_SOURCE_KEY and the telegram id/username) to write the
# workbook's "Tag" column. Documented & exported so persistence depends on a
# constant, not a magic string.
TAG_KEY = "tag"

# Internal flow state + per-state retry counter (not persisted by VOL-205).
STATE_KEY = "qualification_state"
RETRY_KEY = "qualification_retries"

# State values.
STATE_AWAITING_ROLE = "awaiting_role"
STATE_AWAITING_MODEL = "awaiting_model"
STATE_DONE = "done"

# --- callback-data namespace -------------------------------------------------
# All qualification buttons carry this prefix so the shared callback handler can
# route them here and leave other callbacks alone.
CALLBACK_PREFIX = "qual:"

# How many unrecognised TEXT answers to tolerate (re-show buttons) before
# defaulting to Prospect. 1 == one retry, then default.
MAX_TEXT_RETRIES = 1

# --- copy --------------------------------------------------------------------
ROLE_PROMPT = "One quick question — are you a Dongfeng owner, or a prospect?"
MODEL_PROMPT = "Nice! Which model do you drive? (BOX / 007 / VIGO)"
ROLE_RETRY_PROMPT = (
    "No worries — just tap a button below: are you an Owner or a Prospect?"
)
MODEL_RETRY_PROMPT = "Just tap your model below: BOX, 007 or VIGO."
PROSPECT_DONE = "Got it — you're all set. Welcome aboard! 🚗"
OWNER_DONE = "Awesome, thanks! You're all set. 🚗"


# --- pure mapping helpers (unit-testable) -----------------------------------
def answer_to_role(answer: Optional[str]) -> Optional[str]:
    """Map a free-text / callback role answer to ``"owner"`` / ``"prospect"``.

    Case-insensitive, tolerant of surrounding whitespace. Returns ``None`` for
    anything unrecognised so the caller can retry or default.

    >>> answer_to_role("Owner")
    'owner'
    >>> answer_to_role("  i'm an OWNER ")
    'owner'
    >>> answer_to_role("prospect")
    'prospect'
    >>> answer_to_role("just looking")
    'prospect'
    >>> answer_to_role("BOX") is None
    True
    >>> answer_to_role("") is None
    True
    >>> answer_to_role(None) is None
    True
    """

    if not answer:
        return None
    text = answer.strip().lower()
    if not text:
        return None
    if "owner" in text or text in {"o", "own"}:
        return "owner"
    if "prospect" in text or "looking" in text or text in {"p", "prospective"}:
        return "prospect"
    return None


def model_to_tag(answer: Optional[str]) -> Optional[str]:
    """Map a model answer (BOX/007/VIGO) to its canonical owner tag.

    Case-insensitive and whitespace-tolerant. Returns ``None`` for anything
    unrecognised so the caller can retry or default to Prospect.

    >>> model_to_tag("BOX")
    'BOX Owner'
    >>> model_to_tag(" box ")
    'BOX Owner'
    >>> model_to_tag("007")
    '007 Owner'
    >>> model_to_tag("vigo")
    'VIGO Owner'
    >>> model_to_tag("VIGO Owner")
    'VIGO Owner'
    >>> model_to_tag("tesla") is None
    True
    >>> model_to_tag(None) is None
    True
    """

    if not answer:
        return None
    text = answer.strip().lower()
    if not text:
        return None
    if "box" in text:
        return TAG_BOX
    if "007" in text:
        return TAG_007
    if "vigo" in text:
        return TAG_VIGO
    return None


def resolve_tag(tag: Optional[str]) -> str:
    """Resolve a (possibly missing/invalid) tag to a canonical tag.

    The single guarantee of the flow: anything that is not one of the three
    owner tags resolves to ``"Prospect"``. VOL-205 can call this on the stashed
    ``user_data[TAG_KEY]`` to persist a sane value even for members who never
    completed the flow.

    >>> resolve_tag("BOX Owner")
    'BOX Owner'
    >>> resolve_tag("007 Owner")
    '007 Owner'
    >>> resolve_tag("Prospect")
    'Prospect'
    >>> resolve_tag(None)
    'Prospect'
    >>> resolve_tag("garbage")
    'Prospect'
    """

    if tag in {TAG_BOX, TAG_007, TAG_VIGO}:
        return tag  # type: ignore[return-value]
    return TAG_PROSPECT


# --- keyboards ---------------------------------------------------------------
def _role_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Owner", callback_data=f"{CALLBACK_PREFIX}role:owner"),
                InlineKeyboardButton("Prospect", callback_data=f"{CALLBACK_PREFIX}role:prospect"),
            ],
            [InlineKeyboardButton("Skip", callback_data=f"{CALLBACK_PREFIX}role:skip")],
        ]
    )


def _model_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("BOX", callback_data=f"{CALLBACK_PREFIX}model:BOX"),
                InlineKeyboardButton("007", callback_data=f"{CALLBACK_PREFIX}model:007"),
                InlineKeyboardButton("VIGO", callback_data=f"{CALLBACK_PREFIX}model:VIGO"),
            ],
            [InlineKeyboardButton("Skip", callback_data=f"{CALLBACK_PREFIX}model:skip")],
        ]
    )


# --- internal helpers --------------------------------------------------------
def _set_state(context: ContextTypes.DEFAULT_TYPE, state: Optional[str]) -> None:
    if context.user_data is None:
        return
    if state is None:
        context.user_data.pop(STATE_KEY, None)
    else:
        context.user_data[STATE_KEY] = state
    # Any state change resets the per-state retry counter.
    context.user_data[RETRY_KEY] = 0


def _get_state(context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    if context.user_data is None:
        return None
    return context.user_data.get(STATE_KEY)


def _store_tag(context: ContextTypes.DEFAULT_TYPE, tag: str) -> None:
    """Stash the resolved tag for VOL-205 and mark the flow done."""
    if context.user_data is not None:
        context.user_data[TAG_KEY] = tag
        context.user_data[STATE_KEY] = STATE_DONE
        context.user_data.pop(RETRY_KEY, None)


async def _assign_prospect(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    path: str,
    announce: bool = True,
) -> str:
    """Assign the Prospect tag, log, optionally confirm. Returns the tag."""
    _store_tag(context, TAG_PROSPECT)
    if announce:
        try:
            await reply_in_thread(update, PROSPECT_DONE, context=context)
        except Exception as exc:  # noqa: BLE001 - confirmation must never block
            log_event(
                "qualification_reply_failed",
                update,
                level=40,
                error_type=type(exc).__name__,
                outcome="send_error",
            )
    log_event("qualification_complete", update, tag=TAG_PROSPECT, path=path, outcome="tagged")
    metrics.bump(context, "qualification_complete")
    await _handoff_to_onboarding(update, context)
    return TAG_PROSPECT


async def _assign_owner(
    update: Update, context: ContextTypes.DEFAULT_TYPE, tag: str, *, path: str
) -> str:
    """Assign a specific owner tag, log, confirm. Returns the tag."""
    _store_tag(context, tag)
    try:
        await reply_in_thread(update, OWNER_DONE, context=context)
    except Exception as exc:  # noqa: BLE001 - confirmation must never block
        log_event(
            "qualification_reply_failed",
            update,
            level=40,
            error_type=type(exc).__name__,
            outcome="send_error",
        )
    log_event("qualification_complete", update, tag=tag, path=path, outcome="tagged")
    metrics.bump(context, "qualification_complete")
    await _handoff_to_onboarding(update, context)
    return tag


async def _handoff_to_onboarding(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Hand off to PDPA-gated optional capture + persistence (VOL-205).

    Called at the clean end-of-flow point, AFTER the tag is stashed in
    ``user_data[TAG_KEY]``. Mirrors the welcome -> qualification hand-off:
    qualification depends on onboarding one-directionally (onboarding never
    imports qualification at module load), so the import is LOCAL to avoid any
    circular-import risk. Never raises into the flow — a failed hand-off must not
    undo a successful tagging.
    """

    try:
        from . import onboarding

        await onboarding.start_profile_capture(update, context)
    except Exception as exc:  # noqa: BLE001 - tagging already succeeded; don't unwind
        log_event(
            "onboarding_handoff_failed",
            update,
            level=40,
            error_type=type(exc).__name__,
            outcome="handoff_error",
        )


async def _ask_role(update: Update, context: ContextTypes.DEFAULT_TYPE, *, prompt: str) -> None:
    _set_state(context, STATE_AWAITING_ROLE)
    await reply_in_thread(update, prompt, context=context, reply_markup=_role_keyboard())


async def _ask_model(update: Update, context: ContextTypes.DEFAULT_TYPE, *, prompt: str) -> None:
    _set_state(context, STATE_AWAITING_MODEL)
    await reply_in_thread(update, prompt, context=context, reply_markup=_model_keyboard())


# --- entry points ------------------------------------------------------------
async def start_qualification(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    member,
) -> None:
    """Begin the qualification flow for ``member`` (welcome.py hand-off seam).

    Gated by ``config.features.qualification`` (default ON). Never raises into
    the caller — a failed prompt must not block entry; it just leaves the member
    untagged (VOL-205 defaults such members to Prospect via :func:`resolve_tag`).
    """

    config = get_config(context)
    if not config.features.qualification:
        log_event(
            "qualification_skipped",
            update,
            member_id=getattr(member, "id", None),
            member_username=getattr(member, "username", None),
            outcome="feature_disabled",
        )
        return

    try:
        await _ask_role(update, context, prompt=ROLE_PROMPT)
    except Exception as exc:  # noqa: BLE001 - never block entry on a failed prompt
        log_event(
            "qualification_failed",
            update,
            level=40,
            member_id=getattr(member, "id", None),
            error_type=type(exc).__name__,
            outcome="prompt_error",
        )
        return

    log_event(
        "qualification_started",
        update,
        member_id=getattr(member, "id", None),
        member_username=getattr(member, "username", None),
        outcome="asked_role",
    )
    metrics.bump(context, "qualification_started")


async def cmd_qualify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manual retry command ``/qualify`` — (re)start qualification for the user.

    Documented entry point satisfying "starts after welcome OR via a manual retry
    command". Respects the feature flag; clears any stale state first.
    """

    config = get_config(context)
    if not config.features.qualification:
        await reply_in_thread(
            update, "Qualification is currently disabled.", context=context
        )
        return

    _set_state(context, None)
    await _ask_role(update, context, prompt=ROLE_PROMPT)
    log_event("qualification_started", update, outcome="manual_retry")
    metrics.bump(context, "qualification_started")


# --- callback routing (called from messages.handle_callback_query) -----------
def owns_callback(data: Optional[str]) -> bool:
    """True if ``data`` is a qualification callback (``qual:`` namespace)."""
    return bool(data) and data.startswith(CALLBACK_PREFIX)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle a ``qual:`` inline-button callback. Returns True if consumed.

    The shared ``messages.handle_callback_query`` already answers the callback;
    here we only act on the routed data. Returns False for non-qual data so the
    caller can fall through to other behaviour.
    """

    query = update.callback_query
    if query is None or not owns_callback(query.data):
        return False

    # data forms: qual:role:owner / qual:role:prospect / qual:role:skip
    #             qual:model:BOX / qual:model:007 / qual:model:VIGO / qual:model:skip
    parts = query.data[len(CALLBACK_PREFIX):].split(":", 1)
    kind = parts[0]
    value = parts[1] if len(parts) > 1 else ""

    if kind == "role":
        if value == "owner":
            await _ask_model(update, context, prompt=MODEL_PROMPT)
            log_event("qualification_role", update, role="owner", outcome="asked_model")
        elif value == "prospect":
            await _assign_prospect(update, context, path="prospect")
        else:  # skip / anything else -> default Prospect
            await _assign_prospect(update, context, path="default_prospect")
        return True

    if kind == "model":
        tag = model_to_tag(value)
        if tag is not None:
            await _assign_owner(update, context, tag, path=f"owner->{value.lower()}")
        else:  # skip / unknown model -> default Prospect
            await _assign_prospect(update, context, path="default_prospect")
        return True

    # Unknown qual subcommand — consume it (it's ours) but default safely.
    await _assign_prospect(update, context, path="default_prospect")
    return True


# --- text fallback (called from messages.handle_message) ---------------------
def _bump_retry(context: ContextTypes.DEFAULT_TYPE) -> int:
    if context.user_data is None:
        return MAX_TEXT_RETRIES  # no store -> behave as exhausted (default now)
    count = int(context.user_data.get(RETRY_KEY, 0)) + 1
    context.user_data[RETRY_KEY] = count
    return count


async def advance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Advance an in-progress flow using a free-text answer. Returns True if consumed.

    Only acts when the user has an active qualification state. Recognised answers
    progress/complete the flow; an unrecognised answer re-shows the buttons ONCE
    (per state), then defaults to Prospect. Anyone not mid-flow is ignored
    (returns False) so normal chat is untouched.
    """

    state = _get_state(context)
    if state not in {STATE_AWAITING_ROLE, STATE_AWAITING_MODEL}:
        return False

    message = update.effective_message
    text = message.text if message is not None else None

    if state == STATE_AWAITING_ROLE:
        role = answer_to_role(text)
        if role == "owner":
            await _ask_model(update, context, prompt=MODEL_PROMPT)
            log_event("qualification_role", update, role="owner", outcome="asked_model")
            return True
        if role == "prospect":
            await _assign_prospect(update, context, path="prospect")
            return True
        # unrecognised
        if _bump_retry(context) > MAX_TEXT_RETRIES:
            await _assign_prospect(update, context, path="default_prospect")
        else:
            await reply_in_thread(
                update, ROLE_RETRY_PROMPT, context=context, reply_markup=_role_keyboard()
            )
            log_event("qualification_retry", update, state=state, outcome="reprompt_role")
        return True

    # STATE_AWAITING_MODEL
    tag = model_to_tag(text)
    if tag is not None:
        await _assign_owner(update, context, tag, path=f"owner->{tag.split()[0].lower()}")
        return True
    if _bump_retry(context) > MAX_TEXT_RETRIES:
        await _assign_prospect(update, context, path="default_prospect")
    else:
        await reply_in_thread(
            update, MODEL_RETRY_PROMPT, context=context, reply_markup=_model_keyboard()
        )
        log_event("qualification_retry", update, state=state, outcome="reprompt_model")
    return True


def _selftest() -> None:
    """Inline self-tests for the pure parts. Run via __main__."""

    import doctest

    failures, _ = doctest.testmod(verbose=False)
    assert failures == 0, f"{failures} doctest failure(s)"

    # Tags assigned by the flow are EXACTLY schema.TAGS.
    assert {TAG_BOX, TAG_007, TAG_VIGO, TAG_PROSPECT} == set(TAGS)
    assert model_to_tag("BOX") == "BOX Owner"
    assert model_to_tag("007") == "007 Owner"
    assert model_to_tag("VIGO") == "VIGO Owner"
    for tag in (model_to_tag("BOX"), model_to_tag("007"), model_to_tag("VIGO")):
        assert tag in TAGS

    # Unrecognised model -> None (caller defaults to Prospect).
    assert model_to_tag("Cybertruck") is None

    # Role mapping.
    assert answer_to_role("Owner") == "owner"
    assert answer_to_role("prospect") == "prospect"
    assert answer_to_role("???") is None

    # Default guarantee.
    assert resolve_tag(None) == "Prospect"
    assert resolve_tag("nonsense") == "Prospect"
    assert resolve_tag("VIGO Owner") == "VIGO Owner"

    # Callback ownership / namespace.
    assert owns_callback("qual:role:owner")
    assert not owns_callback("other:thing")
    assert not owns_callback(None)

    print("qualification self-tests passed")


if __name__ == "__main__":  # pragma: no cover - manual/dev entry point
    _selftest()
