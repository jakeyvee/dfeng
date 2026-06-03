"""Buttons are locked to the user the question was posted for.

A tap from a DIFFERENT user is ignored (no tag assigned, no state change); the
intended user's tap is processed. Also checks the keyboards embed the uid.
"""

import unittest

from _config import make_config
from _fakes import FakeCallbackQuery, FakeContext, FakeMessage, FakeUpdate, FakeUser, run

from dfeng_bot.handlers import qualification


def _callback_datas(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


class TestKeyboardEmbedsUid(unittest.TestCase):
    def test_role_keyboard_locks_to_uid(self):
        datas = _callback_datas(qualification._role_keyboard(42))
        self.assertTrue(all(d.endswith(":42") for d in datas), datas)

    def test_model_keyboard_locks_to_uid(self):
        datas = _callback_datas(qualification._model_keyboard(42))
        self.assertTrue(all(d.endswith(":42") for d in datas), datas)


def _qual_cb_update(data, tapper_id):
    tapper = FakeUser(tapper_id, "tapper")
    q = FakeCallbackQuery(data=data, message=FakeMessage(), from_user=tapper)
    return FakeUpdate(callback_query=q, user=tapper)


class TestButtonLock(unittest.TestCase):
    def test_other_user_tap_is_ignored(self):
        # Question posted for user 100; user 200 taps "Owner".
        ctx = FakeContext(make_config())
        upd = _qual_cb_update("qual:role:owner:100", tapper_id=200)
        consumed = run(qualification.handle_callback(upd, ctx))
        self.assertTrue(consumed)  # consumed (it's a qual: callback)...
        # ...but nothing happened: no tag stored, no model question asked.
        self.assertNotIn(qualification.TAG_KEY, ctx.user_data)

    def test_intended_user_tap_is_processed(self):
        # Same button, tapped by the intended user 100 -> Owner -> asks model.
        ctx = FakeContext(make_config())
        upd = _qual_cb_update("qual:role:owner:100", tapper_id=100)
        run(qualification.handle_callback(upd, ctx))
        self.assertEqual(qualification._get_state(ctx), qualification.STATE_AWAITING_MODEL)

    def test_prospect_by_intended_user(self):
        ctx = FakeContext(make_config())
        upd = _qual_cb_update("qual:role:prospect:100", tapper_id=100)
        run(qualification.handle_callback(upd, ctx))
        self.assertEqual(ctx.user_data.get(qualification.TAG_KEY), "Prospect")


if __name__ == "__main__":
    unittest.main()
