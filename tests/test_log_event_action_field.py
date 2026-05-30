"""Regression test for DEFECT D1 (VOL-214): log_event(action=...) field collision.

The moderation/persistence handlers (antispam, flood_control, link_restrictions,
onboarding) call ``log_event("<event>", update, ..., action="<verb>", ...)`` —
passing an ``action=`` STRUCTURED FIELD alongside the positional event name.

Before the fix, ``log_event(action, update, *, level, **fields)`` raised
``TypeError: log_event() got multiple values for argument 'action'`` whenever a
caller did this. In antispam.check the offending log line is NOT wrapped in
try/except, so the spam-removed audit log + metrics bump + ApplicationHandlerStop
were all skipped. The fix makes the first parameter positional-only so an
``action=`` field lands in **fields and wins in the logged output.

This test asserts the call no longer raises AND the field value is what's logged.
"""

import logging
import unittest

from dfeng_bot.logging_setup import log_event


class LogEventActionFieldTest(unittest.TestCase):
    def test_action_field_does_not_collide(self):
        # Must not raise even though 'action' is also a structured field.
        try:
            log_event(
                "antispam_action",
                None,
                category="link",
                rule="shortener:bit.ly",
                action="deleted",
                outcome="removed",
            )
        except TypeError as exc:  # pragma: no cover - the defect, if regressed
            self.fail(f"log_event raised on an action= field: {exc}")

    def test_action_field_wins_in_output(self):
        records = []

        class _Cap(logging.Handler):
            def emit(self, rec):
                records.append(rec)

        logger = logging.getLogger("dfeng_bot")
        cap = _Cap()
        logger.addHandler(cap)
        prev = logger.level
        logger.setLevel(logging.DEBUG)
        try:
            log_event("member_persisted", None, action="appended", outcome="persisted")
        finally:
            logger.removeHandler(cap)
            logger.setLevel(prev)

        self.assertEqual(len(records), 1)
        rec = records[0]
        # The event name is the log message; the field value is the 'action' extra.
        self.assertEqual(rec.getMessage(), "member_persisted")
        self.assertEqual(getattr(rec, "action"), "appended")
        self.assertEqual(getattr(rec, "outcome"), "persisted")


if __name__ == "__main__":
    unittest.main()
