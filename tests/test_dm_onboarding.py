"""Deep-link DM onboarding (Option A) — gating + payload mapping.

Covers: /start payload -> entry source; the feature gate (off -> no-op); the
private-chat requirement; and that a private /start with the flag on stashes the
entry source + DM flag and starts the flow.
"""

import unittest

from _config import make_config
from _fakes import FakeChat, FakeContext, FakeMessage, FakeUpdate, FakeUser, run

from dfeng_bot.handlers import dm_onboarding as d
from dfeng_bot.handlers.membership import ENTRY_SOURCE_KEY


def _private_update(user_id=7):
    u = FakeUser(user_id, "tester")
    return FakeUpdate(message=FakeMessage(from_user=u), user=u,
                      chat=FakeChat(user_id, "private"))


class TestPayloadMapping(unittest.TestCase):
    def test_known_and_unknown_tokens(self):
        self.assertEqual(d.source_for_payload("showroom"), "showroom QR")
        self.assertEqual(d.source_for_payload("roadshow"), "roadshow QR")
        self.assertEqual(d.source_for_payload("EVENT"), "event QR")  # case-insensitive
        self.assertEqual(d.source_for_payload("linktree"), "Linktree")
        self.assertEqual(d.source_for_payload(""), "salesperson")     # no payload
        self.assertEqual(d.source_for_payload("garbage"), "salesperson")


class TestGating(unittest.TestCase):
    def test_feature_off_is_noop(self):
        ctx = FakeContext(make_config(features={"dm_onboarding": False}), args=["showroom"])
        self.assertFalse(run(d.maybe_start_dm_onboarding(_private_update(), ctx)))
        self.assertNotIn(d.DM_ONBOARDING_FLAG, ctx.user_data)

    def test_group_chat_is_noop_even_when_on(self):
        ctx = FakeContext(make_config(features={"dm_onboarding": True}), args=["showroom"])
        u = FakeUser(7, "t")
        upd = FakeUpdate(message=FakeMessage(from_user=u), user=u,
                         chat=FakeChat(-100, "supergroup"))
        self.assertFalse(run(d.maybe_start_dm_onboarding(upd, ctx)))

    def test_private_on_starts_and_stashes_source(self):
        ctx = FakeContext(make_config(features={"dm_onboarding": True}), args=["showroom"])
        upd = _private_update()
        self.assertTrue(run(d.maybe_start_dm_onboarding(upd, ctx)))
        self.assertEqual(ctx.user_data[ENTRY_SOURCE_KEY], "showroom QR")
        self.assertTrue(ctx.user_data[d.DM_ONBOARDING_FLAG])


if __name__ == "__main__":
    unittest.main()
