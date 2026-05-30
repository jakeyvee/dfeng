"""VOL-214 scenario 9: crypto/ad/suspicious-link spam removed; legit msg not flagged.

Pure detection layer (classify_spam + note_and_check_repeat). No Telegram I/O.
"""

import unittest

from dfeng_bot.handlers import antispam
from dfeng_bot.handlers.antispam import (
    CATEGORY_AD,
    CATEGORY_CRYPTO,
    CATEGORY_LINK,
    CATEGORY_REPETITION,
    SpamRules,
    classify_spam,
    note_and_check_repeat,
    reset_repeat_memory,
)


class SpamClassificationTest(unittest.TestCase):
    def setUp(self):
        self.rules = SpamRules()

    def test_crypto_promos_flagged(self):
        for text in (
            "Join the USDT giveaway, free crypto airdrop 100x!",
            "Pre-sale live, send ETH to double your money",
            "New memecoin to the moon, guaranteed returns",
        ):
            v = classify_spam(text, rules=self.rules)
            self.assertIsNotNone(v, text)
            self.assertEqual(v.category, CATEGORY_CRYPTO, text)

    def test_external_ads_flagged(self):
        for text in (
            "DM me for a promo code",
            "Join my channel for deals",
            "WhatsApp + me to earn $$$",
        ):
            v = classify_spam(text, rules=self.rules)
            self.assertIsNotNone(v, text)
            self.assertEqual(v.category, CATEGORY_AD, text)

    def test_suspicious_links_flagged(self):
        for text in (
            "check http://bit.ly/win now",
            "free stuff at https://claim-reward.xyz",
            "join t.me/some_other_group",
        ):
            v = classify_spam(text, rules=self.rules)
            self.assertIsNotNone(v, text)
            self.assertEqual(v.category, CATEGORY_LINK, text)

    def test_legit_dongfeng_chatter_not_flagged(self):
        for text in (
            "Loving my BOX on weekend trips!",
            "Anyone going to the roadshow this weekend?",
            "The new EV charging at the showroom is great",
            "Just booked a test drive, excited!",
        ):
            self.assertIsNone(classify_spam(text, rules=self.rules), text)

    def test_allowlist_exempts_community_domain(self):
        allowed = SpamRules(allowed_domains=["dongfeng.com"])
        self.assertIsNone(classify_spam("see https://dongfeng.com/box", rules=allowed))

    def test_repetition_trips_after_threshold(self):
        reset_repeat_memory()
        rep = SpamRules(repeat_count=3, repeat_window_seconds=60)
        self.assertIsNone(note_and_check_repeat(7, "buy now buy now", rep, now=0))
        self.assertIsNone(note_and_check_repeat(7, "buy now  buy now", rep, now=10))
        third = note_and_check_repeat(7, "BUY NOW buy now", rep, now=20)
        self.assertIsNotNone(third)
        self.assertEqual(third.category, CATEGORY_REPETITION)

    def test_repetition_does_not_trip_outside_window(self):
        reset_repeat_memory()
        rep = SpamRules(repeat_count=3, repeat_window_seconds=60)
        self.assertIsNone(note_and_check_repeat(8, "hello", rep, now=0))
        self.assertIsNone(note_and_check_repeat(8, "hello", rep, now=200))


if __name__ == "__main__":
    unittest.main()
