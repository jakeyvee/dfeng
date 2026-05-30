"""VOL-214 scenario 10: new-user link blocked before trust, allowed after.

Covers message_has_link (text + entity detection) and is_trusted transitions, plus
the TrustStore progression (join -> clean messages cross threshold; join-age path;
admin approve) that drives the not-trusted -> trusted transition.
"""

import unittest

from dfeng_bot.handlers.link_restrictions import (
    MemberState,
    TrustConfig,
    TrustStore,
    is_trusted,
    message_has_link,
)


class _E:
    """Stand-in for telegram.MessageEntity."""

    def __init__(self, type_, url=None):
        self.type = type_
        self.url = url


class LinkDetectionTest(unittest.TestCase):
    def test_detects_links_and_mentions(self):
        self.assertTrue(message_has_link("plain http://example.com now", None))
        self.assertTrue(message_has_link("come to t.me/dongfeng", None))
        self.assertTrue(message_has_link("hey @some_channel", None))
        self.assertTrue(message_has_link("hidden", [_E("text_link", "http://x.io")]))
        self.assertTrue(message_has_link("entity", [_E("url")]))

    def test_clean_text_has_no_link(self):
        self.assertFalse(message_has_link("no link at all here", None))
        self.assertFalse(message_has_link("plain text", [_E("bold")]))


class TrustTransitionTest(unittest.TestCase):
    def setUp(self):
        self.cfg = TrustConfig(min_age_seconds=86400, min_messages=3)

    def test_fresh_member_not_trusted_then_trusted_by_age(self):
        fresh = MemberState(joined_at=1000.0, clean_message_count=0)
        self.assertFalse(is_trusted(fresh, now=1000.0, config=self.cfg))
        self.assertTrue(is_trusted(fresh, now=1000.0 + 86400, config=self.cfg))

    def test_clean_messages_earn_trust(self):
        chatty = MemberState(joined_at=2000.0, clean_message_count=3)
        self.assertTrue(is_trusted(chatty, now=2000.0, config=self.cfg))

    def test_qualified_member_trusted(self):
        s = MemberState(joined_at=3000.0)
        self.assertTrue(is_trusted(s, now=3000.0, config=self.cfg, qualified=True))

    def test_admin_approved_trusted(self):
        s = MemberState(joined_at=4000.0, admin_approved=True)
        self.assertTrue(is_trusted(s, now=4000.0, config=self.cfg))

    def test_unknown_member_trusted(self):
        # Never block someone with no observed join record.
        self.assertTrue(is_trusted(None, now=0.0, config=self.cfg))


class TrustStoreProgressionTest(unittest.TestCase):
    """Scenario 10 end-to-end at the store level: blocked -> allowed transition."""

    def setUp(self):
        self.cfg = TrustConfig(min_age_seconds=86400, min_messages=3)
        self.store = TrustStore()

    def test_join_then_clean_messages_cross_threshold(self):
        self.store.record_join(99, now=0.0)
        # Just joined, 0 clean messages -> NOT trusted -> link blocked.
        self.assertFalse(is_trusted(self.store.get(99), now=1.0, config=self.cfg))
        self.store.note_clean_message(99, now=1.0)
        self.store.note_clean_message(99, now=2.0)
        self.assertFalse(is_trusted(self.store.get(99), now=3.0, config=self.cfg))  # 2
        self.store.note_clean_message(99, now=3.0)
        # 3 clean messages -> trusted -> links now allowed.
        self.assertTrue(is_trusted(self.store.get(99), now=4.0, config=self.cfg))

    def test_admin_trust_immediately_allows_links(self):
        self.store.record_join(7, now=0.0)
        self.assertFalse(is_trusted(self.store.get(7), now=1.0, config=self.cfg))
        self.store.approve(7, now=1.0)
        self.assertTrue(is_trusted(self.store.get(7), now=2.0, config=self.cfg))

    def test_store_is_bounded(self):
        small = TrustStore(max_users=2)
        small.record_join(1, now=0.0)
        small.record_join(2, now=1.0)
        small.record_join(3, now=2.0)  # evicts user 1 (oldest touch)
        self.assertIsNone(small.get(1))
        self.assertIsNotNone(small.get(2))
        self.assertIsNotNone(small.get(3))


if __name__ == "__main__":
    unittest.main()
