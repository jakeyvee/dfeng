"""Google Sheets service interface — PLACEHOLDER for later tickets.

VOL-197 does NOT implement Sheets I/O. This module defines the interface that
VOL-198 / VOL-205 / VOL-206 will implement with ``gspread`` + ``google-auth``,
so handlers can be written against ``SheetsService`` today without coupling to
the concrete client.

Implementation guidance for the Sheets ticket:
    * Authenticate with a service account via ``google.oauth2.service_account``
      using ``config.sheets.credentials_path`` (path is gitignored).
    * Open the workbook by ``config.sheets.workbook_id`` and the worksheet by
      ``config.sheets.tab_name``.
    * Keep network calls off the event loop (gspread is sync): wrap in
      ``asyncio.to_thread`` or a small executor so the async bot stays responsive.
    * Never log full member PII rows; log row keys / IDs only.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Protocol, runtime_checkable

from ..config import Config


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
    """No-op implementation used until the real Sheets ticket lands.

    Allows the rest of the bot to be wired up and tested without credentials.
    """

    def append_member(self, record: Mapping[str, Any]) -> None:  # noqa: D401
        return None

    def find_member(self, telegram_id: int) -> Optional[Mapping[str, Any]]:
        return None


def build_sheets_service(config: Config) -> SheetsService:
    """Factory for the Sheets service.

    Returns the real client when the ``sheets`` feature flag is enabled (and
    the ticket implementing it is merged); otherwise a safe no-op.
    """

    if not config.features.sheets:
        return NullSheetsService()

    # TODO(VOL-198/205/206): construct and return the gspread-backed service.
    return NullSheetsService()
