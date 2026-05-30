"""VOL-214 scenario 6: a temporary Sheets write failure never blocks onboarding.

The WriteQueue parks records and drains them on a background worker with bounded
exponential backoff + dead-lettering. We drive it with injected no-op sleep and a
synchronous run_blocking shim so tests are fast and deterministic.

PII hygiene: the queued record carries OBVIOUSLY-FAKE phone/plate; we assert they
NEVER appear in any dead-letter record (which only retains id/username/error).
"""

import asyncio
import unittest

from dfeng_bot.services import schema
from dfeng_bot.services.write_queue import QueueConfig, WriteQueue, backoff_delay

from _fakes import FAKE_PHONE, FAKE_PLATE


def _record(tid="42", username="alice"):
    return {
        schema.KEY_COLUMN: tid,
        "Telegram username": username,
        "Tag": "BOX Owner",
        "Optional phone": FAKE_PHONE,
        "Optional plate": FAKE_PLATE,
        "Consent timestamp": "2026-05-31T00:00:00+00:00",
        "Entry source": "showroom QR",
        "Joined timestamp": "2026-05-30T00:00:00+00:00",
    }


async def _noop_sleep(_delay):
    return None


async def _sync_run(fn, *args):
    return fn(*args)


FAST_CFG = QueueConfig(max_attempts=3, base_delay=0.0, min_write_interval=0.0, jitter=0.0)


class BackoffTest(unittest.TestCase):
    def test_backoff_is_monotonic_and_capped(self):
        seq = [backoff_delay(a, 1.0, 30.0) for a in range(1, 12)]
        self.assertEqual(seq[0], 1.0)
        self.assertTrue(all(b >= a for a, b in zip(seq, seq[1:])))
        self.assertEqual(max(seq), 30.0)
        self.assertEqual(seq[-1], 30.0)


class WriteQueueResilienceTest(unittest.TestCase):
    def test_transient_failure_then_success_persists(self):
        async def scenario():
            calls = {"n": 0}

            def persister(_service, _record):
                calls["n"] += 1
                if calls["n"] < 3:
                    raise RuntimeError("Sheets 503 (transient)")
                return "appended"

            q = WriteQueue(
                service_factory=lambda: object(),
                persister=persister,
                config=FAST_CFG,
                sleep=_noop_sleep,
                run_blocking=_sync_run,
            )
            q.start()
            self.assertTrue(q.enqueue(_record()))
            await asyncio.wait_for(q._queue.join(), timeout=2.0)
            await q.stop(drain=False)
            stats = q.stats()
            self.assertEqual(calls["n"], 3)  # retried twice, succeeded on 3rd
            self.assertEqual(stats["processed_ok"], 1)
            self.assertEqual(stats["dead_letter"], 0)
            self.assertEqual(stats["pending"], 0)

        asyncio.run(scenario())

    def test_persistent_failure_dead_letters_without_pii(self):
        async def scenario():
            def persister(_service, _record):
                raise RuntimeError("Sheets down (permanent)")

            q = WriteQueue(
                service_factory=lambda: object(),
                persister=persister,
                config=FAST_CFG,
                sleep=_noop_sleep,
                run_blocking=_sync_run,
            )
            q.start()
            q.enqueue(_record())
            await asyncio.wait_for(q._queue.join(), timeout=2.0)
            await q.stop(drain=False)

            dls = q.dead_letters()
            self.assertEqual(len(dls), 1)
            dl = dls[0]
            self.assertEqual(dl.telegram_id, "42")
            self.assertEqual(dl.username, "alice")
            self.assertEqual(dl.attempts, 3)
            # PII MUST NOT appear anywhere in the dead-letter record.
            blob = f"{dl.telegram_id}|{dl.username}|{dl.error_type}|{dl.attempts}"
            self.assertNotIn(FAKE_PHONE, blob)
            self.assertNotIn(FAKE_PLATE, blob)
            self.assertNotIn("Optional", blob)

        asyncio.run(scenario())

    def test_onboarding_completes_even_if_queue_full(self):
        # A full bounded queue routes overflow to dead-letter (admin-visible) but
        # enqueue() returns immediately — onboarding never blocks.
        async def scenario():
            q = WriteQueue(
                service_factory=lambda: object(),
                persister=lambda s, r: "appended",
                config=QueueConfig(max_pending=1),
                sleep=_noop_sleep,
                run_blocking=_sync_run,
            )
            self.assertTrue(q.enqueue(_record()))
            self.assertFalse(q.enqueue(_record()))  # queue full
            self.assertEqual(q.stats()["dropped_full"], 1)
            self.assertEqual(q.stats()["dead_letter"], 1)

        asyncio.run(scenario())

    def test_stats_shape_is_stable(self):
        q = WriteQueue(
            service_factory=lambda: object(),
            persister=lambda s, r: "appended",
            config=FAST_CFG,
            sleep=_noop_sleep,
            run_blocking=_sync_run,
        )
        self.assertEqual(
            set(q.stats()),
            {
                "pending",
                "inflight",
                "dead_letter",
                "processed_ok",
                "enqueued_total",
                "dropped_full",
                "running",
            },
        )


if __name__ == "__main__":
    unittest.main()
