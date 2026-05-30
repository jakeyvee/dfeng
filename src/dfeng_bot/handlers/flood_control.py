"""Per-user flood control across ALL topics (VOL-210).

The SECOND moderation handler in ``GROUP_PREFILTER`` (-1), registered AFTER
anti-spam (VOL-208). It tracks each user's message *rate* across the ENTIRE
supergroup — every forum topic counts toward the same per-user limit, NOT
per-topic — and, when a user floods, applies the configured escalating action
(warn / mute / delete / mute+delete) before consuming the update.

Design (two clean layers, mirroring antispam.py)
-----------------------------------------------
1. **Pure tracker** — :class:`FloodTracker` keeps a per-user deque of message
   timestamps and exposes :meth:`FloodTracker.record_and_check`. It is keyed by
   ``user_id`` ONLY (thread/topic is ignored for counting), takes an injected
   ``now``, performs no I/O, and is fully unit-testable / doctested. This is how
   "messages across multiple topics count toward the same per-user limit" is
   guaranteed: the tracker simply never sees the thread id.
2. **Telegram side-effects** — :func:`check`, the async prefilter handler, pulls
   the message, records it in the tracker, and on a :class:`FloodVerdict` performs
   the configured action (logging the thread where the threshold was crossed),
   then raises ``ApplicationHandlerStop`` *only when it actually actions*
   (mute/delete). A bare ``warn`` does not stop the chain, so anti-spam siblings
   and downstream handlers still run.

Cross-topic counting
--------------------
The tracker key is ``user_id``. A user sending one message each in six different
topics within the window is the same as six messages in one topic — both trip the
same per-user limit. The thread id is recorded only for *logging* (where the
flood was observed), via ``thread_id_of(update)``.

Default thresholds + rationale
-----------------------------
Trip when a user sends **more than 8 messages in 10 seconds** (``> max_messages``
within ``window_seconds``). Sustained > 0.8 msg/s is well above natural human
chat — even an excited member double/triple-posting stays clear — but firmly
catches copy-paste floods and spam bursts. A slow sender (e.g. one msg every few
seconds) never accumulates enough in the rolling window. Tune via
``config.rate_limits`` (env ``DFENG_RATE_LIMIT_MESSAGES`` / ``_WINDOW_SECONDS``).

Mute reversibility
-----------------
Mutes use ``restrict_chat_member`` with ``until_date = now + mute_seconds``, so
Telegram auto-lifts them when the window expires — time-bounded and reversible
with no manual unmute. Duration is configurable (``DFENG_RATE_LIMIT_MUTE_SECONDS``,
default 600s / 10 min).

State trade-off (v1)
-------------------
``FloodTracker`` is per-process and in-memory, bounded (outer user map +
per-user deque), and NOT shared across instances — the same single-instance
assumption as antispam's repetition memory and the welcome/support dedupe. A
multi-instance deployment would need a shared store (e.g. Redis).

Admin exemption
--------------
Admins/moderators (``is_admin``) are exempt by default; set
``DFENG_RATE_LIMIT_EXEMPT_ADMINS=0`` to apply flood control to everyone.

Run the inline self-tests::

    python3 -m dfeng_bot.handlers.flood_control
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from ..logging_setup import log_event
from .. import metrics
from .base import get_config, is_admin, thread_id_of

# --- action labels -----------------------------------------------------------

ACTION_WARN = "warn"
ACTION_MUTE = "mute"
ACTION_DELETE = "delete"
ACTION_MUTE_DELETE = "mute_delete"

VALID_ACTIONS = {ACTION_WARN, ACTION_MUTE, ACTION_DELETE, ACTION_MUTE_DELETE}

# Defaults (mirrored from config; > 8 msgs / 10s trips). See module docstring.
DEFAULT_MAX_MESSAGES = 8
DEFAULT_WINDOW_SECONDS = 10


@dataclass(frozen=True)
class FloodVerdict:
    """Result of a flood check: the user tripped the per-user rate limit."""

    count: int          # messages observed in the window (including current)
    window_seconds: int  # the window the count was measured over


class FloodTracker:
    """Pure, per-user message-rate tracker. No Telegram objects, no I/O.

    Keyed by ``user_id`` ONLY — thread/topic is intentionally ignored so messages
    across ALL topics count toward the same limit. Each user has a bounded deque
    of recent message timestamps; :meth:`record_and_check` appends ``now``, drops
    timestamps older than the window, and returns a :class:`FloodVerdict` when the
    count within the window EXCEEDS ``max_messages`` (i.e. ``> max_messages``).

    The outer user map is bounded to ``max_users`` (least-recently-active user is
    evicted on overflow) and each per-user deque to ``max_messages + 1`` — only
    the most recent few timestamps matter for the window.

    >>> t = FloodTracker(max_messages=3, window_seconds=10)
    >>> # Burst: the 4th message within the window trips ( > 3 ).
    >>> t.record_and_check(1, now=0) is None
    True
    >>> t.record_and_check(1, now=1) is None
    True
    >>> t.record_and_check(1, now=2) is None
    True
    >>> v = t.record_and_check(1, now=3)
    >>> v.count, v.window_seconds
    (4, 10)
    >>> # Cross-topic: thread id is never passed in, so different topics share the
    >>> # same per-user counter — this is what makes all-topics counting work.
    >>> t2 = FloodTracker(max_messages=3, window_seconds=10)
    >>> [t2.record_and_check(9, now=i) is None for i in range(3)]
    [True, True, True]
    >>> t2.record_and_check(9, now=3) is not None  # 4th msg, any topic, trips
    True
    >>> # Slow sender stays clear: 1 msg / 5s never fills the window.
    >>> t3 = FloodTracker(max_messages=3, window_seconds=10)
    >>> any(t3.record_and_check(2, now=i * 5) for i in range(6))
    False
    >>> # Window expiry resets: old timestamps drop out of the window.
    >>> t4 = FloodTracker(max_messages=3, window_seconds=10)
    >>> [t4.record_and_check(5, now=i) is None for i in range(3)]
    [True, True, True]
    >>> t4.record_and_check(5, now=100) is None  # window moved on, count back to 1
    True
    """

    __slots__ = ("max_messages", "window_seconds", "max_users", "_times", "_touch")

    def __init__(
        self,
        max_messages: int = DEFAULT_MAX_MESSAGES,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
        *,
        max_users: int = 5000,
    ) -> None:
        self.max_messages = max_messages
        self.window_seconds = window_seconds
        self.max_users = max_users
        # user_id -> deque of monotonic-ish timestamps, oldest first.
        self._times: dict[int, "deque[float]"] = {}
        # user_id -> last-seen ts, for LRU eviction of the outer map.
        self._touch: dict[int, float] = {}

    def record_and_check(self, user_id: int, now: Optional[float] = None) -> Optional[FloodVerdict]:
        """Record one message for ``user_id`` at ``now`` and check the rate.

        Returns a :class:`FloodVerdict` when the number of messages within the
        rolling ``window_seconds`` EXCEEDS ``max_messages`` (``count > max``),
        else ``None``. ``now`` defaults to ``time.monotonic()``; tests inject it.
        """

        now = time.monotonic() if now is None else now

        # Evict least-recently-active user if the outer map is oversized.
        if user_id not in self._times and len(self._times) >= self.max_users:
            oldest = min(self._touch, key=self._touch.get)
            self._times.pop(oldest, None)
            self._touch.pop(oldest, None)

        # Bound the per-user deque: never need more than max_messages + 1 stamps.
        times = self._times.setdefault(user_id, deque(maxlen=self.max_messages + 1))
        self._touch[user_id] = now
        times.append(now)

        # Drop stamps that fell out of the rolling window.
        cutoff = now - self.window_seconds
        while times and times[0] < cutoff:
            times.popleft()

        count = len(times)
        if count > self.max_messages:
            return FloodVerdict(count=count, window_seconds=self.window_seconds)
        return None

    def reset(self) -> None:
        """Clear all tracked state (used by tests / process reset)."""
        self._times.clear()
        self._touch.clear()


# --- module-level tracker (per-process, rebuilt when thresholds change) -------

_tracker: Optional[FloodTracker] = None


def _get_tracker(max_messages: int, window_seconds: int) -> FloodTracker:
    """Return the shared :class:`FloodTracker`, (re)building it if config changed."""
    global _tracker
    if (
        _tracker is None
        or _tracker.max_messages != max_messages
        or _tracker.window_seconds != window_seconds
    ):
        _tracker = FloodTracker(max_messages=max_messages, window_seconds=window_seconds)
    return _tracker


def reset_tracker() -> None:
    """Reset the module-level tracker (used by tests)."""
    global _tracker
    _tracker = None


# --- async prefilter handler -------------------------------------------------


async def check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prefilter handler: per-user flood control across all topics.

    Registered in ``GROUP_PREFILTER`` (-1), AFTER anti-spam. Behaviour:
        * gated by ``config.features.flood_control`` (default OFF until enabled);
        * admins exempt unless ``rate_limits.exempt_admins`` is False;
        * records the message in the pure :class:`FloodTracker` (keyed by user id
          only, so all topics share one counter);
        * on a :class:`FloodVerdict`: perform the configured action (warn / mute /
          delete / mute+delete), logging id, username, count/window, thread, and
          action via :func:`log_event`;
        * raises ``ApplicationHandlerStop`` ONLY when it actually actions by
          mute/delete — a bare ``warn`` lets the chain continue so siblings and
          downstream handlers still run (per the GROUP_PREFILTER seam rule).

    Never logs message bodies — only id, username, counts, thread, action.
    """

    message = update.effective_message
    if message is None:
        return

    config = get_config(context)
    if not config.features.flood_control:
        return

    limits = config.rate_limits

    # Admin exemption (default ON).
    if limits.exempt_admins and is_admin(update, context):
        return

    user = update.effective_user
    user_id = user.id if user else 0
    if not user_id:
        return

    tracker = _get_tracker(limits.max_messages, limits.window_seconds)
    verdict = tracker.record_and_check(user_id)
    if verdict is None:
        return  # below threshold — do NOT block other handlers.

    thread_id = thread_id_of(update)
    action = limits.action if limits.action in VALID_ACTIONS else ACTION_MUTE

    do_delete = action in {ACTION_DELETE, ACTION_MUTE_DELETE}
    do_mute = action in {ACTION_MUTE, ACTION_MUTE_DELETE}

    deleted = False
    if do_delete:
        deleted = await _try_delete(update, verdict, thread_id, action)

    muted = False
    if do_mute:
        muted = await _try_mute(update, context, limits, verdict, thread_id, action)

    if action == ACTION_WARN:
        await _warn(update, context, verdict, thread_id)
        # Warning is non-destructive: let the message and other handlers through.
        return

    # We actioned the update (mute and/or delete) — consume it so downstream
    # handlers (anti-spam already ran as a sibling, plus support-redirect /
    # qualification / logging) don't also act on this flooded message.
    log_event(
        "flood_control",
        update,
        count=verdict.count,
        window_seconds=verdict.window_seconds,
        max_messages=limits.max_messages,
        thread_id=thread_id,
        action=action,
        deleted=deleted,
        muted=muted,
        outcome="actioned",
    )
    metrics.bump(context, "spam_action")
    raise ApplicationHandlerStop


