"""Canonical member-row schema — the single source of truth for the workbook.

Both the human-readable spec (``config/sheets-schema.md``) and the runtime
Sheets client (``services/sheets.py``) derive from the constants here. Keep this
file and ``config/sheets-schema.md`` in sync; if you change a column name or
order, update both and re-run the header-reconciliation tooling.

Column ownership (race-avoidance, see ``config/sheets-schema.md``):
    * **Bot-owned** columns (1-8, :data:`BOT_COLUMNS`) are written exclusively by
      the service account via the bot. Admins should treat them as read-only.
    * **Admin-owned** columns (:data:`ADMIN_COLUMNS`) are appended AFTER the
      bot-owned ones and are edited by humans only. The bot never writes them, so
      a member append/update and an admin edit never touch the same cell.

The STABLE column order in :data:`MEMBER_COLUMNS` is load-bearing: the workbook's
header row must match it exactly, and persistence code maps record dicts onto
positional rows using this order.
"""

from __future__ import annotations

# --- Bot-owned columns (1-8), written by the service account ---------------
# Order here IS the spreadsheet column order. Do not reorder existing entries.
BOT_COLUMNS: list[str] = [
    "Telegram ID",          # 1 - unique key, stable
    "Telegram username",    # 2 - public @handle (may be empty)
    "Tag",                  # 3 - enum, see TAGS
    "Optional phone",       # 4 - PII, may be empty; never logged
    "Optional plate",       # 5 - PII, may be empty; never logged
    "Consent timestamp",    # 6 - ISO-8601 UTC when PDPA consent captured
    "Entry source",         # 7 - enum, see ENTRY_SOURCES
    "Joined timestamp",     # 8 - ISO-8601 UTC when member joined community
]

# --- Admin-owned columns, edited by humans only (appended AFTER bot columns) -
ADMIN_COLUMNS: list[str] = [
    "Notes",                # free-text admin notes
    "Status",               # admin-managed lifecycle label (e.g. active/left)
    "Deletion requested",   # admin marks deletion/retention requests here
    "Last reconciled",      # timestamp of last admin reconciliation pass
]

# --- Full ordered header row -----------------------------------------------
MEMBER_COLUMNS: list[str] = [*BOT_COLUMNS, *ADMIN_COLUMNS]

# --- Allowed enum values ----------------------------------------------------
# Column 3: Tag.
TAGS: list[str] = [
    "BOX Owner",
    "007 Owner",
    "VIGO Owner",
    "Prospect",
]

# Column 7: Entry source.
ENTRY_SOURCES: list[str] = [
    "salesperson",
    "showroom QR",
    "roadshow QR",
    "Linktree",
    "event QR",
    "website placeholder",
]

# --- Convenience views ------------------------------------------------------
# The stable key column (used for idempotent lookups / upserts).
KEY_COLUMN: str = "Telegram ID"

# Columns holding PII that must never be written to logs.
PII_COLUMNS: frozenset[str] = frozenset({"Optional phone", "Optional plate"})


def column_index(name: str) -> int:
    """Return the 0-based position of *name* in the canonical header.

    Raises ``KeyError`` with a clear message if the column is unknown, so callers
    fail loudly rather than silently writing to the wrong cell.
    """

    try:
        return MEMBER_COLUMNS.index(name)
    except ValueError as exc:  # pragma: no cover - defensive
        raise KeyError(f"Unknown member column: {name!r}") from exc


def is_bot_owned(name: str) -> bool:
    """True if *name* is a bot-owned column (the bot may write it)."""

    return name in BOT_COLUMNS
