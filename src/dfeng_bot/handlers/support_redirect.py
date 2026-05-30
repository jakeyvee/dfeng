"""Support-keyword detection and redirection (VOL-207).

When a member posts a support-flavoured message (charging/battery issue,
servicing, repair, warranty, etc.) in a *non-support* topic, the bot replies in
the same thread with a friendly nudge pointing them to the Support & Assistance
section. It does NOT delete or move the original message — it is purely additive
and non-punitive.

Where it runs
-------------
:func:`maybe_redirect` is invoked from ``messages.handle_message`` (the marked
support-redirection extension point), the same way welcome rides the existing
join handlers rather than adding a standalone handler. It is an observer: it
never raises ``ApplicationHandlerStop`` and never returns a "consumed" signal
that would stop later message subsystems (qualification, logging). It returns a
bool only to report whether it nudged, for symmetry with the other extension
seams.

No redirect loops
-----------------
If the triggering message is already inside the Support & Assistance topic
(``message_thread_id == config.topics.support``) we do nothing — otherwise the
nudge itself, and any follow-up the user posts there, could re-trigger forever.

Cooldown / dedupe
-----------------
To avoid spamming a chatty user with repeated nudges, we keep a per-process
in-memory ``{(user_id, thread_id): last_nudge_monotonic_ts}`` map and skip a
nudge if we nudged that same user in that same thread within
:data:`COOLDOWN_SECONDS`. This is per-process and NOT shared across instances —
acceptable for the v1 single-instance deployment (same trade-off as the welcome
dedupe). A multi-instance deployment would need a shared store.

Keywords
--------
:data:`SUPPORT_KEYWORDS` is the v1 default list. It is a plain module constant
and can be overridden by a deployment that imports and reassigns it (or by a
future ticket that makes it config-driven); the required seven keywords are the
v1 default. Matching is case-insensitive and word-boundary aware via a compiled
regex, so ``"issue"`` matches ``"Issue"``, ``"issue."`` and ``"issue!"`` but not
``"reissue"`` or ``"tissue"``. The phrases ``"charging issue"`` / ``"battery
issue"`` are kept in the list for documentation/explicitness even though a bare
``"issue"`` already covers them; :func:`find_support_keyword` returns the first
keyword that matches in list order, so there is no double-trigger — exactly one
keyword (and one nudge) per message.

Run as a module to execute the inline self-tests::

    python3 -m dfeng_bot.handlers.support_redirect
"""

from __future__ import annotations

import re
import time
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from ..logging_setup import log_event
from .. import metrics
from .base import get_config, reply_in_thread, thread_id_of

# Verbatim nudge copy (VOL-207). Stored as a constant; acceptance criteria assert
# this exact wording, so do not edit without updating the ticket.
SUPPORT_REDIRECT_MESSAGE = (
    "Hey! Let's get this sorted properly 🧡 Please continue this in our "
    "Support & Assistance section so our team can assist directly."
)

# v1 default keyword list. Single tokens ("servicing", "repair", "warranty",
# "problem", "issue") and phrases ("charging issue", "battery issue"). A bare
# "issue" already covers the two phrases; they are listed for explicitness.
# Overridable: a deployment may reassign this module constant, or a future ticket
# may source it from config.
SUPPORT_KEYWORDS: list[str] = [
    "charging issue",
    "battery issue",
    "servicing",
    "repair",
    "warranty",
    "problem",
    "issue",
]


def _compile(keywords: list[str]) -> list[tuple[str, "re.Pattern[str]"]]:
    """Compile each keyword into a case-insensitive, word-boundary regex.

    ``\\b`` boundaries keep single tokens from matching inside larger words
    (``"issue"`` must not fire on ``"tissue"``) while ``re.escape`` keeps the
    multiword phrases literal. Internal whitespace in a phrase is allowed to span
    one or more spaces.
    """

    compiled: list[tuple[str, re.Pattern[str]]] = []
    for kw in keywords:
        pattern = r"\b" + r"\s+".join(re.escape(part) for part in kw.split()) + r"\b"
        compiled.append((kw, re.compile(pattern, re.IGNORECASE)))
    return compiled


_COMPILED_KEYWORDS = _compile(SUPPORT_KEYWORDS)

# Cooldown window: skip a repeat nudge to the same (user, thread) within this
# many seconds. Per-process only (see module docstring).
COOLDOWN_SECONDS = 180

# (user_id, thread_id) -> last nudge timestamp (monotonic seconds).
_recent_nudges: dict[tuple[int, Optional[int]], float] = {}


