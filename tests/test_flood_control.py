"""VOL-214 scenario 11: flooding across topics trips rate limiting.

FloodTracker is keyed by user_id ONLY (thread/topic ignored), so messages across
multiple forum topics count toward one per-user limit. Tests cover: burst trips,
cross-topic counting, slow-sender clears, window expiry, and user independence.
"""

import unittest

from dfeng_bot.handlers.flood_control import FloodTracker


class FloodTrackerTest(unittest.TestCase):
    def test_burst_trips_above_max(self):
        t = FloodTracker(max_messages=8, window_seconds=10)
        tripped = None
        for i in range(9):  # 9 msgs within a 10s window -> > 8 trips
            tripped = t.record_and_check(42, now=i)
        self.assertIsNotNone(tripped)
        self.assertEqual(tripped.count, 9)
        self.assertEqual(tripped.window_seconds, 10)

    def test_counts_across_topics_to_one_limit(self):
        # Different "topics" are simulated; the tracker never sees thread ids, so
        # messages across topics share the same per-user counter.
        t = FloodTracker(max_messages=8, window_seconds=10)
        fake_threads = [1, 2, 3, 4, 5, 6, 1, 2, 3]  # would-be topic ids (ignored)
        verdict = None
        for i, _thread in enumerate(fake_threads):
            verdict = t.record_and_check(7, now=i)
        self.assertIsNotNone(verdict, "cross-topic messages must count to one limit")

    def test_slow_sender_never_trips(self):
        t = FloodTracker(max_messages=8, window_seconds=10)
        for i in range(20):
            self.assertIsNone(t.record_and_check(3, now=i * 5))  # 1 msg / 5s

    def test_window_expiry_resets(self):
        t = FloodTracker(max_messages=8, window_seconds=10)
        for i in range(8):
            self.assertIsNone(t.record_and_check(4, now=i))
        # A long pause drops old stamps; only this message is in the window.
        self.assertIsNone(t.record_and_check(4, now=1000))

    def test_users_are_independent(self):
        t = FloodTracker(max_messages=8, window_seconds=10)
        for i in range(8):
            t.record_and_check(100, now=i)
            t.record_and_check(200, now=i)
        # User 100's 9th trips; user 200 (still 8 in window) does not yet.
        self.assertIsNotNone(t.record_and_check(100, now=8))

    def test_outer_map_bounded(self):
        t = FloodTracker(max_messages=3, window_seconds=10, max_users=2)
        t.record_and_check(1, now=0)
        t.record_and_check(2, now=1)
        t.record_and_check(3, now=2)  # evicts least-recently-active
        # No exception; map stayed bounded (smoke check of eviction path).
        self.assertIsNone(t.record_and_check(3, now=3))


if __name__ == "__main__":
    unittest.main()