# --- side-effect helpers -----------------------------------------------------


async def _warn(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    verdict: FloodVerdict,
    thread_id: Optional[int],
) -> None:
    """Reply a non-destructive flood warning in-thread, and log it."""
    from .base import reply_in_thread  # local import keeps the seam tidy

    try:
        await reply_in_thread(
            update,
            "Please slow down — you're sending messages too quickly.",
            context=context,
        )
        outcome = "warned"
    except Exception as exc:  # noqa: BLE001 - a warning must never crash the bot
        outcome = "warn_failed"
        log_event(
            "flood_control",
            update,
            level=30,  # logging.WARNING
            count=verdict.count,
            window_seconds=verdict.window_seconds,
            thread_id=thread_id,
            action=ACTION_WARN,
            error_type=type(exc).__name__,
            outcome=outcome,
        )
        return

    log_event(
        "flood_control",
        update,
        count=verdict.count,
        window_seconds=verdict.window_seconds,
        thread_id=thread_id,
        action=ACTION_WARN,
        outcome=outcome,
    )


async def _try_delete(
    update: Update,
    verdict: FloodVerdict,
    thread_id: Optional[int],
    action: str,
) -> bool:
    """Best-effort delete of the offending message. Returns True on success."""
    message = update.effective_message
    if message is None:
        return False
    try:
        await message.delete()
    except Exception as exc:  # noqa: BLE001 - missing perms must not crash the bot
        log_event(
            "flood_control",
            update,
            level=30,
            count=verdict.count,
            window_seconds=verdict.window_seconds,
            thread_id=thread_id,
            action=action,
            error_type=type(exc).__name__,
            outcome="delete_failed",
        )
        return False
    return True


