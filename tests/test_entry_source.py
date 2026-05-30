"""VOL-214 scenario 1: each of the six entry sources resolves correctly.

The six canonical sources are: salesperson, showroom QR, roadshow QR, Linktree,
event QR, website placeholder. Only FOUR are tracked by a named invite link
(showroom/roadshow/event/Linktree). By documented design
(services/entry_source.py + docs/entry-links.md), salesperson and
website placeholder are NOT link-tracked: a salesperson adds members directly and
the website is an external placeholder URL, so a join exposing no (or an unknown)
link falls back to DEFAULT_ENTRY_SOURCE == "salesperson".

These tests assert the real, documented behaviour — including that the two
non-link-tracked sources resolve via the fallback (NOT a bug; see qa-checklist.md).
"""

import unittest

from dfeng_bot.services import entry_source
from dfeng_bot.services.schema import ENTRY_SOURCES


# Stable, fake invite-link strings keyed by source id (not real grant links).
LINKS = {
    "showroom QR": "https://t.me/+fake_showroom",
    "roadshow QR": "https://t.me/+fake_roadshow",
    "event QR": "https://t.me/+fake_event",
    "Linktree": "https://t.me/+fake_linktree",
}


class EntrySourceTest(unittest.TestCase):
    def setUp(self):
        # Map every configured link to its source; resolver is pure given mapping.
        self.mapping = {link: src for src, link in LINKS.items()}

    def test_schema_has_exactly_six_sources(self):
        self.assertEqual(len(ENTRY_SOURCES), 6)
        self.assertEqual(
            set(ENTRY_SOURCES),
            {
                "salesperson",
                "showroom QR",
                "roadshow QR",
                "Linktree",
                "event QR",
                "website placeholder",
            },
        )

    def test_four_link_tracked_sources_resolve_by_link(self):
        for src, link in LINKS.items():
            with self.subTest(source=src):
                self.assertEqual(
                    entry_source.resolve_entry_source(link, mapping=self.mapping),
                    src,
                )

    def test_salesperson_resolves_via_fallback_when_no_link(self):
        # salesperson is the documented DEFAULT for an un-linked join.
        self.assertEqual(entry_source.DEFAULT_ENTRY_SOURCE, "salesperson")
        self.assertEqual(
            entry_source.resolve_entry_source(None, mapping=self.mapping),
            "salesperson",
        )

    def test_website_placeholder_is_not_link_tracked_falls_back(self):
        # website placeholder has NO invite link (external URL); a join with an
        # unknown/absent link falls back to the documented default. This is the
        # designed behaviour, asserted honestly.
        self.assertNotIn("website placeholder", self.mapping.values())
        self.assertEqual(
            entry_source.resolve_entry_source(
                "https://t.me/+website_not_registered", mapping=self.mapping
            ),
            "salesperson",
        )

    def test_unknown_link_falls_back_to_default(self):
        self.assertEqual(
            entry_source.resolve_entry_source(
                "https://t.me/+totally_unknown", mapping=self.mapping
            ),
            entry_source.DEFAULT_ENTRY_SOURCE,
        )

    def test_whitespace_in_link_is_tolerated(self):
        self.assertEqual(
            entry_source.resolve_entry_source(
                "  " + LINKS["event QR"] + " ", mapping=self.mapping
            ),
            "event QR",
        )

    def test_every_resolved_value_is_a_valid_schema_source(self):
        candidates = list(LINKS.values()) + [None, "https://t.me/+nope"]
        for c in candidates:
            self.assertIn(
                entry_source.resolve_entry_source(c, mapping=self.mapping),
                ENTRY_SOURCES,
            )


if __name__ == "__main__":
    unittest.main()
