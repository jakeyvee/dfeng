"""Anti-spam detection + prefilter handler (VOL-208).

This is the FIRST moderation handler to live in ``GROUP_PREFILTER`` (-1). It
catches obviously-spammy group messages *before* the normal message handlers
(support redirection, qualification, logging) run, deletes them where the bot
has permission, and consumes the update via ``ApplicationHandlerStop`` so no
downstream handler acts on spam.

Design (two clean layers)
-------------------------
1. **Pure detection** — :func:`classify_spam` (and the helpers it calls) take
   plain ``text`` + extracted ``urls`` and return an optional :class:`SpamVerdict`.
   No Telegram objects, no I/O, fully unit-testable. Rule lists come from a
   :class:`SpamRules` bundle so deployments can tune them without code changes.
2. **Telegram side-effects** — :func:`check`, the async prefilter handler, pulls
   the message, runs detection, performs the delete / optional restrict, logs
   every action via :func:`log_event`, and raises ``ApplicationHandlerStop`` when
   it removes a message.

Spam categories (VOL-208)
-------------------------
* ``crypto``     — pump/airdrop/giveaway/100x/pre-sale scam phrasing.
* ``ad``         — external promo unrelated to Dongfeng ("DM me", "join my
                   channel", "WhatsApp +", "promo code", ...).
* ``link``       — clearly-spammy links: URL shorteners, ``t.me`` invite links to
                   *other* groups, crypto/airdrop domains, and known scam TLDs.
                   (New-user / low-trust link restriction is VOL-209, out of scope.)
* ``repetition`` — the same/near-identical message repeated N times within a
                   window by one user.

Repetition memory
-----------------
A per-process, bounded ``{user_id: deque[(normalized_text, monotonic_ts)]}`` map
tracks each user's recent messages. v1 trade-off: in-memory and NOT shared across
instances (same single-instance assumption as welcome/support dedupe). A
multi-instance deployment would need a shared store.

Admin exemption
---------------
Admins/moderators (``is_admin``) are exempt by default. Set
``SpamRules.exempt_admins = False`` (env ``DFENG_SPAM_EXEMPT_ADMINS=0``) to apply
rules to everyone.

False-positive risk
-------------------
Rules are deliberately specific (crypto-scam phrasing + shortener/scam domains +
hard promo phrases) to avoid nuking legitimate community chatter. A normal
Dongfeng message like "Loving my BOX on weekend trips!" is NOT flagged. The
``allowed_domains`` allowlist exempts community links (e.g. ``dongfeng.com``,
``t.me`` is allowed for the community's *own* group only insofar as bare
``t.me`` links are treated as ad/invite spam — tune the allowlist per policy).

Run the inline self-tests::

    python3 -m dfeng_bot.handlers.antispam
"""

from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from ..logging_setup import log_event
from .base import get_config, is_admin, thread_id_of

# --- spam category labels ----------------------------------------------------

CATEGORY_CRYPTO = "crypto"
CATEGORY_AD = "ad"
CATEGORY_LINK = "link"
CATEGORY_REPETITION = "repetition"


# --- default tunable rule lists ---------------------------------------------
# These are module-level DEFAULTS. The live values come from ``config.spam``
# (env / optional config/spam-rules.yaml), so deployments tune them without code
# changes. Kept here so detection has sane behaviour even with empty config.

# Crypto-promo / scam phrasing. Word-boundary aware, case-insensitive.
DEFAULT_CRYPTO_KEYWORDS: list[str] = [
    "pump",
    "airdrop",
    "free crypto",
    "100x",
    "1000x",
    "usdt giveaway",
    "crypto giveaway",
    "pre-sale",
    "presale",
    "pre sale",
    "to the moon",
    "guaranteed returns",
    "double your",
    "send eth",
    "send btc",
    "elon",
    "shiba",
    "memecoin",
    "web3 project",
    "mint now",
    "whitelist spot",
]

# External-advertisement / promo phrasing unrelated to Dongfeng.
DEFAULT_AD_KEYWORDS: list[str] = [
    "telegram.me/",
    "join my channel",
    "join my group",
    "dm me",
    "pm me",
    "whatsapp +",
    "whatsapp me",
    "promo code",
    "click the link in my bio",
    "link in bio",
    "make money fast",
    "work from home",
    "earn $",
    "subscribe to my",
]

# URL shortener hosts — almost always used to mask spam/scam destinations.
DEFAULT_SHORTENER_DOMAINS: list[str] = [
    "bit.ly",
    "tinyurl.com",
    "t.co",
    "goo.gl",
    "ow.ly",
    "is.gd",
    "buff.ly",
    "rebrand.ly",
    "cutt.ly",
    "shorturl.at",
    "rb.gy",
]

