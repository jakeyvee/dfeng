"""Shared test fakes for the VOL-214 QA suite.

NO network, NO live Telegram, NO gspread. These minimal stand-ins let us drive
the real handler/service code at the logic level.

PII hygiene: every fixture uses OBVIOUSLY-FAKE values (e.g. phone "000-FAKE",
plate "FAKEPLATE"). Tests assert PII never appears in logged fields / dead-letter
records — see test_pii_hygiene.py and the assertions in test_onboarding_*.
"""

from __future__ import annotations

import asyncio
from typing import Any, Mapping, Optional

from dfeng_bot.services import schema


# --- obviously-fake PII sentinels (never real data) --------------------------
FAKE_PHONE = "000-FAKE-PHONE"
FAKE_PLATE = "FAKEPLATE1"


def run(coro):
    """Run a coroutine to completion on a fresh event loop (test helper)."""
    return asyncio.run(coro)


class FakeUser:
    def __init__(self, user_id: int, username: Optional[str] = None, is_bot: bool = False):
        self.id = user_id
        self.username = username
        self.is_bot = is_bot
        self.first_name = "Test"


class FakeMessage:
    """Stand-in for telegram.Message. Records reply_text calls."""

    def __init__(
        self,
        text: Optional[str] = None,
        thread_id: Optional[int] = None,
        entities: Optional[list] = None,
        caption: Optional[str] = None,
        caption_entities: Optional[list] = None,
        reply_to_message: Optional["FakeMessage"] = None,
        from_user: Optional[FakeUser] = None,
        message_id: int = 1,
    ):
        self.text = text
        self.caption = caption
        self.entities = entities or []
        self.caption_entities = caption_entities or []
        self.message_thread_id = thread_id
        self.reply_to_message = reply_to_message
        self.from_user = from_user
        self.message_id = message_id
        self.new_chat_members: list = []
        self.replies: list[dict[str, Any]] = []
        self.deleted = False

    async def reply_text(self, text: str, **kwargs):
        self.replies.append({"text": text, "kwargs": kwargs})
        return FakeMessage(text=text)

    async def delete(self):
        self.deleted = True
        return True


class FakeCallbackQuery:
    def __init__(self, data: str, message: Optional[FakeMessage] = None,
                 from_user: Optional[FakeUser] = None):
        self.data = data
        self.message = message
        self.from_user = from_user
        self.answered = False

    async def answer(self, *a, **k):
        self.answered = True


class FakeChat:
    def __init__(self, chat_id: int = -100123):
        self.id = chat_id


class FakeUpdate:
    """Stand-in for telegram.Update."""

    def __init__(
        self,
        message: Optional[FakeMessage] = None,
        user: Optional[FakeUser] = None,
        chat: Optional[FakeChat] = None,
        callback_query: Optional[FakeCallbackQuery] = None,
        chat_member: Any = None,
    ):
        self._message = message
        self._user = user
        self._chat = chat or FakeChat()
        self.callback_query = callback_query
        self.chat_member = chat_member

    @property
    def effective_message(self):
        if self._message is not None:
            return self._message
        if self.callback_query is not None:
            return self.callback_query.message
        return None

    @property
    def effective_user(self):
        if self._user is not None:
            return self._user
        if self.callback_query is not None:
            return self.callback_query.from_user
        msg = self.effective_message
        return getattr(msg, "from_user", None) if msg else None

    @property
    def effective_chat(self):
        return self._chat


class FakeBot:
    """Records Bot API calls instead of hitting Telegram."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def send_message(self, **kwargs):
        self.calls.append(("send_message", kwargs))
        return FakeMessage(text=kwargs.get("text"))

    async def restrict_chat_member(self, **kwargs):
        self.calls.append(("restrict_chat_member", kwargs))
        return True

    async def delete_message(self, **kwargs):
        self.calls.append(("delete_message", kwargs))
        return True

    async def pin_chat_message(self, **kwargs):
        self.calls.append(("pin_chat_message", kwargs))
        return True

    async def ban_chat_member(self, **kwargs):
        self.calls.append(("ban_chat_member", kwargs))
        return True

    async def unban_chat_member(self, **kwargs):
        self.calls.append(("unban_chat_member", kwargs))
        return True

    async def approve_chat_join_request(self, **kwargs):
        self.calls.append(("approve_chat_join_request", kwargs))
        return True


class FakeApplication:
    def __init__(self, config: Any):
        self.bot_data: dict[str, Any] = {"config": config}


class FakeContext:
    """Stand-in for telegram.ext.ContextTypes.DEFAULT_TYPE."""

    def __init__(self, config: Any, user_data: Optional[dict] = None,
                 args: Optional[list] = None):
        self.application = FakeApplication(config)
        self.bot_data = self.application.bot_data
        self.bot = FakeBot()
        self.user_data: dict = {} if user_data is None else user_data
        self.args = args or []


class FakeSheetsService:
    """In-memory Sheets service capturing rows — used for persist_member tests.

    Mirrors the schema-aware surface persist_member depends on:
    ensure_header / find_row_by_telegram_id / append_member_row / update_member_row.
    Captures rows keyed by Telegram ID so idempotency (upsert) is observable.
    """

    def __init__(self):
        self.rows: dict[int, dict] = {}
        self.header_calls = 0
        self.appends = 0
        self.updates = 0

    def ensure_header(self) -> None:
        self.header_calls += 1

    def find_row_by_telegram_id(self, tid: int):
        return tid if tid in self.rows else None

    def append_member_row(self, record: Mapping[str, str]) -> None:
        tid = int(record[schema.KEY_COLUMN])
        assert tid not in self.rows, "append must not duplicate an existing row"
        self.rows[tid] = dict(record)
        self.appends += 1

    def update_member_row(self, tid: int, record: Mapping[str, str]) -> None:
        self.rows[tid] = dict(record)
        self.updates += 1

    def flag_needs_reconciliation(self, tid: int) -> bool:
        return tid in self.rows
