"""VOL-214 scenarios 2-5: owner/prospect/skip onboarding record building + tags.

Covers the pure logic layer:
  * resolve_tag / model_to_tag / answer_to_role (qualification segmentation)
  * build_member_record (PDPA consent-timestamp rule, schema column mapping)
  * persist_member idempotency through a FakeSheetsService (upsert keyed on
    Telegram ID)

PII hygiene: uses OBVIOUSLY-FAKE phone/plate values and asserts they only ever
land in the dedicated record cells, never in any other field.
"""

import unittest

from dfeng_bot.handlers import onboarding, qualification
from dfeng_bot.services import schema

from _fakes import FAKE_PHONE, FAKE_PLATE, FakeSheetsService


class TagResolutionTest(unittest.TestCase):
    """Scenario 4 + 5: model->tag mapping and the Prospect default guarantee."""

    def test_box_owner_tag(self):
        self.assertEqual(qualification.model_to_tag("BOX"), "BOX Owner")

    def test_007_owner_tag(self):
        self.assertEqual(qualification.model_to_tag("007"), "007 Owner")

    def test_vigo_owner_tag(self):
        self.assertEqual(qualification.model_to_tag("vigo"), "VIGO Owner")

    def test_unknown_model_returns_none(self):
        self.assertIsNone(qualification.model_to_tag("Cybertruck"))

    def test_skip_qualification_defaults_to_prospect(self):
        # Scenario 5: a user who skips / never completes resolves to Prospect.
        self.assertEqual(qualification.resolve_tag(None), "Prospect")
        self.assertEqual(qualification.resolve_tag("garbage"), "Prospect")

    def test_resolve_tag_preserves_valid_owner_tags(self):
        for tag in ("BOX Owner", "007 Owner", "VIGO Owner", "Prospect"):
            self.assertEqual(qualification.resolve_tag(tag), tag)

    def test_answer_to_role(self):
        self.assertEqual(qualification.answer_to_role("Owner"), "owner")
        self.assertEqual(qualification.answer_to_role("prospect"), "prospect")
        self.assertEqual(qualification.answer_to_role("just looking"), "prospect")
        self.assertIsNone(qualification.answer_to_role("???"))

    def test_tags_match_schema(self):
        self.assertEqual(
            {qualification.model_to_tag(m) for m in ("BOX", "007", "VIGO")}
            | {"Prospect"},
            set(schema.TAGS),
        )


class BoxOwnerDeclinesTest(unittest.TestCase):
    """Scenario 2: BOX owner, declines phone/plate -> empty PII + empty consent."""

    def test_record_has_box_tag_and_empty_optional_fields(self):
        rec = onboarding.build_member_record(
            telegram_id=1001,
            username="boxowner",
            tag="BOX Owner",
            phone=None,
            plate=None,
            consent_ts="2026-05-31T00:00:00+00:00",  # passed but must be dropped
            entry_source="showroom QR",
            joined_ts="2026-05-30T00:00:00+00:00",
        )
        self.assertEqual(rec["Tag"], "BOX Owner")
        self.assertEqual(rec["Optional phone"], "")
        self.assertEqual(rec["Optional plate"], "")
        # Consent rule: no optional data provided -> NO consent timestamp.
        self.assertEqual(rec["Consent timestamp"], "")
        self.assertEqual(rec["Entry source"], "showroom QR")
        self.assertEqual(set(rec), set(schema.BOT_COLUMNS))


class OwnerProvidesDataTest(unittest.TestCase):
    """Scenario 3: 007 owner provides phone/plate after consent -> consent ts set."""

    def test_consent_timestamp_set_when_optional_data_provided(self):
        rec = onboarding.build_member_record(
            telegram_id=1002,
            username="oo7",
            tag="007 Owner",
            phone=FAKE_PHONE,
            plate=FAKE_PLATE,
            consent_ts="2026-05-31T12:00:00+00:00",
            entry_source="roadshow QR",
            joined_ts="2026-05-30T00:00:00+00:00",
        )
        self.assertEqual(rec["Tag"], "007 Owner")
        self.assertEqual(rec["Optional phone"], FAKE_PHONE)
        self.assertEqual(rec["Optional plate"], FAKE_PLATE)
        self.assertEqual(rec["Consent timestamp"], "2026-05-31T12:00:00+00:00")

    def test_phone_only_still_sets_consent(self):
        rec = onboarding.build_member_record(
            1003, "phoneonly", "VIGO Owner", FAKE_PHONE, None,
            "2026-05-31T12:00:00+00:00", "Linktree", "2026-05-30T00:00:00+00:00",
        )
        self.assertEqual(rec["Consent timestamp"], "2026-05-31T12:00:00+00:00")
        self.assertEqual(rec["Optional plate"], "")

    def test_pii_only_appears_in_its_own_cells(self):
        # PII hygiene: the fake phone/plate must NOT leak into any other column.
        rec = onboarding.build_member_record(
            1004, "owner", "BOX Owner", FAKE_PHONE, FAKE_PLATE,
            "2026-05-31T12:00:00+00:00", "event QR", "2026-05-30T00:00:00+00:00",
        )
        for col, val in rec.items():
            if col not in schema.PII_COLUMNS:
                self.assertNotIn(FAKE_PHONE, str(val), col)
                self.assertNotIn(FAKE_PLATE, str(val), col)


class PersistIdempotencyTest(unittest.TestCase):
    """persist_member upserts: append once, then update (no duplicate row)."""

    def test_append_then_update_is_idempotent(self):
        svc = FakeSheetsService()
        r1 = onboarding.build_member_record(
            2001, "alice", "Prospect", None, None, "",
            "salesperson", "2026-05-30T00:00:00+00:00",
        )
        self.assertEqual(onboarding.persist_member(svc, r1), "appended")
        self.assertEqual(len(svc.rows), 1)

        # Re-onboarding the SAME id updates the existing row, never duplicates.
        r2 = onboarding.build_member_record(
            2001, "alice", "BOX Owner", FAKE_PHONE, None,
            "2026-05-31T00:00:00+00:00", "salesperson", "2026-05-30T00:00:00+00:00",
        )
        self.assertEqual(onboarding.persist_member(svc, r2), "updated")
        self.assertEqual(len(svc.rows), 1)  # still ONE row
        self.assertEqual(svc.rows[2001]["Tag"], "BOX Owner")
        self.assertEqual(svc.appends, 1)
        self.assertEqual(svc.updates, 1)
        self.assertEqual(svc.header_calls, 2)  # ensure_header idempotent per write

    def test_null_service_completes(self):
        from dfeng_bot.services.sheets import NullSheetsService

        r = onboarding.build_member_record(
            2002, None, "Prospect", None, None, "", "salesperson",
            "2026-05-30T00:00:00+00:00",
        )
        # NullSheetsService no-ops but the seam still reports a branch.
        self.assertEqual(onboarding.persist_member(NullSheetsService(), r), "appended")


if __name__ == "__main__":
    unittest.main()