# Crypto / airdrop scam domains (substring match on host).
DEFAULT_BLOCKED_DOMAINS: list[str] = [
    "airdrop",
    "free-crypto",
    "claim-",
    "-giveaway",
    "metamask-",
    "wallet-connect",
]

# Scam-favoured TLD suffixes (host endings).
DEFAULT_BLOCKED_TLDS: list[str] = [
    ".xyz",
    ".top",
    ".click",
    ".gq",
    ".tk",
    ".work",
    ".loan",
]

# Repetition: N identical-ish messages within the window => spam.
DEFAULT_REPEAT_COUNT = 3
DEFAULT_REPEAT_WINDOW_SECONDS = 60

# Naive but effective URL extractor (http/https + bare-domain-with-path forms).
_URL_RE = re.compile(
    r"""(?xi)
    \b(
        (?:https?://|www\.)\S+              # explicit scheme or www.
        |
        (?:t\.me|telegram\.me)/\S+          # telegram invite/channel links
        |
        [a-z0-9][a-z0-9\-]*\.[a-z]{2,}/\S*  # bare domain + path (e.g. bit.ly/x)
    )
    """
)


# --- rule bundle -------------------------------------------------------------


@dataclass(frozen=True)
class SpamRules:
    """Tunable rule lists + thresholds for :func:`classify_spam`.

    Built from :class:`~dfeng_bot.config.SpamSettings` in :func:`rules_from_config`,
    which itself loads from env (and an optional ``config/spam-rules.yaml``). All
    keyword/domain matching is case-insensitive.
    """

    crypto_keywords: list[str] = field(default_factory=lambda: list(DEFAULT_CRYPTO_KEYWORDS))
    ad_keywords: list[str] = field(default_factory=lambda: list(DEFAULT_AD_KEYWORDS))
    shortener_domains: list[str] = field(default_factory=lambda: list(DEFAULT_SHORTENER_DOMAINS))
    blocked_domains: list[str] = field(default_factory=lambda: list(DEFAULT_BLOCKED_DOMAINS))
    blocked_tlds: list[str] = field(default_factory=lambda: list(DEFAULT_BLOCKED_TLDS))
    allowed_domains: list[str] = field(default_factory=list)
    repeat_count: int = DEFAULT_REPEAT_COUNT
    repeat_window_seconds: int = DEFAULT_REPEAT_WINDOW_SECONDS
    # Operational toggles (mirrored from config; kept here so detection + handler
    # read one bundle).
    block_links: bool = True
    exempt_admins: bool = True
    # Escalate to a temporary restrict after this many removed messages by the
    # same user (0 disables escalation -> delete + log only).
    restrict_after: int = 0
    restrict_seconds: int = 3600


@dataclass(frozen=True)
class SpamVerdict:
    """Result of classifying a message as spam."""

    category: str  # one of CATEGORY_*
    rule: str      # the specific matched keyword/domain/threshold (for logging)


# --- pure detection ----------------------------------------------------------


def extract_urls(text: Optional[str]) -> list[str]:
    """Return URL-ish tokens found in ``text`` (lowercased, stripped).

    >>> extract_urls("see http://bit.ly/abc now")
    ['http://bit.ly/abc']
    >>> extract_urls("join t.me/some_group please")
    ['t.me/some_group']
    >>> extract_urls("no links here")
    []
    """

    if not text:
        return []
    return [m.group(0).rstrip(".,!?)").lower() for m in _URL_RE.finditer(text)]


