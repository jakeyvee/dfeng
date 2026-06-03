"""Hybrid DM PII capture + required classification (no skipping).

Covers:
  * Owner/Prospect and model keyboards have NO Skip button (classification required).
  * DM mode posts a benefit-led offer with a private deep-link button and does
    NOT show the PDPA notice / collect PII in the public group.
  * In-group mode still shows the PDPA notice.
  * start_dm_pii_capture (the /start profile handoff) shows the PDPA notice and
    asks for phone privately.
"""

import unittest

from _config import make_config
from _fakes import FakeChat, FakeContext, FakeMessage, FakeUpdate, FakeUser, run

from dfeng_bot import policy
from dfeng_bot.handlers import onboarding, qualification


def _labels(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


class TestNoSkip(unittest.TestCase):
    def test_role_keyboard_has_no_skip(self):
        self.assertEqual(set(_labels(qualification._role_keyboard(1))), {"Owner", "Prospect"})

    def test_model_keyboard_has_no_skip(self):
        self.assertEqual(set(_labels(qualification._model_keyboard(1))), {"BOX", "007", "VIGO"})


def _group_update(uid=7):
    u = FakeUser(uid, "tester")
    msg = FakeMessage(from_user=u)
    return msg, FakeUpdate(message=msg, user=u, chat=FakeChat(-100, "supergroup"))


class TestProfileOffer(unittest.TestCase):
    def test_dm_mode_offers_private_button_without_public_pdpa(self):
        cfg = make_config(features={"dm_pii_capture": True}, bot_username="DongfengSGBot")
        msg, upd = _group_update()
        ctx = FakeContext(cfg, user_data={qualification.TAG_KEY: "BOX Owner"})
        run(onboarding.start_profile_capture(upd, ctx))
        texts = [r["text"] for r in msg.replies]
        # Benefit-led DM offer was posted...
        self.assertTrue(any("Share your contact number" in t for t in texts))
        # ...with an inline keyboard (the deep-link button)...
        self.assertTrue(any(r["kwargs"].get("reply_markup") for r in msg.replies))
        # ...and the PDPA notice was NOT shown in the public group.
        self.assertFalse(any(policy.PDPA_CONSENT_NOTICE in t for t in texts))

    def test_in_group_mode_shows_pdpa(self):
        cfg = make_config(features={"dm_pii_capture": False})
        msg, upd = _group_update()
        ctx = FakeContext(cfg, user_data={qualification.TAG_KEY: "Prospect"})
        run(onboarding.start_profile_capture(upd, ctx))
        texts = [r["text"] for r in msg.replies]
        self.assertTrue(any(policy.PDPA_CONSENT_NOTICE in t for t in texts))


class TestDmCaptureEntry(unittest.TestCase):
    def test_start_dm_pii_capture_shows_pdpa_then_phone(self):
        cfg = make_config(features={"dm_pii_capture": True}, bot_username="DongfengSGBot")
        u = FakeUser(7, "tester")
        msg = FakeMessage(from_user=u)
        upd = FakeUpdate(message=msg, user=u, chat=FakeChat(7, "private"))
        ctx = FakeContext(cfg)
        run(onboarding.start_dm_pii_capture(upd, ctx))
        texts = [r["text"] for r in msg.replies]
        self.assertTrue(any(policy.PDPA_CONSENT_NOTICE in t for t in texts))
        self.assertEqual(onboarding._get_state(ctx), onboarding.STATE_AWAITING_PHONE)


if __name__ == "__main__":
    unittest.main()
