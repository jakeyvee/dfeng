"""VOL-214 scenario 12: admin moderation commands register + are admin-gated.

Logic-level coverage (live Telegram delete/mute/pin/ban deferred to the manual
checklist):
  * build_moderation_handlers registers the expected commands.
  * a NON-admin call is denied ("Not authorised.") and performs NO Bot API call.
  * an ADMIN call performs the corresponding Bot API call.
  * the core admin commands (/health, /stats, /sheets_status) are admin-gated too.
"""

import unittest

from dfeng_bot.handlers import moderation
from dfeng_bot.handlers.commands import build_command_handlers
from dfeng_bot.handlers.moderation import build_moderation_handlers

from _config import make_config
from _fakes import FakeContext, FakeMessage, FakeUpdate, FakeUser, run

ADMIN_ID = 555
NONADMIN_ID = 999


def _command_names(handlers):
    names = set()
    for h in handlers:
        cmds = getattr(h, "commands", None)
        if cmds:
            names.update(cmds)
    return names


class RegistrationTest(unittest.TestCase):
    def test_moderation_commands_registered(self):
        names = _command_names(build_moderation_handlers())
        expected = {"pin", "del", "delete", "mute", "unmute", "ban", "unban",
                    "approve", "modhelp"}
        self.assertTrue(expected.issubset(names), names)

    def test_core_admin_commands_registered(self):
        names = _command_names(build_command_handlers())
        # admin-gated commands + the user trust command all wired in.
        for c in ("health", "stats", "sheets_status", "reconcile", "trust"):
            self.assertIn(c, names)


class AdminGateTest(unittest.TestCase):
    def setUp(self):
        self.config = make_config(admin_ids=[ADMIN_ID])

    def _update(self, user_id, *, reply_target_id=777):
        caller = FakeUser(user_id, username="caller")
        target_user = FakeUser(reply_target_id, username="target")
        reply_to = FakeMessage(text="bad message", from_user=target_user, message_id=4321)
        msg = FakeMessage(text="/del", from_user=caller, reply_to_message=reply_to)
        return FakeUpdate(message=msg, user=caller)

    def test_nonadmin_delete_denied_no_api_call(self):
        ctx = FakeContext(self.config)
        upd = self._update(NONADMIN_ID)
        run(moderation.cmd_delete(upd, ctx))
        # No Bot API call was made.
        self.assertEqual(
            [c for c in ctx.bot.calls if c[0] == "delete_message"], []
        )
        # User got the denial message.
        self.assertEqual(upd.effective_message.replies[-1]["text"], "Not authorised.")

    def test_admin_delete_calls_api(self):
        ctx = FakeContext(self.config)
        upd = self._update(ADMIN_ID)
        run(moderation.cmd_delete(upd, ctx))
        delete_calls = [c for c in ctx.bot.calls if c[0] == "delete_message"]
        self.assertEqual(len(delete_calls), 1)

    def test_nonadmin_pin_denied(self):
        ctx = FakeContext(self.config)
        caller = FakeUser(NONADMIN_ID)
        reply_to = FakeMessage(text="pin me", message_id=10)
        msg = FakeMessage(text="/pin", from_user=caller, reply_to_message=reply_to)
        upd = FakeUpdate(message=msg, user=caller)
        run(moderation.cmd_pin(upd, ctx))
        self.assertEqual([c for c in ctx.bot.calls if c[0] == "pin_chat_message"], [])

    def test_admin_ban_calls_api(self):
        ctx = FakeContext(self.config)
        caller = FakeUser(ADMIN_ID)
        msg = FakeMessage(text="/ban 12345", from_user=caller)
        upd = FakeUpdate(message=msg, user=caller)
        ctx.args = ["12345"]
        run(moderation.cmd_ban(upd, ctx))
        ban_calls = [c for c in ctx.bot.calls if c[0] == "ban_chat_member"]
        self.assertEqual(len(ban_calls), 1)
        self.assertEqual(ban_calls[0][1]["user_id"], 12345)

    def test_admin_mute_is_time_bounded(self):
        ctx = FakeContext(self.config)
        caller = FakeUser(ADMIN_ID)
        msg = FakeMessage(text="/mute 5 12345", from_user=caller)
        upd = FakeUpdate(message=msg, user=caller)
        ctx.args = ["5", "12345"]
        run(moderation.cmd_mute(upd, ctx))
        restrict_calls = [c for c in ctx.bot.calls if c[0] == "restrict_chat_member"]
        self.assertEqual(len(restrict_calls), 1)
        # 5 minutes -> a finite until_date (reversible, auto-expiring).
        self.assertIsNotNone(restrict_calls[0][1]["until_date"])


class CoreCommandGateTest(unittest.TestCase):
    def setUp(self):
        self.config = make_config(admin_ids=[ADMIN_ID])

    def test_health_denies_nonadmin(self):
        from dfeng_bot.handlers.commands import cmd_admin_health

        ctx = FakeContext(self.config)
        caller = FakeUser(NONADMIN_ID)
        upd = FakeUpdate(message=FakeMessage(text="/health", from_user=caller), user=caller)
        run(cmd_admin_health(upd, ctx))
        self.assertEqual(upd.effective_message.replies[-1]["text"], "Not authorised.")

    def test_health_allows_admin(self):
        from dfeng_bot.handlers.commands import cmd_admin_health

        ctx = FakeContext(self.config)
        caller = FakeUser(ADMIN_ID)
        upd = FakeUpdate(message=FakeMessage(text="/health", from_user=caller), user=caller)
        run(cmd_admin_health(upd, ctx))
        self.assertIn("OK", upd.effective_message.replies[-1]["text"])


if __name__ == "__main__":
    unittest.main()