async def _try_mute(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    limits,
    verdict: FloodVerdict,
    thread_id: Optional[int],
    action: str,
) -> bool:
    """Apply a time-bounded, reversible mute via ``restrict_chat_member``.

    Uses ``until_date = now + mute_seconds`` so Telegram auto-lifts the mute when
    it expires — no manual unmute needed. Returns True on success.
    """
    chat = update.effective_chat
    user = update.effective_user
    if chat is None or user is None:
        return False

    from telegram import ChatPermissions  # lazy: keep module import-light

    until = int(time.time()) + limits.mute_seconds
    try:
        await context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=user.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until,
        )
    except Exception as exc:  # noqa: BLE001 - missing perms must not crash the bot
        log_event(
            "flood_control",
            update,
            level=30,
            count=verdict.count,
            window_seconds=verdict.window_seconds,
            thread_id=thread_id,
            action=action,
            mute_seconds=limits.mute_seconds,
            error_type=type(exc).__name__,
            outcome="mute_failed",
        )
        return False
    return True


# --- inline self-tests -------------------------------------------------------


def _selftest() -> None:
    """Prove FloodTracker behaviour on sample inputs. Run via __main__."""

    import doctest

    failures, _ = doctest.testmod(verbose=False)
    assert failures == 0, f"{failures} doctest failure(s)"

    # 1) Burst trips: > max within the window.
    t = FloodTracker(max_messages=8, window_seconds=10)
    tripped = None
    for i in range(9):  # 9 messages at t=0..8 (all within a 10s window)
        tripped = t.record_and_check(42, now=i)
    assert tripped is not None, "9 msgs / <10s should trip ( > 8 )"
    assert tripped.count == 9 and tripped.window_seconds == 10, tripped

    # 2) Cross-topic: thread id is never an input, so messages from different
    #    topics share the same per-user counter and still trip.
    t.reset()
    fake_threads = [1, 2, 3, 4, 5, 6, 1, 2, 3]  # would-be topic ids (ignored)
    verdict = None
    for i, _thread in enumerate(fake_threads):  # same user, "different topics"
        verdict = t.record_and_check(7, now=i)
    assert verdict is not None, "messages across topics must count to one limit"

    # 3) Slow sender stays clear: 1 msg every 5s never fills a 10s/8-msg window.
    t.reset()
    for i in range(20):
        assert t.record_and_check(3, now=i * 5) is None, "slow sender must not trip"

    # 4) Window expiry resets: a long pause drops old stamps from the window.
    t.reset()
    for i in range(8):
        assert t.record_and_check(4, now=i) is None
    # 9th message far in the future -> only it remains in the window.
    assert t.record_and_check(4, now=1000) is None, "old msgs should expire out"

    # 5) Two users are independent.
    t.reset()
    for i in range(8):
        t.record_and_check(100, now=i)
        t.record_and_check(200, now=i)
    # Each user has 8 (not > 8) -> neither tripped yet.
    assert t.record_and_check(100, now=8) is not None  # user 100's 9th trips
    # user 200 still at 8 in window until its own 9th.

    # 6) Config-driven tracker reuse rebuilds on threshold change.
    reset_tracker()
    a = _get_tracker(8, 10)
    b = _get_tracker(8, 10)
    assert a is b, "same thresholds reuse the tracker"
    c = _get_tracker(5, 10)
    assert c is not a, "changed thresholds rebuild the tracker"

    print("flood_control self-tests passed")


if __name__ == "__main__":  # pragma: no cover - manual/dev entry point
    _selftest()
