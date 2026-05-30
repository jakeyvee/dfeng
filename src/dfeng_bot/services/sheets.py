"""Google Sheets service — schema-aware member persistence interface.

VOL-198 turns the original placeholder into a real, schema-aware client that
later tickets build on:

    * VOL-205 (persistence) calls ``ensure_header`` / ``find_row_by_telegram_id``
      / ``append_member_row`` / ``update_member_row`` to upsert members.
    * VOL-206 (retry queue) wraps those same calls with retry/backoff.

Design notes:
    * The canonical column order, enums and bot/admin ownership split live in
      :mod:`dfeng_bot.services.schema`. This module never hardcodes column names.
    * ``gspread`` and ``google-auth`` are imported **lazily** (inside the factory
      and methods), so this module imports cleanly even when those packages are
      not installed — matching the foundation's "import-clean" convention.
    * Auth is lazy: credentials are read on first use from
      ``config.sheets.credentials_path`` (a file path) OR, if that points at raw
      JSON via an env var, parsed as JSON. Credentials are NEVER hardcoded.
    * gspread is synchronous. Callers on the async bot must wrap these methods in
      ``asyncio.to_thread`` so the event loop is never blocked (see CLAUDE.md).
    * PII (phone/plate) is never logged. Only the Telegram ID key is logged.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Mapping, Optional, Protocol, runtime_checkable

from ..config import Config
from . import schema

logger = logging.getLogger("dfeng_bot")

# OAuth scopes: Sheets read/write, plus Drive (gspread opens workbooks by key
# through the Drive API).
_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


@runtime_checkable
class SheetsService(Protocol):
    """Minimal append/lookup interface backing member persistence."""

    def append_member(self, record: Mapping[str, Any]) -> None:
        """Append a member/qualification record as a new row."""
        ...

    def find_member(self, telegram_id: int) -> Optional[Mapping[str, Any]]:
        """Return the stored record for a member, or None if absent."""
        ...


class NullSheetsService:
    """No-op implementation used when Sheets is disabled or unconfigured.

    Allows the rest of the bot to be wired up and tested without credentials.
    """

    def append_member(self, record: Mapping[str, Any]) -> None:  # noqa: D401
        return None

    def find_member(self, telegram_id: int) -> Optional[Mapping[str, Any]]:
        return None

    # Schema-aware methods (no-op mirrors of GoogleSheetsService) so callers can
    # depend on the richer surface regardless of which implementation is active.
    def ensure_header(self) -> None:
        return None

    def find_row_by_telegram_id(self, tid: int) -> Optional[int]:
        return None

    def append_member_row(self, record: Mapping[str, Any]) -> None:
        return None

    def update_member_row(self, tid: int, record: Mapping[str, Any]) -> None:
        return None

    def flag_needs_reconciliation(self, tid: int) -> bool:
        # No sheet to flag; the write queue's dead-letter + ERROR log carry the
        # reconciliation signal instead. Report "not flagged".
        return False


class GoogleSheetsService:
    """Schema-aware gspread-backed Sheets client.

    Construction is cheap and does NOT authenticate; the gspread client and the
    target worksheet are built lazily on first use. This keeps import + object
    creation free of network/credential dependencies.
    """

    def __init__(self, config: Config) -> None:
        self._workbook_id = config.sheets.workbook_id
        self._tab_name = config.sheets.tab_name
        self._credentials_path = config.sheets.credentials_path
        self._worksheet: Any = None  # cached gspread Worksheet

    # --- lazy auth / worksheet ---------------------------------------------

    def _load_credentials(self) -> Any:
        """Build google-auth service-account credentials (lazy import).

        Accepts either a path to a JSON key file or, if the configured value is
        itself a JSON document (some hosts inject the key as an env var value),
        the raw JSON. Credentials are never hardcoded or logged.
        """

        from google.oauth2.service_account import Credentials  # lazy import

        raw = self._credentials_path
        if not raw:
            raise SheetsConfigError(
                "No Google credentials configured (GOOGLE_APPLICATION_CREDENTIALS)."
            )

        stripped = raw.strip()
        if stripped.startswith("{"):
            # Raw JSON injected via env var.
            info = json.loads(stripped)
            return Credentials.from_service_account_info(info, scopes=_SCOPES)

        if not os.path.exists(stripped):
            raise SheetsConfigError(
                f"Google credentials file not found at configured path: {stripped!r}"
            )
        return Credentials.from_service_account_file(stripped, scopes=_SCOPES)

    def _get_worksheet(self) -> Any:
        """Return the cached gspread worksheet, authenticating on first call."""

        if self._worksheet is not None:
            return self._worksheet

        import gspread  # lazy import

        if not self._workbook_id:
            raise SheetsConfigError("No DFENG_SHEETS_WORKBOOK_ID configured.")

        creds = self._load_credentials()
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(self._workbook_id)
        self._worksheet = spreadsheet.worksheet(self._tab_name)
        logger.info("sheets_connected", extra={"action": "sheets_connected", "tab": self._tab_name})
        return self._worksheet

    # --- schema-aware operations (used by VOL-205 / VOL-206) ---------------

    def ensure_header(self) -> None:
        """Ensure row 1 matches the canonical header from :mod:`schema`.

        Writes the header if the sheet is empty. If a header exists but differs
        from the canonical order, raises rather than silently rewriting — a
        mismatch means the workbook drifted and needs operator attention (the
        positional row mapping would otherwise corrupt data).
        """

        ws = self._get_worksheet()
        existing = ws.row_values(1)
        expected = schema.MEMBER_COLUMNS

        if not existing:
            ws.update("A1", [expected])
            logger.info("sheets_header_written", extra={"action": "sheets_header_written"})
            return

        if existing != expected:
            raise SheetsSchemaError(
                "Workbook header does not match canonical schema. "
                f"expected={expected} got={existing}"
            )

    def find_row_by_telegram_id(self, tid: int) -> Optional[int]:
        """Return the 1-based sheet row number for *tid*, or ``None``.

        Row 1 is the header, so member rows are >= 2. Matches against the
        Telegram ID key column only.
        """

        ws = self._get_worksheet()
        key_col = schema.column_index(schema.KEY_COLUMN) + 1  # gspread is 1-based
        column = ws.col_values(key_col)
        target = str(tid)
        # Skip the header at index 0.
        for offset, value in enumerate(column[1:], start=2):
            if value == target:
                return offset
        return None

    def append_member_row(self, record: Mapping[str, Any]) -> None:
        """Append a new member row built from *record* in canonical order.

        Only bot-owned columns are populated from the record; admin-owned columns
        are left blank for humans to fill (race avoidance). Unknown keys in the
        record are ignored. PII values are written to the sheet but never logged.
        """

        ws = self._get_worksheet()
        row = self._record_to_row(record)
        ws.append_row(row, value_input_option="USER_ENTERED")
        logger.info(
            "sheets_member_appended",
            extra={"action": "sheets_member_appended", "telegram_id": record.get(schema.KEY_COLUMN)},
        )

    def update_member_row(self, tid: int, record: Mapping[str, Any]) -> None:
        """Update the bot-owned cells of an existing member row.

        Writes ONLY the bot-owned column range (columns 1..len(BOT_COLUMNS)),
        leaving admin-owned columns untouched so concurrent admin edits are never
        clobbered. Raises if no row exists for *tid*.
        """

        ws = self._get_worksheet()
        row_number = self.find_row_by_telegram_id(tid)
        if row_number is None:
            raise SheetsRowNotFoundError(f"No member row found for telegram_id={tid}")

        bot_values = [self._cell_value(record, col) for col in schema.BOT_COLUMNS]
        last_col_letter = _col_letter(len(schema.BOT_COLUMNS))
        cell_range = f"A{row_number}:{last_col_letter}{row_number}"
        ws.update(cell_range, [bot_values], value_input_option="USER_ENTERED")
        logger.info(
            "sheets_member_updated",
            extra={"action": "sheets_member_updated", "telegram_id": tid},
        )

    def flag_needs_reconciliation(self, tid: int) -> bool:
        """Best-effort: set the admin ``Status`` cell to NEEDS_RECONCILIATION (VOL-206).

        Writes ONLY the single admin ``schema.RECONCILE_STATUS_COLUMN`` cell of an
        existing member row — never the bot-owned range, so it can't clobber the
        member data, and never creates a row. Returns True if the flag was written,
        False if no row exists for *tid*. May RAISE if Sheets is unreachable; the
        caller (write queue) treats this as best-effort and swallows errors, since
        the dead-letter list + ERROR log are the durable reconciliation signals.
        """

        ws = self._get_worksheet()
        row_number = self.find_row_by_telegram_id(tid)
        if row_number is None:
            return False
        col_letter = _col_letter(schema.column_index(schema.RECONCILE_STATUS_COLUMN) + 1)
        cell = f"{col_letter}{row_number}"
        ws.update(cell, [[schema.RECONCILE_STATUS_VALUE]], value_input_option="USER_ENTERED")
        logger.warning(
            "sheets_reconcile_flagged",
            extra={"action": "sheets_reconcile_flagged", "telegram_id": tid},
        )
        return True

    # --- legacy Protocol surface (kept for callers wired to SheetsService) --

    def append_member(self, record: Mapping[str, Any]) -> None:
        self.append_member_row(record)

    def find_member(self, telegram_id: int) -> Optional[Mapping[str, Any]]:
        row_number = self.find_row_by_telegram_id(telegram_id)
        if row_number is None:
            return None
        ws = self._get_worksheet()
        values = ws.row_values(row_number)
        return dict(zip(schema.MEMBER_COLUMNS, values))

    # --- helpers ------------------------------------------------------------

    @staticmethod
    def _cell_value(record: Mapping[str, Any], column: str) -> str:
        value = record.get(column, "")
        return "" if value is None else str(value)

    def _record_to_row(self, record: Mapping[str, Any]) -> list[str]:
        """Map *record* onto a full canonical row.

        Bot-owned columns are filled from the record; admin-owned columns are
        emitted as empty strings so the appended row keeps the canonical width
        without ever populating admin-owned cells.
        """

        row: list[str] = []
        for column in schema.MEMBER_COLUMNS:
            if schema.is_bot_owned(column):
                row.append(self._cell_value(record, column))
            else:
                row.append("")
        return row


def _col_letter(one_based_index: int) -> str:
    """Convert a 1-based column index to an A1 column letter (1->A, 27->AA)."""

    letters = ""
    n = one_based_index
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


class SheetsConfigError(RuntimeError):
    """Raised when Sheets is enabled but required config/credentials are missing."""


class SheetsSchemaError(RuntimeError):
    """Raised when the workbook header drifts from the canonical schema."""


class SheetsRowNotFoundError(RuntimeError):
    """Raised when an update targets a member row that does not exist."""


def build_sheets_service(config: Config) -> SheetsService:
    """Factory for the Sheets service.

    Returns a real :class:`GoogleSheetsService` when the ``sheets`` feature flag
    is enabled AND the workbook id + credentials path are configured. Otherwise
    returns a safe :class:`NullSheetsService` so the rest of the bot still runs.

    The gspread/google-auth imports happen lazily inside the service methods, so
    this factory does not require those packages to be installed in order to
    return the Null service.
    """

    if not config.features.sheets:
        return NullSheetsService()

    if not config.sheets.workbook_id or not config.sheets.credentials_path:
        logger.warning(
            "sheets_unconfigured",
            extra={"action": "sheets_unconfigured", "outcome": "fallback_null"},
        )
        return NullSheetsService()

    return GoogleSheetsService(config)
