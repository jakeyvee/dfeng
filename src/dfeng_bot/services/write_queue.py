"""Resilient Google Sheets write queue with retries + reconciliation flags (VOL-206).

VOL-205 left :func:`dfeng_bot.handlers.onboarding.persist_member` as the SINGLE
write seam (``ensure_header`` -> ``find`` -> ``update``/``append``). This module
wraps that seam in a resilient async layer so that a Sheets outage NEVER blocks
or crashes the user-facing onboarding flow.

What it gives you
-----------------
    * :meth:`WriteQueue.enqueue` — returns IMMEDIATELY after parking the record on
      a bounded in-memory queue. Onboarding's call site no longer waits on the
      (slow, failure-prone) gspread round-trip.
    * A single background async worker (:meth:`WriteQueue.start` /
      :meth:`WriteQueue.stop`) that drains the queue, calling ``persist_member``
      through ``asyncio.to_thread`` (gspread is sync — see CLAUDE.md).
    * EXPONENTIAL BACKOFF with jitter between retry attempts (capped attempts,
      base/max delay) so a transient Sheets error is retried without a tight loop.
    * QUOTA-AWARE throttling: a minimum interval between writes smooths a spike of
      joins (the roadshow scenario: 50 joins in minutes) under the Sheets quotas
      (300 read/min/project, 300 write/min/project, 60 req/min/user).
    * RECONCILIATION on exhaustion: a write that fails every attempt is moved to an
      in-memory DEAD-LETTER list, logged at ERROR with a structured
      ``needs_reconciliation`` signal, AND (best-effort) the admin-owned
      ``schema.RECONCILE_STATUS_COLUMN`` cell is set to
      ``schema.RECONCILE_STATUS_VALUE`` for that Telegram ID — so the signal is
      visible both IN the sheet (when reachable) and OUT-OF-BAND (log + admin
      command ``/sheets_status``) when Sheets is down.

Durability tradeoff (DOCUMENTED, per ticket)
--------------------------------------------
The pending queue and dead-letter list are **in-memory only**. If the process
restarts, any not-yet-flushed writes are LOST. This is an ACCEPTED v1 tradeoff:

    * The bot runs single-instance; restarts are rare and operator-initiated.
    * Onboarding records are idempotent (keyed on Telegram ID) and re-derivable —
      a member can re-run ``/profile`` and the structured ``member_enqueued`` /
      ``needs_reconciliation`` logs name every affected Telegram ID for a manual
      backfill. No PII is required to reconcile (the log carries the ID, never the
      phone/plate).
    * A JSON-file spool would add durability but also disk I/O, serialization of
      PII to disk (a new PII-at-rest surface), and crash-consistency concerns —
      out of proportion for v1. It is noted as a future nice-to-have.

This module imports cleanly WITHOUT gspread/python-telegram-bot installed: it
depends only on the stdlib, :mod:`dfeng_bot.services.schema`, and (lazily, at call
time) the onboarding ``persist_member`` seam.

Run the inline self-tests::

    python3 -m dfeng_bot.services.write_queue
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional

from . import schema

logger = logging.getLogger("dfeng_bot")

# A persister takes (service, record) and returns an action string ("appended" /
# "updated"), matching onboarding.persist_member. Kept as a type alias so tests
# can inject fakes without importing the handlers package.
Persister = Callable[[Any, Mapping[str, str]], str]


# --- tunables ----------------------------------------------------------------
@dataclass(frozen=True)
class QueueConfig:
    """Retry / throttle tunables for :class:`WriteQueue`.

    Defaults are deliberately conservative for the Sheets quotas (see module
    docstring). ``min_write_interval`` is the floor between two writes leaving the
    worker; at the default 1.1s that caps sustained throughput near ~54 writes/min
    — comfortably under the 60 req/min/user and 300 write/min/project limits even
    accounting for the extra read (``find_row_by_telegram_id``) each upsert does.
    """

    enabled: bool = True
    max_attempts: int = 5
    base_delay: float = 1.0
    max_delay: float = 30.0
    min_write_interval: float = 1.1
    max_pending: int = 1000
    jitter: float = 0.1  # +/- fraction applied to each backoff delay


def backoff_delay(attempt: int, base: float, cap: float) -> float:
    """Return the (un-jittered) exponential backoff delay for *attempt* (1-based).

    Delay = ``base * 2**(attempt-1)``, clamped to ``cap``. Monotonic
    non-decreasing in ``attempt`` and never above ``cap`` — the property the
    acceptance criteria check.

    >>> backoff_delay(1, 1.0, 30.0)
    1.0
    >>> backoff_delay(2, 1.0, 30.0)
    2.0
    >>> backoff_delay(3, 1.0, 30.0)
    4.0
    >>> backoff_delay(10, 1.0, 30.0)  # clamped to the cap
    30.0
    >>> backoff_delay(1, 0.0, 30.0)
    0.0
    """

    if attempt < 1:
        attempt = 1
    raw = base * (2 ** (attempt - 1))
    return float(min(raw, cap))


def _jittered(delay: float, jitter: float) -> float:
    """Apply +/- *jitter* fraction to *delay*, floored at 0."""
    if jitter <= 0 or delay <= 0:
        return delay
    spread = delay * jitter
    return max(0.0, delay + random.uniform(-spread, spread))


# --- queue item --------------------------------------------------------------
@dataclass
class _Item:
    """A queued write: the record plus its retry bookkeeping (no PII in repr/log)."""

    record: dict[str, str]
    attempts: int = 0
    enqueued_at: float = field(default_factory=time.monotonic)

    @property
    def telegram_id(self) -> str:
        return str(self.record.get(schema.KEY_COLUMN, ""))

    @property
    def username(self) -> str:
        return str(self.record.get("Telegram username", ""))


@dataclass
class DeadLetter:
    """A permanently-failed write surfaced to admins (NEVER carries PII).

    Only the Telegram ID + public username + error class are retained — phone and
    plate (``schema.PII_COLUMNS``) are intentionally dropped here so the
    dead-letter view shown by ``/sheets_status`` / ``/reconcile`` can never expose
    personal data.
    """

    telegram_id: str
    username: str
    attempts: int
    error_type: str
    failed_at: float = field(default_factory=time.monotonic)


# --- the queue ---------------------------------------------------------------
class WriteQueue:
    """Bounded in-memory async write queue draining through a single worker.

    Lifecycle: construct -> :meth:`start` (spawns the worker) -> :meth:`enqueue`
    (from any coroutine) -> :meth:`stop` (drains then cancels). Safe to
    ``start``/``stop`` idempotently.
    """

    def __init__(
        self,
        service_factory: Callable[[], Any],
        persister: Persister,
        config: Optional[QueueConfig] = None,
        *,
        sleep: Callable[[float], "asyncio.Future"] = asyncio.sleep,
        run_blocking: Optional[Callable[..., "asyncio.Future"]] = None,
    ) -> None:
        """Build a queue.

        Args:
            service_factory: zero-arg callable returning a Sheets service (e.g.
                ``lambda: build_sheets_service(config)``). Called per drain so a
                recovered service/credentials are picked up.
            persister: the write seam, normally ``onboarding.persist_member``.
            config: retry/throttle tunables.
            sleep: injectable sleep (tests pass a no-op to avoid real waits).
            run_blocking: injectable ``asyncio.to_thread``-style runner (tests pass
                a synchronous shim). Defaults to ``asyncio.to_thread``.
        """

        self._service_factory = service_factory
        self._persister = persister
        self._cfg = config or QueueConfig()
        self._sleep = sleep
        self._run_blocking = run_blocking or asyncio.to_thread

        self._queue: "asyncio.Queue[_Item]" = asyncio.Queue(maxsize=self._cfg.max_pending)
        self._dead_letter: list[DeadLetter] = []
        self._worker: Optional[asyncio.Task] = None
        self._inflight: int = 0
        self._last_write_at: float = 0.0
        # Cumulative counters for observability.
        self._processed_ok = 0
        self._enqueued_total = 0
        self._dropped_full = 0

    # --- public API ---------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return self._cfg.enabled

    def enqueue(self, record: Mapping[str, str]) -> bool:
        """Park *record* for asynchronous persistence. Returns immediately.

        Returns True if queued, False if the bounded queue is full (the caller's
        flow still completes either way — a dropped item is logged and, on a full
        queue, the loss is treated like an exhausted write). Copies the record so
        later mutation of the caller's dict can't corrupt the queued write.
        """

        item = _Item(record=dict(record))
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            self._dropped_full += 1
            self._to_dead_letter(item, error_type="QueueFull", reachable_service=None)
            logger.error(
                "write_queue_full",
                extra={
                    "action": "write_queue_full",
                    "telegram_id": item.telegram_id,
                    "username": item.username or None,
                    "outcome": "needs_reconciliation",
                },
            )
            return False

        self._enqueued_total += 1
        logger.info(
            "member_enqueued",
            extra={
                "action": "member_enqueued",
                "telegram_id": item.telegram_id,
                "username": item.username or None,
                "pending": self._queue.qsize(),
                "outcome": "queued",
            },
        )
        return True

    def start(self) -> None:
        """Spawn the background drain worker (idempotent, no-op if running)."""
        if self._worker is not None and not self._worker.done():
            return
        self._worker = asyncio.ensure_future(self._run())
        logger.info("write_queue_started", extra={"action": "write_queue_started"})

    async def stop(self, *, drain: bool = True, timeout: float = 10.0) -> None:
        """Stop the worker, optionally draining the queue first.

        Args:
            drain: if True, wait (up to ``timeout``) for the pending queue to
                empty before cancelling so in-flight writes aren't lost on a clean
                shutdown.
            timeout: max seconds to wait for the drain.
        """

        if drain:
            try:
                await asyncio.wait_for(self._queue.join(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(
                    "write_queue_drain_timeout",
                    extra={"action": "write_queue_drain_timeout", "pending": self._queue.qsize()},
                )

        worker = self._worker
        self._worker = None
        if worker is not None and not worker.done():
            worker.cancel()
            try:
                await worker
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        logger.info("write_queue_stopped", extra={"action": "write_queue_stopped"})

    def stats(self) -> dict[str, Any]:
        """Return an observable snapshot of the queue state.

        Shape (stable for the admin command + tests)::

            {pending, inflight, dead_letter, processed_ok, enqueued_total,
             dropped_full, running}
        """

        return {
            "pending": self._queue.qsize(),
            "inflight": self._inflight,
            "dead_letter": len(self._dead_letter),
            "processed_ok": self._processed_ok,
            "enqueued_total": self._enqueued_total,
            "dropped_full": self._dropped_full,
            "running": self._worker is not None and not self._worker.done(),
        }

    def dead_letters(self) -> list[DeadLetter]:
        """Return a copy of the dead-letter list (PII-free, safe to surface)."""
        return list(self._dead_letter)

    # --- worker -------------------------------------------------------------
    async def _run(self) -> None:
        """Drain loop: pull an item, persist it with retries, repeat."""
        while True:
            item = await self._queue.get()
            try:
                await self._process(item)
            except asyncio.CancelledError:  # pragma: no cover - shutdown path
                self._queue.task_done()
                raise
            except Exception:  # noqa: BLE001 - a buggy item must not kill the worker
                logger.exception("write_queue_worker_error")
                self._queue.task_done()
            else:
                self._queue.task_done()

    async def _process(self, item: _Item) -> None:
        """Attempt one item with bounded exponential-backoff retries."""
        self._inflight += 1
        try:
            last_exc: Optional[BaseException] = None
            while item.attempts < self._cfg.max_attempts:
                item.attempts += 1
                await self._throttle()
                service = self._service_factory()
                try:
                    action = await self._run_blocking(self._persister, service, item.record)
                except asyncio.CancelledError:  # pragma: no cover
                    raise
                except Exception as exc:  # noqa: BLE001 - retry on any write error
                    last_exc = exc
                    logger.warning(
                        "member_persist_retry",
                        extra={
                            "action": "member_persist_retry",
                            "telegram_id": item.telegram_id,
                            "username": item.username or None,
                            "attempt": item.attempts,
                            "max_attempts": self._cfg.max_attempts,
                            "error_type": type(exc).__name__,
                            "outcome": "will_retry"
                            if item.attempts < self._cfg.max_attempts
                            else "exhausted",
                        },
                    )
                    if item.attempts < self._cfg.max_attempts:
                        delay = _jittered(
                            backoff_delay(item.attempts, self._cfg.base_delay, self._cfg.max_delay),
                            self._cfg.jitter,
                        )
                        await self._sleep(delay)
                    continue
                else:
                    self._last_write_at = time.monotonic()
                    self._processed_ok += 1
                    logger.info(
                        "member_persisted",
                        extra={
                            "action": "member_persisted",
                            "telegram_id": item.telegram_id,
                            "username": item.username or None,
                            "attempts": item.attempts,
                            "queued_action": action,
                            "outcome": "persisted",
                        },
                    )
                    return

            # Exhausted every attempt -> reconciliation.
            self._handle_exhausted(item, last_exc)
        finally:
            self._inflight -= 1

    async def _throttle(self) -> None:
        """Enforce the minimum interval between writes (quota smoothing)."""
        interval = self._cfg.min_write_interval
        if interval <= 0:
            return
        elapsed = time.monotonic() - self._last_write_at
        if elapsed < interval:
            await self._sleep(interval - elapsed)

    # --- reconciliation -----------------------------------------------------
    def _handle_exhausted(self, item: _Item, exc: Optional[BaseException]) -> None:
        """Move an exhausted item to dead-letter + emit the reconciliation signal.

        Three independent signals so reconciliation works even when Sheets is
        down: (1) the in-memory dead-letter list, (2) a structured ERROR log, and
        (3) a BEST-EFFORT admin ``Status`` column write.
        """

        error_type = type(exc).__name__ if exc is not None else "unknown"

        # (3) best-effort Status column flag — only if a fresh service is reachable.
        flagged = self._best_effort_flag_status(item, error_type)

        # (1) dead-letter (PII-free) + (2) structured ERROR log.
        self._to_dead_letter(item, error_type=error_type, reachable_service=flagged)
        logger.error(
            "member_persist_exhausted",
            extra={
                "action": "member_persist_exhausted",
                "telegram_id": item.telegram_id,
                "username": item.username or None,
                "attempts": item.attempts,
                "error_type": error_type,
                "status_flagged": flagged,
                "outcome": "needs_reconciliation",
            },
        )

    def _best_effort_flag_status(self, item: _Item, error_type: str) -> bool:
        """Try to set the admin ``Status`` cell to NEEDS_RECONCILIATION. Never raises.

        Returns True if the flag was written, False if Sheets was unreachable (the
        common case when the original write just exhausted) or the row/feature is
        unavailable. The dead-letter list + ERROR log are the durable signals; this
        is a convenience for admins who watch the sheet.
        """

        try:
            service = self._service_factory()
            flagger = getattr(service, "flag_needs_reconciliation", None)
            if flagger is None:
                return False
            tid = int(item.telegram_id)
            return bool(flagger(tid))
        except Exception:  # noqa: BLE001 - flagging is best-effort; Sheets may be down
            return False

    def _to_dead_letter(
        self, item: _Item, *, error_type: str, reachable_service: Optional[bool]
    ) -> None:
        self._dead_letter.append(
            DeadLetter(
                telegram_id=item.telegram_id,
                username=item.username,
                attempts=item.attempts,
                error_type=error_type,
            )
        )


# --- application wiring -------------------------------------------------------
# Key under which the shared WriteQueue is stored in ``application.bot_data``.
WRITE_QUEUE_KEY = "write_queue"


def build_write_queue(config: Any) -> WriteQueue:
    """Build a :class:`WriteQueue` from a :class:`dfeng_bot.config.Config`.

    Wires the queue to the real Sheets service (rebuilt per drain so recovered
    credentials are picked up) and the VOL-205 ``persist_member`` seam. Imports of
    the handlers/sheets packages are LOCAL so this factory — and the queue module —
    stay import-clean without python-telegram-bot or gspread installed.
    """

    from ..handlers.onboarding import persist_member
    from .sheets import build_sheets_service

    wq = config.write_queue
    return WriteQueue(
        service_factory=lambda: build_sheets_service(config),
        persister=persist_member,
        config=QueueConfig(
            enabled=wq.enabled,
            max_attempts=wq.max_attempts,
            base_delay=wq.base_delay,
            max_delay=wq.max_delay,
            min_write_interval=wq.min_write_interval,
            max_pending=wq.max_pending,
        ),
    )


# --- inline self-tests -------------------------------------------------------
def _selftest() -> None:  # pragma: no cover - manual/dev entry point
    import doctest

    failures, _ = doctest.testmod(verbose=False)
    assert failures == 0, f"{failures} doctest failure(s)"

    # Backoff schedule is non-decreasing and capped.
    seq = [backoff_delay(a, 1.0, 30.0) for a in range(1, 12)]
    assert seq[0] == 1.0
    assert all(b >= a for a, b in zip(seq, seq[1:])), seq
    assert max(seq) <= 30.0 and seq[-1] == 30.0, seq

    # Fast, deterministic harness: no real sleeping, synchronous "blocking" call.
    async def _noop_sleep(_delay: float) -> None:
        return None

    async def _sync_run(fn, *args):
        return fn(*args)

    rec = {
        schema.KEY_COLUMN: "42",
        "Telegram username": "alice",
        "Optional phone": "SECRET",  # must NEVER reach a dead-letter / log
        "Optional plate": "SECRET",
    }

    fast_cfg = QueueConfig(max_attempts=3, base_delay=0.0, min_write_interval=0.0, jitter=0.0)

    async def _case_fails_twice_then_succeeds() -> None:
        calls = {"n": 0}

        def persister(_service: Any, _record: Mapping[str, str]) -> str:
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("Sheets 503")
            return "appended"

        q = WriteQueue(
            service_factory=lambda: object(),
            persister=persister,
            config=fast_cfg,
            sleep=_noop_sleep,
            run_blocking=_sync_run,
        )
        q.start()
        assert q.enqueue(rec) is True
        await asyncio.wait_for(q._queue.join(), timeout=2.0)
        await q.stop(drain=False)
        assert calls["n"] == 3, calls
        s = q.stats()
        assert s["processed_ok"] == 1, s
        assert s["dead_letter"] == 0, s
        assert s["pending"] == 0, s

    async def _case_always_fails_dead_letters() -> None:
        def persister(_service: Any, _record: Mapping[str, str]) -> str:
            raise RuntimeError("Sheets down")

        q = WriteQueue(
            service_factory=lambda: object(),
            persister=persister,
            config=fast_cfg,
            sleep=_noop_sleep,
            run_blocking=_sync_run,
        )
        q.start()
        q.enqueue(rec)
        await asyncio.wait_for(q._queue.join(), timeout=2.0)
        await q.stop(drain=False)
        dls = q.dead_letters()
        assert len(dls) == 1, dls
        dl = dls[0]
        assert dl.telegram_id == "42"
        assert dl.username == "alice"
        assert dl.attempts == 3, dl
        # PII must never appear in the dead-letter record.
        blob = f"{dl.telegram_id}{dl.username}{dl.error_type}{dl.attempts}"
        assert "SECRET" not in blob

    async def _case_best_effort_status_flag() -> None:
        flagged = {"tids": []}

        class _RecoverableService:
            def flag_needs_reconciliation(self, tid: int) -> bool:
                flagged["tids"].append(tid)
                return True

        def persister(_service: Any, _record: Mapping[str, str]) -> str:
            raise RuntimeError("transient")

        q = WriteQueue(
            service_factory=_RecoverableService,
            persister=persister,
            config=QueueConfig(max_attempts=2, base_delay=0.0, min_write_interval=0.0, jitter=0.0),
            sleep=_noop_sleep,
            run_blocking=_sync_run,
        )
        q.start()
        q.enqueue(rec)
        await asyncio.wait_for(q._queue.join(), timeout=2.0)
        await q.stop(drain=False)
        assert flagged["tids"] == [42], flagged
        assert q.stats()["dead_letter"] == 1

    async def _case_stats_shape() -> None:
        q = WriteQueue(
            service_factory=lambda: object(),
            persister=lambda s, r: "appended",
            config=fast_cfg,
            sleep=_noop_sleep,
            run_blocking=_sync_run,
        )
        s = q.stats()
        assert set(s) == {
            "pending",
            "inflight",
            "dead_letter",
            "processed_ok",
            "enqueued_total",
            "dropped_full",
            "running",
        }, set(s)
        assert s["running"] is False  # not started yet

    async def _case_bounded_queue_drops_to_dead_letter() -> None:
        # A full queue (never drained) sends overflow straight to dead-letter so
        # the loss is still an admin-visible reconciliation signal.
        q = WriteQueue(
            service_factory=lambda: object(),
            persister=lambda s, r: "appended",
            config=QueueConfig(max_pending=1),
            sleep=_noop_sleep,
            run_blocking=_sync_run,
        )
        assert q.enqueue(rec) is True
        assert q.enqueue(rec) is False  # queue full
        assert q.stats()["dead_letter"] == 1
        assert q.stats()["dropped_full"] == 1

    async def _main() -> None:
        await _case_fails_twice_then_succeeds()
        await _case_always_fails_dead_letters()
        await _case_best_effort_status_flag()
        await _case_stats_shape()
        await _case_bounded_queue_drops_to_dead_letter()

    asyncio.run(_main())
    print("write_queue self-tests passed")


if __name__ == "__main__":  # pragma: no cover
    _selftest()
