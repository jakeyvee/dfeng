"""Require-qualification gate: mute on join, auto-unmute on classification.

Verifies the bot restricts a new member when the gate is on (and not when off /
for admins), and lifts the restriction once they pick a tag.
"""

import unittest

from _config import make_config
from _fakes import FakeChat, FakeContext, FakeMessage, FakeUpdate, FakeUser, run

from dfeng_bot.handlers import membership, qualification


def _calls(ctx, name):
    return [kw for (n, kw) in ctx.bot.calls if n == name]


def _restrict_perms(ctx):
    """Return list of (can_send_messages) flags from restrict_chat_member calls."""
    out = []
    for kw in _calls(ctx, "restrict_chat_member"):
        perms = kw.get("permissions")
        out.append(getattr(perms, "can_send_messages", None))
    return out


class TestMuteOnJoin(unittest.TestCase):
    def _join(self, cfg, uid=900):
        member = FakeUser(uid, "newbie")
        upd = FakeUpdate(message=FakeMessage(from_user=member), user=member,
                         chat=FakeChat(-100, "supergroup"))
        ctx = FakeContext(cfg)
        run(membership.on_new_member(upd, ctx, member))
        return ctx

    def test_gate_on_mutes_new_member(self):
        cfg = make_config(features={"require_qualification": True, "welcome": False})
        ctx = self._join(cfg)
        # A restrict call with can_send_messages == False was made.
        self.assertIn(False, _restrict_perms(ctx))

    def test_gate_off_does_not_mute(self):
        cfg = make_config(features={"require_qualification": False, "welcome": False})
        ctx = self._join(cfg)
        self.assertEqual(_restrict_perms(ctx), [])

    def test_admin_not_muted(self):
        cfg = make_config(admin_ids=[900], features={"require_qualification": True, "welcome": False})
        ctx = self._join(cfg, uid=900)
        self.assertEqual(_restrict_perms(ctx), [])


class TestUnmuteOnCompletion(unittest.TestCase):
    def test_picking_prospect_unmutes(self):
        cfg = make_config(features={"require_qualification": True})
        u = FakeUser(901, "newbie")
        upd = FakeUpdate(message=FakeMessage(from_user=u), user=u,
                         chat=FakeChat(-100, "supergroup"))
        ctx = FakeContext(cfg)
        run(qualification._assign_prospect(upd, ctx, path="prospect"))
        # An unmute (restrict with can_send_messages True) was issued.
        self.assertIn(True, _restrict_perms(ctx))

    def test_no_unmute_when_gate_off(self):
        cfg = make_config(features={"require_qualification": False})
        u = FakeUser(902, "newbie")
        upd = FakeUpdate(message=FakeMessage(from_user=u), user=u,
                         chat=FakeChat(-100, "supergroup"))
        ctx = FakeContext(cfg)
        run(qualification._assign_prospect(upd, ctx, path="prospect"))
        self.assertEqual(_restrict_perms(ctx), [])


if __name__ == "__main__":
    unittest.main()
