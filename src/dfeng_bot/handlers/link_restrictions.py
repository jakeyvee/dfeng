"""New-user link restrictions + trust threshold (VOL-209).

The THIRD moderation handler in ``GROUP_PREFILTER`` (-1), registered AFTER
anti-spam (VOL-208) and flood control (VOL-210). Where anti-spam removes
clearly-spammy links *for everyone*, this handler additionally blocks ALL links
(even benign ones) from members who have not yet earned **trust** — so a brand-new
or low-trust member cannot drop links until they have settled in.

Design (two clean layers, mirroring antispam.py / flood_control.py)
------------------------------------------------------------------
1. **Pure helpers** — :func:`message_has_link` (text + Telegram entities ->
   bool) and :func:`is_trusted` (a member's :class:`MemberState` + ``now`` +
   :class:`TrustConfig` -> bool). No Telegram side-effects, fully doctested /
   unit-testable.
2. **Telegram side-effects** — :func:`check`, the async prefilter handler:
   resolves the member's trust, and ONLY when an untrusted member posts a link
   does it remove the message, optionally notify them, log the event, and raise
   ``ApplicationHandlerStop``. A clean (no-link) message passes straight through
   AND advances the member's ``clean_message_count`` toward trust.

Trust threshold (v1 rule, documented + configurable)
---------------------------------------------------
A member is TRUSTED (may post links) when ANY of the following holds:

    * **join age** ``>= TRUST_MIN_AGE_SECONDS`` (default 24h) — they have been in
      the community long enough; OR
    * **clean messages** ``clean_message_count >= TRUST_MIN_MESSAGES``
      (default 3) — they have contributed non-link/non-spam chatter; OR
    * **qualified** — they completed the VOL-204 qualification flow (e.g.
      qualified-as-owner); OR
    * **admin-approved** — a moderator ran ``/trust`` on them (or they are an
      admin, who is exempt up front anyway).

This is deliberately *forgiving* (OR, not AND): any one signal of good standing
lifts the restriction. Tune via ``config.link_restrictions`` (env
``DFENG_LINK_TRUST_MIN_AGE_SECONDS`` / ``DFENG_LINK_TRUST_MIN_MESSAGES``).
Unknown members (no recorded join — e.g. joined before the bot, or state was
evicted) default to ``join_age = +inf`` so they are treated as trusted; this
avoids false-blocking established members and keeps the feature non-punitive.

Trust state (v1 trade-off)
-------------------------
:class:`TrustStore` is a per-process, bounded ``{user_id: MemberState}`` map
(LRU-evicted on overflow), holding ``joined_at``, ``clean_message_count`` and
``admin_approved``. In-memory and NOT shared across instances — the same
single-instance assumption as antispam's repetition memory, flood control's
tracker, and the welcome/support dedupe. A multi-instance deployment would need
a shared store (e.g. Redis). Join time is recorded on the join event via
:func:`record_join` (called from ``membership.on_new_member``); the
qualified-as-owner signal is read live from ``context.user_data`` (VOL-204's
``TAG_KEY``) rather than copied into the store.

Admin exemption
--------------
Admins/moderators (``is_admin``) bypass link restrictions by default; set
``DFENG_LINK_EXEMPT_ADMINS=0`` to apply them to everyone.

Coexistence in GROUP_PREFILTER
-----------------------------
Anti-spam runs first and stops on spam, so by the time this handler runs the
message is non-spam — we never re-delete what anti-spam already removed. We raise
``ApplicationHandlerStop`` ONLY when we actually remove a link message; a clean
message is never blocked and DOES increment ``clean_message_count`` so the member
progresses toward trust.

Run the inline self-tests::

    python3 -m dfeng_bot.handlers.link_restrictions
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Iterable, Optional

from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from ..logging_setup import log_event
from .. import metrics
from .base import get_config, is_admin, thread_id_of

# --- link detection ----------------------------------------------------------

# URL regex fallback (used alongside message entities). Catches http/https,
# bare ``www.`` hosts, telegram links (t.me / telegram.me), and ``@channel``
# style mentions. Entities are the primary signal; this backs them up for
# clients that don't surface entities (or plain-text pastes).
_URL_RE = re.compile(
    r"""(?xi)
    (
        (?:https?://|www\.)\S+              # explicit scheme or www.
        |
        (?:t\.me|telegram\.me)/\S+          # telegram invite/channel links
        |
        \b[a-z0-9][a-z0-9\-]*\.[a-z]{2,}(?:/\S*)?  # bare domain (+ optional path)
        |
        (?<![\w@])@[a-z0-9_]{4,}\b          # @mention of a channel/user
    )
    """
)

# Telegram MessageEntity types that represent a link.
_LINK_ENTITY_TYPES = frozenset({"url", "text_link", "mention", "text_mention"})


def message_has_link(text: Optional[str], entities: Optional[Iterable[object]] = None) -> bool:
    """Return True if ``text`` / ``entities`` contain a link.

    Uses Telegram message entities where available (``url``, ``text_link``,
    ``mention``, ``text_mention``) PLUS a URL regex fallback over the raw text
    (covers plain ``t.me`` links, bare domains, and ``@mentions`` that some
    clients don't tag). Pure & unit-testable — ``entities`` may be real
    :class:`telegram.MessageEntity` objects or any objects with a ``.type``.

    >>> message_has_link("just saying hello", None)
    False
    >>> message_has_link("check http://example.com/path", None)
    True
    >>> message_has_link("join t.me/some_group", None)
    True
    >>> message_has_link("ping @cool_channel here", None)
    True
    >>> class E:  # a stand-in for telegram.MessageEntity
    ...     def __init__(self, t): self.type = t
    >>> message_has_link("see this", [E("text_link")])
    True
    >>> message_has_link("plain text only", [E("bold")])
    False
    """

    for ent in entities or ():
        if getattr(ent, "type", None) in _LINK_ENTITY_TYPES:
            return True
    if text and _URL_RE.search(text):
        return True
    return False


# --- trust model -------------------------------------------------------------

# A join age at or above this is "old enough" to be trusted. Default 24h.
DEFAULT_TRUST_MIN_AGE_SECONDS = 24 * 60 * 60
# This many clean (non-link, non-spam) messages earns trust. Default 3.
DEFAULT_TRUST_MIN_MESSAGES = 3


@dataclass(frozen=True)
class TrustConfig:
    """Tunable trust thresholds + handler toggles (mirrored from config)."""

    min_age_seconds: int = DEFAULT_TRUST_MIN_AGE_SECONDS
    min_messages: int = DEFAULT_TRUST_MIN_MESSAGES
    exempt_admins: bool = True
    # When True, remove silently; when False (default), reply a friendly note.
    silent: bool = False


@dataclass
class MemberState:
    """Per-member trust-relevant state held in the :class:`TrustStore`.

    ``joined_at`` is an epoch second (``time.time``) recorded at join; ``None``
    means the join was never observed by this process (treated as old/trusted).
    ``clean_message_count`` counts non-link messages seen from the member.
    ``admin_approved`` is set by the ``/trust`` admin command.
    """

    joined_at: Optional[float] = None
    clean_message_count: int = 0
    admin_approved: bool = False
    last_touch: float = 0.0


def is_trusted(
    state: Optional[MemberState],
    now: float,
    config: TrustConfig,
    *,
    qualified: bool = False,
) -> bool:
    """Pure trust decision. True => the member may post links.

    Trusted when ANY holds (see module docstring): join age >= min_age_seconds,
    OR clean_message_count >= min_messages, OR ``qualified``, OR admin_approved.
    A missing ``state`` (no observed join) is treated as an established member
    (trusted) — we never block someone we have no join record for.

    Args:
        state: The member's :class:`MemberState`, or ``None`` if unknown.
        now: Current epoch seconds (injected for testability).
        config: Trust thresholds.
        qualified: Whether the member completed qualification (VOL-204). Read by
            the handler from ``context.user_data`` and passed in here.

    >>> cfg = TrustConfig(min_age_seconds=86400, min_messages=3)
    >>> fresh = MemberState(joined_at=1000.0, clean_message_count=0)
    >>> is_trusted(fresh, now=1000.0, config=cfg)          # just joined
    False
    >>> is_trusted(fresh, now=1000.0 + 86400, config=cfg)  # 24h later
    True
    >>> chatty = MemberState(joined_at=2000.0, clean_message_count=3)
    >>> is_trusted(chatty, now=2000.0, config=cfg)         # enough clean msgs
    True
    >>> is_trusted(MemberState(joined_at=3000.0), now=3000.0, config=cfg, qualified=True)
    True
    >>> approved = MemberState(joined_at=4000.0, admin_approved=True)
    >>> is_trusted(approved, now=4000.0, config=cfg)       # admin-approved
    True
    >>> is_trusted(None, now=0.0, config=cfg)              # unknown -> trusted
    True
    """

    if state is None:
        return True
    if state.admin_approved or qualified:
        return True
    if state.clean_message_count >= config.min_messages:
        return True
    if state.joined_at is None:
        return True  # no recorded join => established member.
    return (now - state.joined_at) >= config.min_age_seconds


# --- trust store (stateful, per-process, bounded) ----------------------------


class TrustStore:
    """Bounded per-process ``{user_id: MemberState}`` map. No I/O.

    The outer map is bounded to ``max_users``; on overflow the
    least-recently-touched member is evicted (their state is reconstructible: a
    re-observed join re-records, and an evicted established member simply reads as
    "unknown" -> trusted). Pure data structure — the async handler owns the
    Telegram side-effects.
    """

    __slots__ = ("max_users", "_states")

    def __init__(self, *, max_users: int = 5000) -> None:
        self.max_users = max_users
        self._states: dict[int, MemberState] = {}

    def _evict_if_needed(self, user_id: int) -> None:
        if user_id not in self._states and len(self._states) >= self.max_users:
            oldest = min(self._states, key=lambda uid: self._states[uid].last_touch)
            self._states.pop(oldest, None)

    def get(self, user_id: int) -> Optional[MemberState]:
        """Return the member's state, or ``None`` if unknown."""
        return self._states.get(user_id)

    def record_join(self, user_id: int, *, now: Optional[float] = None) -> MemberState:
        """Record (or refresh) a member's join time; resets trust progression."""
        now = time.time() if now is None else now
        self._evict_if_needed(user_id)
        state = self._states.get(user_id)
        if state is None:
            state = MemberState()
            self._states[user_id] = state
        state.joined_at = now
        state.clean_message_count = 0
        state.last_touch = now
        return state

    def note_clean_message(self, user_id: int, *, now: Optional[float] = None) -> MemberState:
        """Increment the member's clean-message count and return their state.

        If the member is unknown (no observed join), a state is created with
        ``joined_at=None`` (established member) so counting still progresses but
        join-age never blocks them.
        """
        now = time.time() if now is None else now
        self._evict_if_needed(user_id)
        state = self._states.get(user_id)
        if state is None:
            state = MemberState(joined_at=None)
            self._states[user_id] = state
        state.clean_message_count += 1
        state.last_touch = now
        return state

    def approve(self, user_id: int, *, now: Optional[float] = None) -> MemberState:
        """Mark a member as admin-approved (manual ``/trust``)."""
        now = time.time() if now is None else now
        self._evict_if_needed(user_id)
        state = self._states.get(user_id)
        if state is None:
            state = MemberState()
            self._states[user_id] = state
        state.admin_approved = True
        state.last_touch = now
        return state

    def reset(self) -> None:
        """Clear all tracked state (used by tests / process reset)."""
        self._states.clear()


# --- module-level store (per-process) ----------------------------------------

_store = TrustStore()


def get_store() -> TrustStore:
    """Return the shared per-process :class:`TrustStore`."""
    return _store


def record_join(user_id: int, *, now: Optional[float] = None) -> None:
    """Record a member's join time in the shared store.

    Called from ``membership.on_new_member`` so trust progression starts the
    moment a member joins. Safe to call repeatedly (refreshes the timestamp).
    """
    _store.record_join(user_id, now=now)


def reset_store() -> None:
    """Reset the module-level trust store (used by tests)."""
    _store.reset()


# --- config bridge -----------------------------------------------------------


def config_from(config) -> TrustConfig:
    """Build a :class:`TrustConfig` from the runtime :class:`Config`."""
    lr = config.link_restrictions
    return TrustConfig(
        min_age_seconds=lr.trust_min_age_seconds,
        min_messages=lr.trust_min_messages,
        exempt_admins=lr.exempt_admins,
        silent=lr.silent,
    )


def _is_qualified(context: ContextTypes.DEFAULT_TYPE) -> bool:
    """True if the member completed qualification (VOL-204 stashed a tag)."""
    from .qualification import TAG_KEY  # local import keeps the seam tidy

    user_data = getattr(context, "user_data", None)
    return bool(user_data and user_data.get(TAG_KEY))


# Concise, friendly, on-tone notice (VOL-209). No links, no shaming.
NOTICE_TEXT = (
    "Hey! 🧡 New members can't post links just yet — hang out and chat with us a "
    "bit first, and you'll be able to share links soon. Thanks for understanding!"
)


# --- async prefilter handler -------------------------------------------------


async def check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prefilter handler: block links from untrusted (new/low-trust) members.

    Registered in ``GROUP_PREFILTER`` (-1), AFTER anti-spam + flood control.
    Behaviour:
        * gated by ``config.features.link_restrictions`` (default OFF until
          enabled);
        * admins exempt unless ``exempt_admins`` is False;
        * if the message has NO link: increment the member's clean-message count
          (trust progression) and return WITHOUT blocking — other handlers run;
        * if the message HAS a link and the member IS trusted: return without
          blocking (trusted members may post links);
        * if the message HAS a link and the member is NOT trusted: delete it,
          optionally reply a friendly notice (unless ``silent``), log the event
          (id/username, thread, domain, reason — never the message body), and
          raise ``ApplicationHandlerStop``.
    """

    message = update.effective_message
    if message is None:
        return

    config = get_config(context)
    if not config.features.link_restrictions:
        return

    trust_cfg = config_from(config)

    # Admin exemption (default ON).
    if trust_cfg.exempt_admins and is_admin(update, context):
        return

    user = update.effective_user
    user_id = user.id if user else 0
    if not user_id:
        return

    text = message.text or message.caption
    entities = list(message.entities or ()) + list(message.caption_entities or ())

    if not message_has_link(text, entities):
        # Clean message: advance trust progression, never block.
        _store.note_clean_message(user_id)
        return

    # Message has a link — decide based on trust.
    state = _store.get(user_id)
    if is_trusted(state, time.time(), trust_cfg, qualified=_is_qualified(context)):
        return  # trusted member may post links — pass through.

    thread_id = thread_id_of(update)
    domain = _first_link_domain(text, entities)

    deleted = True
    try:
        await message.delete()
    except Exception as exc:  # noqa: BLE001 - missing perms must not crash the bot
        deleted = False
        log_event(
            "link_restriction",
            update,
            level=30,  # logging.WARNING
            reason="untrusted_link",
            domain=domain,
            thread_id=thread_id,
            action="delete",
            error_type=type(exc).__name__,
            outcome="delete_failed",
        )
    else:
        log_event(
            "link_restriction",
            update,
            reason="untrusted_link",
            domain=domain,
            thread_id=thread_id,
            action="delete",
            outcome="removed",
        )
        metrics.bump(context, "spam_action")

    # Friendly notice (unless silent). Best-effort; failure must not crash.
    if not trust_cfg.silent:
        from .base import reply_in_thread  # local import keeps the seam tidy

        try:
            await reply_in_thread(update, NOTICE_TEXT, context=context)
        except Exception as exc:  # noqa: BLE001
            log_event(
                "link_restriction",
                update,
                level=30,
                reason="untrusted_link",
                thread_id=thread_id,
                action="notify",
                error_type=type(exc).__name__,
                outcome="notify_failed",
            )

    # We removed (or attempted to remove) the link — consume the update so
    # downstream handlers don't also act on it.
    if deleted:
        raise ApplicationHandlerStop


def _first_link_domain(text: Optional[str], entities: Iterable[object]) -> Optional[str]:
    """Best-effort domain/host of the first link, for SAFE logging.

    Returns a host string (e.g. ``t.me``) or an ``@mention`` handle — never the
    full message body. Prefers ``text_link`` entity URLs, falls back to the regex.
    """

    for ent in entities or ():
        if getattr(ent, "type", None) == "text_link":
            url = getattr(ent, "url", None)
            if url:
                return _host_of(url)
    if text:
        m = _URL_RE.search(text)
        if m:
            token = m.group(0)
            if token.startswith("@"):
                return token  # channel/user mention handle (public, safe)
            return _host_of(token)
    return None


def _host_of(url: str) -> str:
    """Extract a host from a URL-ish token (no urllib needed)."""
    host = url
    if "://" in host:
        host = host.split("://", 1)[1]
    host = host.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    return host


# --- admin /trust command ----------------------------------------------------


async def cmd_trust(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command: manually trust/approve a member so they can post links.

    Usage: reply to one of the member's messages with ``/trust``, or
    ``/trust <user_id>``. Restricted to admins (``DFENG_ADMIN_IDS``). Sets the
    member's ``admin_approved`` flag in the trust store.
    """

    from .base import reply_in_thread

    if not is_admin(update, context):
        log_event("cmd_trust", update, outcome="denied")
        await reply_in_thread(update, "Not authorised.", context=context)
        return

    target_id: Optional[int] = None
    message = update.effective_message
    reply_to = getattr(message, "reply_to_message", None) if message else None
    if reply_to is not None and getattr(reply_to, "from_user", None) is not None:
        target_id = reply_to.from_user.id
    elif context.args:
        try:
            target_id = int(context.args[0])
        except (ValueError, IndexError):
            target_id = None

    if not target_id:
        await reply_in_thread(
            update,
            "Usage: reply to the member's message with /trust, or /trust <user_id>.",
            context=context,
        )
        return

    _store.approve(target_id)
    log_event("cmd_trust", update, target_id=target_id, outcome="approved")
    await reply_in_thread(
        update, f"Done — user {target_id} can now post links. 🧡", context=context
    )


# --- inline self-tests -------------------------------------------------------


def _selftest() -> None:
    """Prove message_has_link + is_trusted on sample inputs. Run via __main__."""

    import doctest

    failures, _ = doctest.testmod(verbose=False)
    assert failures == 0, f"{failures} doctest failure(s)"

    class _E:  # stand-in for telegram.MessageEntity
        def __init__(self, type_, url=None):
            self.type = type_
            self.url = url

    # 1) message_has_link: plain url / t.me / text_link entity / mention / none.
    assert message_has_link("plain http://example.com now", None) is True
    assert message_has_link("come to t.me/dongfeng", None) is True
    assert message_has_link("hidden", [_E("text_link", "http://x.io")]) is True
    assert message_has_link("hey @some_channel", None) is True
    assert message_has_link("entity url type", [_E("url")]) is True
    assert message_has_link("no link at all here", None) is False
    assert message_has_link("no link", [_E("bold")]) is False
    # Caption entities flow through the same helper (handler merges them).
    assert message_has_link("see pic", [_E("text_link", "http://y.io")]) is True

    # 2) is_trusted transitions.
    cfg = TrustConfig(min_age_seconds=86400, min_messages=3)
    # fresh join -> NOT trusted.
    fresh = MemberState(joined_at=1000.0, clean_message_count=0)
    assert is_trusted(fresh, now=1000.0, config=cfg) is False
    # old enough -> trusted.
    assert is_trusted(fresh, now=1000.0 + 86400, config=cfg) is True
    # enough clean messages -> trusted (even when fresh).
    chatty = MemberState(joined_at=2000.0, clean_message_count=3)
    assert is_trusted(chatty, now=2000.0, config=cfg) is True
    # qualified -> trusted.
    assert is_trusted(MemberState(joined_at=3000.0), now=3000.0, config=cfg, qualified=True) is True
    # admin-approved -> trusted.
    assert is_trusted(MemberState(joined_at=4000.0, admin_approved=True), now=4000.0, config=cfg) is True
    # unknown member -> trusted (never block someone with no join record).
    assert is_trusted(None, now=0.0, config=cfg) is True

    # 3) TrustStore: join -> not trusted; clean messages cross the threshold.
    store = TrustStore()
    store.reset()
    store.record_join(99, now=0.0)
    s = store.get(99)
    assert s is not None and s.joined_at == 0.0
    assert is_trusted(s, now=1.0, config=cfg) is False  # fresh, 0 clean msgs
    store.note_clean_message(99, now=1.0)
    store.note_clean_message(99, now=2.0)
    assert is_trusted(store.get(99), now=3.0, config=cfg) is False  # only 2
    store.note_clean_message(99, now=3.0)
    assert is_trusted(store.get(99), now=4.0, config=cfg) is True   # 3 -> trusted

    # 4) join-age path: a member who just stays long enough becomes trusted.
    store.reset()
    store.record_join(7, now=0.0)
    assert is_trusted(store.get(7), now=10.0, config=cfg) is False
    assert is_trusted(store.get(7), now=86400.0, config=cfg) is True

    # 5) admin approve path.
    store.reset()
    store.record_join(7, now=0.0)
    store.approve(7, now=1.0)
    assert is_trusted(store.get(7), now=2.0, config=cfg) is True

    # 6) eviction keeps the store bounded.
    small = TrustStore(max_users=2)
    small.record_join(1, now=0.0)
    small.record_join(2, now=1.0)
    small.record_join(3, now=2.0)  # evicts user 1 (oldest touch)
    assert small.get(1) is None and small.get(2) is not None and small.get(3) is not None

    print("link_restrictions self-tests passed")


if __name__ == "__main__":  # pragma: no cover - manual/dev entry point
    _selftest()
