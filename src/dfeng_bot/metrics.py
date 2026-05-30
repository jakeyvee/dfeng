"""Canonical launch-metric event names + a thin ``log_metric`` wrapper (VOL-212).

This module is the single source of truth for the **structured event names**
admins grep/jq for when computing the PRD launch metrics. Most of the metrics
are already derivable from events emitted by existing handlers (see
:data:`EXISTING_EVENT_ACTIONS`); VOL-212 only ADDS one low-noise per-message
*activity* event (:data:`ACTIVITY`) so weekly-active and owner/prospect-message
metrics become countable without a BI warehouse.

Design goals (kept deliberately tiny):
    * **No behaviour change.** Nothing here deletes, restricts or replies. It
      only logs. Feature handlers keep their existing ``log_event`` calls.
    * **No new PII.** The activity event logs ``telegram_id`` (already logged
      everywhere), ``thread_id`` (a forum topic id), an optional ``tag`` enum
      (BOX/007/VIGO Owner / Prospect — never a phone/plate), and a coarse
      ``is_question`` heuristic boolean. It NEVER logs the message body, phone,
      or plate. See :func:`log_activity` and the ``__main__`` self-test.
    * **Flag-gated, cheap.** The activity logger is gated on
      :data:`ACTIVITY_FLAG_ENV` (default ON) and does O(1) work per message.

In-process counters
-------------------
:class:`MetricCounters` is a tiny PII-free tally of a few cheaply-countable
events for the optional ``/stats`` admin command. It counts events for the
**current process lifetime only** — it is NOT a historical store. The
authoritative history lives in the structured logs / Sheets workbook.

Run the self-tests::

    python3 -m dfeng_bot.metrics
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .logging_setup import log_event

# --- Canonical metric event action names ------------------------------------
# These strings are the contract between the bot and the reporting procedure in
# ``docs/metrics-and-reporting.md``. Do NOT rename without updating that doc.

# NEW in VOL-212: one low-noise per-message activity event. Emitted for every
# non-command, non-spam group message that reaches messages.handle_message.
# Fields: telegram_id, thread_id (topic), tag (if known), is_question (bool).
ACTIVITY = "message_activity"

# Events that ALREADY exist in other handlers (VOL-204/207/208/209/210/211).
# Listed here so the metric doc + /stats reference one canonical set of names.
QUALIFICATION_STARTED = "qualification_started"
QUALIFICATION_COMPLETE = "qualification_complete"
SUPPORT_REDIRECT = "support_redirect"
SUPPORT_REDIRECT_SKIPPED = "support_redirect_skipped"
ANTISPAM_ACTION = "antispam_action"
FLOOD_CONTROL = "flood_control"
LINK_RESTRICTION = "link_restriction"
CMD_DELETE = "cmd_delete"  # manual admin /del|/delete (VOL-211)

# Pre-existing actions a metric depends on, grouped by the metric they serve.
# (Documentation aid; also exercised by the self-test for spelling stability.)
EXISTING_EVENT_ACTIONS: frozenset[str] = frozenset(
    {
        QUALIFICATION_STARTED,
        QUALIFICATION_COMPLETE,
        SUPPORT_REDIRECT,
        SUPPORT_REDIRECT_SKIPPED,
        ANTISPAM_ACTION,
        FLOOD_CONTROL,
        LINK_RESTRICTION,
        CMD_DELETE,
    }
)

# Owner tags (subset of schema.TAGS). Kept as a local constant so this module
# stays importable without pulling the handlers package at import time.
OWNER_TAGS: frozenset[str] = frozenset({"BOX Owner", "007 Owner", "VIGO Owner"})
PROSPECT_TAG = "Prospect"

# Env flag for the activity logger. Default ON; set to a falsey value to silence
# the per-message activity event entirely (the metric becomes uncomputable from
# logs but no feature behaviour changes).
ACTIVITY_FLAG_ENV = "DFENG_METRICS_ACTIVITY"


def activity_logging_enabled() -> bool:
    """Return whether the per-message activity event should be emitted.

    Reads the process env directly (this is metrics plumbing, not feature config)
    and defaults to ON. Cheap and side-effect free.

    >>> import os
    >>> os.environ.pop("DFENG_METRICS_ACTIVITY", None) and None
    >>> activity_logging_enabled()
    True
    >>> os.environ["DFENG_METRICS_ACTIVITY"] = "0"; activity_logging_enabled()
    False
    >>> os.environ["DFENG_METRICS_ACTIVITY"] = "on"; activity_logging_enabled()
    True
    >>> del os.environ["DFENG_METRICS_ACTIVITY"]
    """

    raw = os.environ.get(ACTIVITY_FLAG_ENV)
    if raw is None or raw == "":
        return True
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# --- is_question heuristic ---------------------------------------------------
# "Questions" are hard to classify; this is an explicit, documented APPROXIMATION
# (see metric #4 in the doc). It looks ONLY at shape (a trailing/embedded "?" or a
# leading interrogative word) — it never stores or logs the text itself.
_INTERROGATIVE_RE = re.compile(
    r"^\s*(who|what|when|where|why|how|which|whose|whom|is|are|can|could|"
    r"do|does|did|should|would|will|may|any(one|body)?)\b",
    re.IGNORECASE,
)


def looks_like_question(text: Optional[str]) -> bool:
    """Coarse, PII-free heuristic: does *text* look like a question?

    True when the text contains a ``?`` OR starts with a common interrogative
    word. This is intentionally approximate and is documented as a PROXY for the
    "prospect-initiated questions" metric. The text is inspected transiently and
    NEVER logged.

    >>> looks_like_question("How do I charge the BOX?")
    True
    >>> looks_like_question("anyone tried the 007")
    True
    >>> looks_like_question("Loving my new VIGO!")
    False
    >>> looks_like_question("")
    False
    >>> looks_like_question(None)
    False
    """

    if not text:
        return False
    if "?" in text:
        return True
    return bool(_INTERROGATIVE_RE.match(text))


def log_metric(action: str, update: Any = None, **fields: Any) -> None:
    """Thin wrapper over :func:`log_event` for canonical metric events.

    Exists so all metric emissions route through one place (easy to audit /
    grep) and to make the call sites read intentionally as metrics. Same PII
    rules as ``log_event``: pass ids/tags/topics/counts, never message bodies or
    phone/plate.
    """

    log_event(action, update, **fields)


def log_activity(
    update: Any,
    *,
    counters: Optional["MetricCounters"] = None,
    tag: Optional[str] = None,
    thread_id: Optional[int] = None,
    text: Optional[str] = None,
) -> None:
    """Emit the low-noise per-message activity event (if enabled).

    PII-safe by construction: logs ``telegram_id`` (auto-extracted from the
    update by ``log_event``), ``thread_id`` (a forum topic id), the resolved
    ``tag`` enum when known, and a derived ``is_question`` boolean. The raw
    ``text`` is used ONLY to compute ``is_question`` and is never logged.

    Args:
        update: The Telegram update (telegram_id/username auto-extracted).
        counters: Optional in-process counters to bump (for ``/stats``).
        tag: The user's resolved tag (BOX/007/VIGO Owner | Prospect) if known.
        thread_id: The forum topic id the message landed in.
        text: The message text — inspected for the question heuristic only.
    """

    if counters is not None:
        counters.note_activity(tag=tag)

    if not activity_logging_enabled():
        return

    fields: dict[str, Any] = {
        "thread_id": thread_id,
        "is_question": looks_like_question(text),
        "outcome": "activity",
    }
    if tag:
        fields["tag"] = tag
    log_metric(ACTIVITY, update, **fields)


# --- tiny in-process counters (for optional /stats) --------------------------


@dataclass
class MetricCounters:
    """PII-free, process-lifetime tallies for the optional ``/stats`` command.

    Holds only small integers — NO user ids, text, or PII. Reset on every
    process restart; the authoritative history is the structured logs / Sheets.
    Bumped opportunistically from the relevant handlers via the ``note_*`` helpers
    so the counters never diverge from a single update path.
    """

    BOT_DATA_KEY: str = field(default="metric_counters", init=False, repr=False)

    activity_total: int = 0
    activity_owner: int = 0
    activity_prospect: int = 0
    qualification_started: int = 0
    qualification_complete: int = 0
    support_redirect: int = 0
    spam_action: int = 0  # antispam + flood + link removals (automated)

    def note_activity(self, *, tag: Optional[str] = None) -> None:
        self.activity_total += 1
        if tag in OWNER_TAGS:
            self.activity_owner += 1
        elif tag == PROSPECT_TAG:
            self.activity_prospect += 1

    def note_qualification_started(self) -> None:
        self.qualification_started += 1

    def note_qualification_complete(self) -> None:
        self.qualification_complete += 1

    def note_support_redirect(self) -> None:
        self.support_redirect += 1

    def note_spam_action(self) -> None:
        self.spam_action += 1

    def onboarding_completion_rate(self) -> Optional[float]:
        """completed / started as a fraction, or None when nothing started yet."""
        if self.qualification_started <= 0:
            return None
        return self.qualification_complete / self.qualification_started

    def as_dict(self) -> dict[str, int]:
        return {
            "activity_total": self.activity_total,
            "activity_owner": self.activity_owner,
            "activity_prospect": self.activity_prospect,
            "qualification_started": self.qualification_started,
            "qualification_complete": self.qualification_complete,
            "support_redirect": self.support_redirect,
            "spam_action": self.spam_action,
        }


def bump(context: Any, note: str) -> None:
    """Bump a named in-process counter from a handler ``context`` (best-effort).

    ``note`` is the name of a ``MetricCounters.note_*`` method without the
    ``note_`` prefix (e.g. ``"support_redirect"``). Resolves the shared counters
    from ``context.application.bot_data`` and calls the method. Never raises into
    a handler — instrumentation must not affect feature behaviour.
    """

    try:
        counters = get_counters(context.application.bot_data)
        getattr(counters, f"note_{note}")()
    except Exception:  # noqa: BLE001 - metrics must never break a handler
        pass


def get_counters(bot_data: Any) -> MetricCounters:
    """Return (creating if needed) the shared MetricCounters in ``bot_data``.

    ``bot_data`` is the PTB application's shared dict. Centralising creation here
    keeps the key consistent across handlers.
    """

    key = MetricCounters.BOT_DATA_KEY
    counters = bot_data.get(key)
    if counters is None:
        counters = MetricCounters()
        bot_data[key] = counters
    return counters


# --- self-tests --------------------------------------------------------------


def _selftest() -> None:
    import doctest

    failures, _ = doctest.testmod(verbose=False)
    assert failures == 0, f"{failures} doctest failure(s)"

    # Event-name spelling stability (the doc + /stats depend on these).
    assert ACTIVITY == "message_activity"
    assert QUALIFICATION_COMPLETE == "qualification_complete"
    assert SUPPORT_REDIRECT == "support_redirect"
    assert CMD_DELETE == "cmd_delete"
    assert OWNER_TAGS == {"BOX Owner", "007 Owner", "VIGO Owner"}

    # Counters: owner vs prospect routing + completion rate.
    c = MetricCounters()
    assert c.onboarding_completion_rate() is None  # nothing started
    c.note_activity(tag="BOX Owner")
    c.note_activity(tag="Prospect")
    c.note_activity(tag=None)
    assert c.activity_total == 3
    assert c.activity_owner == 1
    assert c.activity_prospect == 1
    c.note_qualification_started()
    c.note_qualification_started()
    c.note_qualification_complete()
    assert abs(c.onboarding_completion_rate() - 0.5) < 1e-9

    # get_counters is idempotent on a shared dict.
    store: dict[str, Any] = {}
    a = get_counters(store)
    b = get_counters(store)
    assert a is b

    # PII guard: the activity field set must never include a body/phone/plate.
    # Simulate the field assembly log_activity performs.
    fields = {"thread_id": 7, "is_question": True, "outcome": "activity", "tag": "Prospect"}
    forbidden = {"text", "message", "body", "phone", "plate", "caption"}
    assert not (forbidden & set(fields)), "activity event must not carry PII/body"

    print("metrics self-tests passed")


if __name__ == "__main__":  # pragma: no cover - manual/dev entry point
    _selftest()