def _host_of(url: str) -> str:
    """Best-effort host extraction from a URL-ish token (no urllib needed)."""
    host = url
    if "://" in host:
        host = host.split("://", 1)[1]
    host = host.split("/", 1)[0]
    host = host.split("?", 1)[0].split("#", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def _compile_keywords(keywords: list[str]) -> list[tuple[str, "re.Pattern[str]"]]:
    """Compile keywords to case-insensitive matchers.

    Phrases containing a non-word character (``.``, ``+``, ``/``, ``$``) match as
    a plain case-insensitive substring (word boundaries don't apply cleanly to
    e.g. ``"whatsapp +"`` or ``"telegram.me/"``). Pure alphanumeric tokens use
    ``\\b`` word boundaries so ``"pump"`` does not fire inside ``"pumpkin"``.
    """

    compiled: list[tuple[str, re.Pattern[str]]] = []
    for kw in keywords:
        if re.fullmatch(r"[\w ]+", kw):
            pattern = r"\b" + r"\s+".join(re.escape(p) for p in kw.split()) + r"\b"
        else:
            pattern = re.escape(kw)
        compiled.append((kw, re.compile(pattern, re.IGNORECASE)))
    return compiled


def _match_keyword(text: str, keywords: list[str]) -> Optional[str]:
    for kw, pattern in _compile_keywords(keywords):
        if pattern.search(text):
            return kw
    return None


def _is_allowed_host(host: str, allowed: list[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in (a.lower() for a in allowed))


def classify_links(urls: list[str], rules: SpamRules) -> Optional[SpamVerdict]:
    """Classify the link portion of a message. Pure.

    Flags shorteners, ``t.me``/``telegram.me`` invite/channel links to other
    groups, crypto/airdrop scam domains, and scam TLDs — unless the host is on
    ``allowed_domains``. Returns the first offending link's verdict.
    """

    if not rules.block_links:
        return None
    for url in urls:
        host = _host_of(url)
        if not host:
            continue
        if _is_allowed_host(host, rules.allowed_domains):
            continue
        # Telegram invite / channel links to other groups.
        if host in {"t.me", "telegram.me"}:
            return SpamVerdict(CATEGORY_LINK, f"telegram_link:{host}")
        # URL shorteners.
        if any(host == d or host.endswith("." + d) for d in rules.shortener_domains):
            return SpamVerdict(CATEGORY_LINK, f"shortener:{host}")
        # Crypto/airdrop scam domains (substring on host).
        for needle in rules.blocked_domains:
            if needle.lower() in host:
                return SpamVerdict(CATEGORY_LINK, f"blocked_domain:{needle}")
        # Scam-favoured TLDs.
        for tld in rules.blocked_tlds:
            if host.endswith(tld.lower()):
                return SpamVerdict(CATEGORY_LINK, f"blocked_tld:{tld}")
    return None


def classify_spam(
    text: Optional[str],
    urls: Optional[list[str]] = None,
    rules: Optional[SpamRules] = None,
) -> Optional[SpamVerdict]:
    """Classify a message's content as spam. Pure & unit-testable.

    Checks (in order): crypto promo -> external ad -> suspicious link. Repetition
    is stateful and handled separately by :func:`check` via :func:`note_and_check_repeat`
    (it needs per-user history), but the ``CATEGORY_REPETITION`` verdict is built
    by the same machinery.

    Args:
        text: The message text (may be ``None``/empty).
        urls: Pre-extracted URLs; if ``None`` they are extracted from ``text``.
        rules: Tunable :class:`SpamRules`; defaults to module defaults.

    Returns:
        A :class:`SpamVerdict` (category + matched rule) or ``None`` if clean.

    >>> v = classify_spam("Free crypto airdrop! 100x guaranteed, DM me")
    >>> v.category
    'crypto'
    >>> classify_spam("Join my channel for promo code DEALS").category
    'ad'
    >>> classify_spam("check this http://bit.ly/win").category
    'link'
    >>> classify_spam("Loving my BOX on weekend trips!") is None
    True
    """

    rules = rules or SpamRules()
    if not text:
        text = ""
    if urls is None:
        urls = extract_urls(text)

    crypto = _match_keyword(text, rules.crypto_keywords)
    if crypto:
        return SpamVerdict(CATEGORY_CRYPTO, f"keyword:{crypto}")

    ad = _match_keyword(text, rules.ad_keywords)
    if ad:
        return SpamVerdict(CATEGORY_AD, f"keyword:{ad}")

    link_verdict = classify_links(urls, rules)
    if link_verdict is not None:
        return link_verdict

    return None


# --- repetition memory (stateful, per-process, bounded) ----------------------

# user_id -> deque of (normalized_text, monotonic_ts), most-recent last.
_recent_messages: dict[int, "deque[tuple[str, float]]"] = {}
_MAX_USERS = 5000          # bound the outer map (evict oldest-touched on overflow)
_MAX_PER_USER = 12         # bound history per user
_user_touch: dict[int, float] = {}


def _normalize(text: str) -> str:
    """Collapse whitespace + casefold so near-identical repeats match."""
    return re.sub(r"\s+", " ", text).strip().casefold()


def note_and_check_repeat(
    user_id: int,
    text: Optional[str],
    rules: SpamRules,
    *,
    now: Optional[float] = None,
) -> Optional[SpamVerdict]:
    """Record ``text`` for ``user_id`` and flag if it repeats too often.

    Returns a ``CATEGORY_REPETITION`` verdict when the user has sent
    ``rules.repeat_count`` identical (normalized) messages within
    ``rules.repeat_window_seconds`` (inclusive of the current one). Bounded and
    self-evicting.

    >>> r = SpamRules(repeat_count=3, repeat_window_seconds=60)
    >>> reset_repeat_memory()
    >>> note_and_check_repeat(1, "buy now", r, now=0) is None
    True
    >>> note_and_check_repeat(1, "buy now", r, now=1) is None
    True
    >>> note_and_check_repeat(1, "buy now", r, now=2).category
    'repetition'
    """

    if not text:
        return None
    now = time.monotonic() if now is None else now
    norm = _normalize(text)

    # Evict least-recently-touched users if the map is oversized.
    if user_id not in _recent_messages and len(_recent_messages) >= _MAX_USERS:
        oldest = min(_user_touch, key=_user_touch.get)
        _recent_messages.pop(oldest, None)
        _user_touch.pop(oldest, None)

    history = _recent_messages.setdefault(user_id, deque(maxlen=_MAX_PER_USER))
    _user_touch[user_id] = now
    history.append((norm, now))

    window = rules.repeat_window_seconds
    count = sum(1 for t, ts in history if t == norm and now - ts <= window)
    if count >= rules.repeat_count:
        return SpamVerdict(CATEGORY_REPETITION, f"repeat_x{count}")
    return None


def reset_repeat_memory() -> None:
    """Clear the per-user repetition memory (used by tests)."""
    _recent_messages.clear()
    _user_touch.clear()


# --- config bridge -----------------------------------------------------------


def rules_from_config(config) -> SpamRules:
    """Build a :class:`SpamRules` from the runtime :class:`Config`.

    Uses configured lists when present, else module defaults, so a deployment can
    fully override rules via env / ``config/spam-rules.yaml`` (loaded in
    ``config.py``) without code changes.
    """

    spam = config.spam
    return SpamRules(
        crypto_keywords=list(spam.crypto_keywords) or list(DEFAULT_CRYPTO_KEYWORDS),
        ad_keywords=list(spam.ad_keywords) or list(DEFAULT_AD_KEYWORDS),
        shortener_domains=list(spam.shortener_domains) or list(DEFAULT_SHORTENER_DOMAINS),
        blocked_domains=list(spam.blocked_domains) or list(DEFAULT_BLOCKED_DOMAINS),
        blocked_tlds=list(spam.blocked_tlds) or list(DEFAULT_BLOCKED_TLDS),
        allowed_domains=list(spam.allowed_domains),
        repeat_count=spam.repeat_count,
        repeat_window_seconds=spam.repeat_window_seconds,
        block_links=spam.block_links,
        exempt_admins=spam.exempt_admins,
        restrict_after=spam.restrict_after,
        restrict_seconds=spam.restrict_seconds,
    )


# Track removed-message counts per user this process, for restrict escalation.
_offense_counts: dict[int, int] = {}


def reset_offense_counts() -> None:
    """Clear per-user offense counters (used by tests)."""
    _offense_counts.clear()


# --- async prefilter handler -------------------------------------------------


async def check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prefilter handler: detect spam, remove it, and consume the update.

    Registered in ``GROUP_PREFILTER`` (-1). Behaviour:
        * gated by ``config.features.antispam`` (default OFF until enabled);
        * admins exempt unless ``rules.exempt_admins`` is False;
        * runs pure detection + stateful repetition check;
        * on a spam verdict: delete the message (log + flag if no permission),
          optionally escalate to a temporary restrict, then raise
          ``ApplicationHandlerStop`` so downstream handlers don't act on spam;
        * on a clean message: return without blocking other handlers.

    Never logs the message body — only the matched rule/category (PII-safe).
    """

    message = update.effective_message
    if message is None:
        return

    config = get_config(context)
    if not config.features.antispam:
        return

    rules = rules_from_config(config)

    # Admin exemption (default ON).
    if rules.exempt_admins and is_admin(update, context):
        return

    user = update.effective_user
    user_id = user.id if user else 0
    thread_id = thread_id_of(update)
    text = message.text or message.caption

    # Content classification (crypto / ad / link), then stateful repetition.
    verdict = classify_spam(text, rules=rules)
    if verdict is None:
        verdict = note_and_check_repeat(user_id, text, rules)
    if verdict is None:
        return  # clean — do NOT block other handlers.

    # --- spam: attempt removal ----------------------------------------------
    action = "deleted"
    try:
        await message.delete()
    except Exception as exc:  # noqa: BLE001 - missing perms must not crash the bot
        action = "flagged"  # delete failed (likely no delete permission)
        log_event(
            "antispam_action",
            update,
            level=30,  # logging.WARNING
            category=verdict.category,
            rule=verdict.rule,
            thread_id=thread_id,
            action=action,
            error_type=type(exc).__name__,
            outcome="delete_failed",
        )
    else:
        log_event(
            "antispam_action",
            update,
            category=verdict.category,
            rule=verdict.rule,
            thread_id=thread_id,
            action=action,
            outcome="removed",
        )

    # --- optional escalation: temporary restrict on repeated offenses --------
    if rules.restrict_after > 0 and user_id:
        _offense_counts[user_id] = _offense_counts.get(user_id, 0) + 1
        if _offense_counts[user_id] >= rules.restrict_after:
            await _try_restrict(update, context, rules, verdict, thread_id)

    # Consume the update so support-redirect / qualification / logging skip spam.
    raise ApplicationHandlerStop


async def _try_restrict(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    rules: SpamRules,
    verdict: SpamVerdict,
    thread_id: Optional[int],
) -> None:
    """Best-effort temporary mute. Optional / config-gated; failures are logged."""

    chat = update.effective_chat
    user = update.effective_user
    if chat is None or user is None:
        return

    from telegram import ChatPermissions  # lazy: keep module import-light

    until = int(time.time()) + rules.restrict_seconds
    try:
        await context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=user.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until,
        )
    except Exception as exc:  # noqa: BLE001
        log_event(
            "antispam_action",
            update,
            level=30,
            category=verdict.category,
            rule=verdict.rule,
            thread_id=thread_id,
            action="restrict",
            error_type=type(exc).__name__,
            outcome="restrict_failed",
        )
        return

    log_event(
        "antispam_action",
        update,
        category=verdict.category,
        rule=verdict.rule,
        thread_id=thread_id,
        action="restrict",
        restrict_seconds=rules.restrict_seconds,
        outcome="restricted",
    )


# --- inline self-tests -------------------------------------------------------


def _selftest() -> None:
    """Prove classify_spam + repetition on sample inputs. Run via __main__."""

    import doctest

    failures, _ = doctest.testmod(verbose=False)
    assert failures == 0, f"{failures} doctest failure(s)"

    rules = SpamRules()

    # 1) Crypto promos.
    for text in (
        "Join the USDT giveaway, free crypto airdrop 100x!",
        "Pre-sale live, send ETH to double your money",
        "New memecoin to the moon, guaranteed returns",
    ):
        v = classify_spam(text, rules=rules)
        assert v is not None and v.category == CATEGORY_CRYPTO, (text, v)

    # 2) External ads.
    for text in (
        "DM me for a promo code",
        "Join my channel for deals",
        "WhatsApp + me to earn $$$",
    ):
        v = classify_spam(text, rules=rules)
        assert v is not None and v.category == CATEGORY_AD, (text, v)

    # 3) Suspicious links.
    for text in (
        "check http://bit.ly/win now",
        "free stuff at https://claim-reward.xyz",
        "join t.me/some_other_group",
    ):
        v = classify_spam(text, rules=rules)
        assert v is not None and v.category == CATEGORY_LINK, (text, v)

    # Allowlist exempts community domains.
    allowed = SpamRules(allowed_domains=["dongfeng.com"])
    assert classify_spam("see https://dongfeng.com/box", rules=allowed) is None

    # 4) Repetition.
    reset_repeat_memory()
    rep = SpamRules(repeat_count=3, repeat_window_seconds=60)
    assert note_and_check_repeat(7, "buy now buy now", rep, now=0) is None
    assert note_and_check_repeat(7, "buy now  buy now", rep, now=10) is None
    third = note_and_check_repeat(7, "BUY NOW buy now", rep, now=20)
    assert third is not None and third.category == CATEGORY_REPETITION, third
    # Outside the window does not accumulate.
    reset_repeat_memory()
    assert note_and_check_repeat(7, "hello", rep, now=0) is None
    assert note_and_check_repeat(7, "hello", rep, now=200) is None

    # 5) Legitimate Dongfeng chatter is NOT flagged.
    for text in (
        "Loving my BOX on weekend trips!",
        "Anyone going to the roadshow this weekend?",
        "The new EV charging at the showroom is great",
        "Just booked a test drive, excited!",
    ):
        assert classify_spam(text, rules=rules) is None, text

    print("antispam self-tests passed")


if __name__ == "__main__":  # pragma: no cover - manual/dev entry point
    _selftest()
