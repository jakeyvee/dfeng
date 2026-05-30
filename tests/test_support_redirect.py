"""VOL-214 scenarios 7-8: support-keyword redirect outside Support; no loop inside.

Covers:
  * find_support_keyword (pure detection, case/punctuation/word-boundary).
  * the verbatim nudge copy == the ticket string.
  * maybe_redirect nudges in a NON-support topic.
  * maybe_redirect does NOT nudge when the message is already in the Support
    topic (the loop guard).
"""

import unittest

from dfeng_bot.handlers import support_redirect

from _config import make_config
from _fakes import FakeContext, FakeMessage, FakeUpdate, FakeUser, run

SUPPORT_TOPIC = 50


class SupportKeywordDetectionTest(unittest.TestCase):
    def test_detects_each_required_keyword(self):
        samples = {
            "I have a charging issue today": True,
            "battery issue here": True,
            "When is servicing due?": True,
            "needs a Repair please": True,
            "is this under WARRANTY?": True,
            "big problem!": True,
            "Issue.": True,
        }
        for text, expect in samples.items():
            with self.subTest(text=text):
                self.assertEqual(
                    support_redirect.find_support_keyword(text) is not None, expect
                )

    def test_word_boundary_avoids_false_positives(self):
        self.assertIsNone(support_redirect.find_support_keyword("Just a tissue here"))
        self.assertIsNone(support_redirect.find_support_keyword("Loving my BOX!"))
        self.assertIsNone(support_redirect.find_support_keyword(""))
        self.assertIsNone(support_redirect.find_support_keyword(None))

    def test_verbatim_copy_matches_ticket(self):
        self.assertEqual(
            support_redirect.SUPPORT_REDIRECT_MESSAGE,
            "Hey! Let's get this sorted properly 🧡 Please continue this in our "
            "Support & Assistance section so our team can assist directly.",
        )


class SupportRedirectBehaviourTest(unittest.TestCase):
    def setUp(self):
        # Avoid cross-test cooldown contamination from the per-process map.
        support_redirect._recent_nudges.clear()
        self.config = make_config(support_topic=SUPPORT_TOPIC)

    def _update(self, text, thread_id, user_id=900):
        user = FakeUser(user_id, username="member")
        msg = FakeMessage(text=text, thread_id=thread_id, from_user=user)
        return FakeUpdate(message=msg, user=user)

    def test_redirect_fires_outside_support_topic(self):
        ctx = FakeContext(self.config)
        upd = self._update("My car has a battery issue", thread_id=20)  # General
        nudged = run(support_redirect.maybe_redirect(upd, ctx))
        self.assertTrue(nudged)
        # The exact nudge copy was sent in-thread.
        self.assertEqual(len(upd.effective_message.replies), 1)
        self.assertEqual(
            upd.effective_message.replies[0]["text"],
            support_redirect.SUPPORT_REDIRECT_MESSAGE,
        )

    def test_no_loop_inside_support_topic(self):
        ctx = FakeContext(self.config)
        upd = self._update("I still have a charging issue", thread_id=SUPPORT_TOPIC)
        nudged = run(support_redirect.maybe_redirect(upd, ctx))
        self.assertFalse(nudged)  # already in Support -> no nudge -> no loop
        self.assertEqual(len(upd.effective_message.replies), 0)

    def test_no_redirect_for_non_support_chatter(self):
        ctx = FakeContext(self.config)
        upd = self._update("Loving my new VIGO on weekend trips!", thread_id=20)
        nudged = run(support_redirect.maybe_redirect(upd, ctx))
        self.assertFalse(nudged)

    def test_cooldown_suppresses_repeat_nudge(self):
        ctx = FakeContext(self.config)
        upd1 = self._update("warranty?", thread_id=20, user_id=901)
        self.assertTrue(run(support_redirect.maybe_redirect(upd1, ctx)))
        upd2 = self._update("warranty again?", thread_id=20, user_id=901)
        self.assertFalse(run(support_redirect.maybe_redirect(upd2, ctx)))

    def test_disabled_feature_does_not_redirect(self):
        cfg = make_config(support_topic=SUPPORT_TOPIC, features={"support_redirect": False})
        ctx = FakeContext(cfg)
        upd = self._update("battery issue", thread_id=20, user_id=902)
        self.assertFalse(run(support_redirect.maybe_redirect(upd, ctx)))


if __name__ == "__main__":
    unittest.main()