def find_support_keyword(text: Optional[str]) -> Optional[str]:
    """Return the first matching support keyword in ``text``, else ``None``.

    Pure and unit-testable: case-insensitive, word-boundary aware. Returns the
    matched keyword *as listed in* :data:`SUPPORT_KEYWORDS` (first match wins in
    list order), so a message triggers at most one keyword.

    >>> find_support_keyword("My car has a battery Issue.")
    'battery issue'
    >>> find_support_keyword("It just has an Issue.")
    'issue'
    >>> find_support_keyword("Need SERVICING soon!")
    'servicing'
    >>> find_support_keyword("warranty?")
    'warranty'
    >>> find_support_keyword("This is a tissue, not an issue") is None
    False
    >>> find_support_keyword("Just a tissue here") is None
    True
    >>> find_support_keyword("Just here to say hi") is None
    True
    >>> find_support_keyword("") is None
    True
    >>> find_support_keyword(None) is None
    True
    """

    if not text:
        return None
    for keyword, pattern in _COMPILED_KEYWORDS:
        if pattern.search(text):
            return keyword
    return None


def _on_cooldown(user_id: int, thread_id: Optional[int], *, now: Optional[float] = None) -> bool:
    """Return True if (user_id, thread_id) was nudged within the cooldown window.

    Records ``now`` as the latest nudge time when returning False (i.e. when the
    caller should proceed to nudge). Opportunistically evicts expired entries so
    the map stays bounded.
    """

    now = time.monotonic() if now is None else now

    expired = [k for k, ts in _recent_nudges.items() if now - ts > COOLDOWN_SECONDS]
    for k in expired:
        _recent_nudges.pop(k, None)

    key = (user_id, thread_id)
    last = _recent_nudges.get(key)
    if last is not None and now - last <= COOLDOWN_SECONDS:
        return True

    _recent_nudges[key] = now
    return False


async def maybe_redirect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Nudge a member toward Support & Assistance if their message looks like one.

    Observer semantics: returns ``True`` when a nudge was sent, ``False``
    otherwise. The caller in ``messages.handle_message`` does NOT stop other
    subsystems on a truthy return (this is purely additive). Never raises into
    the caller; failures to send are logged.

    Behaviour:
        * gated by ``config.features.support_redirect`` (default ON);
        * no-op when the message is already in the Support topic (no loops);
        * no-op when no keyword matches;
        * cooldown-deduped per (user, thread).
    """

    message = update.effective_message
    if message is None:
        return False

    config = get_config(context)
    if not config.features.support_redirect:
        return False

    thread_id = thread_id_of(update)
    support_thread = config.topics.support

    # Never redirect from inside the Support topic — avoids loops.
    if support_thread and thread_id == support_thread:
        return False

    keyword = find_support_keyword(message.text)
    if keyword is None:
        return False

    user = update.effective_user
    user_id = user.id if user else 0

    if _on_cooldown(user_id, thread_id):
        log_event(
            "support_redirect_skipped",
            update,
            matched_keyword=keyword,
            thread_id=thread_id,
            outcome="cooldown",
        )
        return False

    try:
        await reply_in_thread(update, SUPPORT_REDIRECT_MESSAGE, context=context)
    except Exception as exc:  # noqa: BLE001 - a failed nudge must not break handling
        log_event(
            "support_redirect_failed",
            update,
            level=40,  # logging.ERROR
            matched_keyword=keyword,
            thread_id=thread_id,
            error_type=type(exc).__name__,
            outcome="send_error",
        )
        return False

    log_event(
        "support_redirect",
        update,
        matched_keyword=keyword,
        thread_id=thread_id,
        outcome="redirected",
    )
    metrics.bump(context, "support_redirect")
    return True


def _selftest() -> None:
    """Tiny self-test proving detection + the verbatim string. Run via __main__."""

    import doctest

    failures, _ = doctest.testmod(verbose=False)
    assert failures == 0, f"{failures} doctest failure(s)"

    # Each required keyword triggers (case / punctuation variations).
    samples = {
        "charging issue": "I have a charging issue today",
        "battery issue": "battery issue here",
        "servicing": "When is servicing due?",
        "repair": "needs a Repair, please",
        "warranty": "is this under WARRANTY?",
        "problem": "big problem!",
        "issue": "Issue.",
    }
    for expected_in, text in samples.items():
        match = find_support_keyword(text)
        assert match is not None, f"expected a match for {text!r}"
        # "issue" is the catch-all; phrases also legitimately resolve to "issue".
        assert match in (expected_in, "issue"), f"{text!r} -> {match!r}"

    # Non-support chatter does not trigger.
    for text in ("hello there", "great car!", "thanks team", "reissue the pass"):
        assert find_support_keyword(text) is None, f"unexpected match for {text!r}"

    # Verbatim copy guard.
    assert SUPPORT_REDIRECT_MESSAGE == (
        "Hey! Let's get this sorted properly 🧡 Please continue this in our "
        "Support & Assistance section so our team can assist directly."
    )

    print("support_redirect self-tests passed")


if __name__ == "__main__":  # pragma: no cover - manual/dev entry point
    _selftest()
