"""VOL-214 PDPA gate + PII/secret hygiene across the suite.

  * The PDPA consent notice shown to members is byte-for-byte the locked policy
    constant (policy.PDPA_CONSENT_NOTICE), and onboarding shows it BEFORE asking
    for any optional field.
  * Captured logs from the async onboarding finish path never contain PII
    (phone/plate) — only presence booleans.
  * The end-to-end async onboarding completes even when the Sheets write raises
    (non-blocking persistence).
"""

import logging
import unittest

from dfeng_bot import policy
from dfeng_bot.handlers import onboarding, qualification, membership
from dfeng_bot.services import schema

from _config import make_config
from _fakes import (
    FAKE_PHONE,
    FAKE_PLATE,
    FakeContext,
    FakeMessage,
    FakeSheetsService,
    FakeUpdate,
    FakeUser,
    run,
)


class PdpaNoticeTest(unittest.TestCase):
    def test_notice_is_locked_constant(self):
        self.assertEqual(
            policy.PDPA_CONSENT_NOTICE,
            "By providing your information, you consent to Dongfeng Singapore storing "
            "and using the information solely for community management, support and "
            "engagement purposes in accordance with applicable PDPA requirements.",
        )

    def test_consent_shown_before_optional_capture(self):
        # start_profile_capture should send the CONSENT_INTRO then the exact PDPA
        # notice BEFORE any phone/plate prompt.
        cfg = make_config()
        ctx = FakeContext(cfg)
        user = FakeUser(3001, username="member")
        msg = FakeMessage(text="hi", from_user=user)
        upd = FakeUpdate(message=msg, user=user)
        run(onboarding.start_profile_capture(upd, ctx))
        texts = [r["text"] for r in msg.replies]
        self.assertIn(policy.PDPA_CONSENT_NOTICE, texts)
        # The PDPA notice must appear; no phone/plate prompt sent yet.
        self.assertNotIn(onboarding.PHONE_PROMPT, texts)
        self.assertNotIn(onboarding.PLATE_PROMPT, texts)


class OnboardingFinishNonBlockingTest(unittest.TestCase):
    """The async finish path persists via FakeSheetsService and is PII-safe."""

    def _build_ctx_update(self, config, *, with_pii=True):
        ctx = FakeContext(config)
        # Simulate upstream state: a resolved tag + entry source in user_data.
        ctx.user_data[qualification.TAG_KEY] = "BOX Owner"
        ctx.user_data[membership.ENTRY_SOURCE_KEY] = "showroom QR"
        if with_pii:
            ctx.user_data[onboarding.PHONE_KEY] = FAKE_PHONE
            ctx.user_data[onboarding.PLATE_KEY] = FAKE_PLATE
            ctx.user_data[onboarding.STATE_KEY] = onboarding.STATE_AWAITING_PLATE
        user = FakeUser(4001, username="member")
        msg = FakeMessage(text="SGFAKE", from_user=user)
        upd = FakeUpdate(message=msg, user=user)
        return ctx, upd

    def test_finish_persists_and_clears_pii_from_user_data(self):
        # Force the direct write path (no queue) and inject a FakeSheetsService by
        # enabling sheets isn't necessary: we patch build_sheets_service via the
        # module-level seam. Simplest: monkeypatch onboarding's sheets factory.
        import dfeng_bot.services.sheets as sheets_mod

        fake = FakeSheetsService()
        original = sheets_mod.build_sheets_service
        sheets_mod.build_sheets_service = lambda cfg: fake

        # Capture logs so we can assert the SUCCESS event fires (regression for
        # DEFECT D1: before the log_event fix, the success path raised TypeError
        # and was masked as member_persist_failed).
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
            cfg = make_config()
            ctx, upd = self._build_ctx_update(cfg)
            run(onboarding._finish_and_persist(upd, ctx, announce=True))
        finally:
            sheets_mod.build_sheets_service = original
            logger.removeHandler(cap)
            logger.setLevel(prev)

        events = {r.getMessage() for r in records}
        self.assertIn("member_persisted", events)
        self.assertNotIn("member_persist_failed", events)

        # Member row written with PII in its dedicated cells only.
        self.assertEqual(len(fake.rows), 1)
        row = fake.rows[4001]
        self.assertEqual(row["Optional phone"], FAKE_PHONE)
        self.assertEqual(row["Optional plate"], FAKE_PLATE)
        self.assertEqual(row["Tag"], "BOX Owner")
        self.assertEqual(row["Entry source"], "showroom QR")
        # Consent timestamp recorded because optional data was provided.
        self.assertTrue(row["Consent timestamp"])
        # PII cleared from in-memory user_data after capture.
        self.assertNotIn(onboarding.PHONE_KEY, ctx.user_data)
        self.assertNotIn(onboarding.PLATE_KEY, ctx.user_data)

    def test_finish_is_nonblocking_when_sheets_raises(self):
        import dfeng_bot.services.sheets as sheets_mod

        class _BoomService:
            def ensure_header(self):
                raise RuntimeError("Sheets down")

            def find_row_by_telegram_id(self, tid):
                raise RuntimeError("Sheets down")

            def append_member_row(self, record):
                raise RuntimeError("Sheets down")

            def update_member_row(self, tid, record):
                raise RuntimeError("Sheets down")

        original = sheets_mod.build_sheets_service
        sheets_mod.build_sheets_service = lambda cfg: _BoomService()
        try:
            cfg = make_config()
            ctx, upd = self._build_ctx_update(cfg)
            # Must NOT raise — persistence failure is swallowed + logged.
            run(onboarding._finish_and_persist(upd, ctx, announce=True))
        finally:
            sheets_mod.build_sheets_service = original

        # Member still got a confirmation reply (flow completed).
        self.assertTrue(upd.effective_message.replies)

    def test_logs_never_contain_pii(self):
        import dfeng_bot.services.sheets as sheets_mod

        fake = FakeSheetsService()
        original = sheets_mod.build_sheets_service
        sheets_mod.build_sheets_service = lambda cfg: fake

        handler_records = []

        class _Capture(logging.Handler):
            def emit(self, record):
                handler_records.append(record)

        logger = logging.getLogger("dfeng_bot")
        cap = _Capture()
        logger.addHandler(cap)
        prev_level = logger.level
        logger.setLevel(logging.DEBUG)
        try:
            cfg = make_config()
            ctx, upd = self._build_ctx_update(cfg)
            run(onboarding._finish_and_persist(upd, ctx, announce=True))
        finally:
            sheets_mod.build_sheets_service = original
            logger.removeHandler(cap)
            logger.setLevel(prev_level)

        # Scan every captured log record's message + extra fields for PII.
        for rec in handler_records:
            blob = rec.getMessage() + " " + " ".join(
                str(v) for k, v in vars(rec).items()
                if k not in {"args", "msg", "exc_info", "exc_text", "stack_info"}
            )
            self.assertNotIn(FAKE_PHONE, blob)
            self.assertNotIn(FAKE_PLATE, blob)


if __name__ == "__main__":
    unittest.main()
