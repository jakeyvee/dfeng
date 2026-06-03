"""Issue 2 fix: the user's typed phone/plate message is deleted from the topic.

Capture happens in a public topic; the bot must remove the PII-bearing message
immediately after reading it. Verifies the message is deleted while the value is
still captured into user_data.
"""

import unittest

from _config import make_config
from _fakes import FAKE_PHONE, FAKE_PLATE, FakeContext, FakeMessage, FakeUpdate, FakeUser, run

from dfeng_bot.handlers import onboarding


class TestPiiAutoDelete(unittest.TestCase):
    def _typed(self, text):
        u = FakeUser(5, "tester")
        msg = FakeMessage(text=text, from_user=u)
        return msg, FakeUpdate(message=msg, user=u), FakeContext(make_config())

    def test_phone_message_deleted_but_value_kept(self):
        msg, upd, ctx = self._typed(FAKE_PHONE)
        onboarding._set_state(ctx, onboarding.STATE_AWAITING_PHONE)
        consumed = run(onboarding.advance(upd, ctx))
        self.assertTrue(consumed)
        self.assertTrue(msg.deleted)  # PII message removed from the topic
        self.assertEqual(ctx.user_data[onboarding.PHONE_KEY], FAKE_PHONE)

    def test_plate_message_deleted(self):
        # The plate step finishes onboarding (persist clears PII from user_data,
        # which is correct hygiene), so we only assert the message was removed.
        msg, upd, ctx = self._typed(FAKE_PLATE)
        onboarding._set_state(ctx, onboarding.STATE_AWAITING_PLATE)
        consumed = run(onboarding.advance(upd, ctx))
        self.assertTrue(consumed)
        self.assertTrue(msg.deleted)
        # PII must not linger in process memory after persistence.
        self.assertNotIn(onboarding.PLATE_KEY, ctx.user_data)

    def test_non_capture_state_does_not_delete(self):
        # A normal chat message (no capture in progress) is never touched.
        msg, upd, ctx = self._typed("Loving my BOX!")
        # no state set -> advance returns False, message untouched
        consumed = run(onboarding.advance(upd, ctx))
        self.assertFalse(consumed)
        self.assertFalse(msg.deleted)


if __name__ == "__main__":
    unittest.main()
