"""Structured logging configuration and the :func:`log_event` helper.

Two output formats are supported, selected via ``DFENG_LOG_FORMAT``:

    * ``kv``   -> ``2026-05-31T... INFO action=ping telegram_id=42 ...``
    * ``json`` -> one JSON object per line (good for log aggregators)

All event logging should go through :func:`log_event` so that the same context
fields (telegram_id, username, update_type, thread_id, action, error) appear
consistently across every handler.

PII / secrets convention for later tickets:
    Do NOT log message bodies, tokens, or personal data by default. Log IDs and
    actions. If a field may contain PII, omit it or hash it before logging.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

# Telegram objects are imported lazily-typed only; we never hard-require them
# here so this module stays importable without python-telegram-bot installed.
try:  # pragma: no cover - typing convenience
    from telegram import Update
except Exception:  # pragma: no cover
    Update = Any  # type: ignore[assignment, misc]


LOGGER_NAME = "dfeng_bot"

# Reserved LogRecord attributes we must not clobber when injecting extra fields.
_RESERVED = set(logging.makeLogRecord({}).__dict__.keys()) | {"message", "asctime"}


class KeyValueFormatter(logging.Formatter):
    """Render the base message plus any ``extra`` structured fields as key=value."""

    def format(self, record: logging.LogRecord) -> str:
        base = f"{self.formatTime(record)} {record.levelname} {record.name}: {record.getMessage()}"
        extras = _extract_extras(record)
        if not extras:
            return base
        kv = " ".join(f"{k}={_render_scalar(v)}" for k, v in extras.items())
        return f"{base} {kv}"


class JsonFormatter(logging.Formatter):
    """Render each record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update(_extract_extras(record))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def _extract_extras(record: logging.LogRecord) -> dict[str, Any]:
    return {
        k: v
        for k, v in record.__dict__.items()
        if k not in _RESERVED and not k.startswith("_")
    }


def _render_scalar(value: Any) -> str:
    text = "null" if value is None else str(value)
    # Quote values containing spaces so key=value parsing stays unambiguous.
    if any(c.isspace() for c in text):
        return json.dumps(text, ensure_ascii=False)
    return text


def configure_logging(level: str = "INFO", fmt: str = "kv") -> None:
    """Configure the root logger once at startup.

    Args:
        level: Logging level name (e.g. ``"INFO"``).
        fmt: ``"kv"`` (default) or ``"json"``.
    """

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter() if fmt == "json" else KeyValueFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Quiet noisy third-party loggers; surface our own at the configured level.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)


def get_logger() -> logging.Logger:
    """Return the project logger."""
    return logging.getLogger(LOGGER_NAME)


def context_from_update(update: Optional["Update"]) -> dict[str, Any]:
    """Extract standard, non-PII context fields from a Telegram update.

    Returns telegram_id, username, update_type, chat_id, and thread_id when
    available. Username is included as it is a public handle (not sensitive
    PII like phone/email); omit message text deliberately.
    """

    if update is None:
        return {}

    fields: dict[str, Any] = {}
    user = getattr(update, "effective_user", None)
    if user is not None:
        fields["telegram_id"] = getattr(user, "id", None)
        if getattr(user, "username", None):
            fields["username"] = user.username

    chat = getattr(update, "effective_chat", None)
    if chat is not None:
        fields["chat_id"] = getattr(chat, "id", None)

    message = getattr(update, "effective_message", None)
    thread_id = getattr(message, "message_thread_id", None) if message else None
    if thread_id is not None:
        fields["thread_id"] = thread_id

    fields["update_type"] = _classify_update(update)
    return fields


def _classify_update(update: "Update") -> str:
    if getattr(update, "callback_query", None) is not None:
        return "callback_query"
    if getattr(update, "chat_member", None) is not None:
        return "chat_member"
    if getattr(update, "my_chat_member", None) is not None:
        return "my_chat_member"
    message = getattr(update, "effective_message", None)
    if message is not None:
        if getattr(message, "new_chat_members", None):
            return "new_chat_members"
        if getattr(message, "left_chat_member", None) is not None:
            return "left_chat_member"
        return "message"
    return "unknown"


def log_event(
    action: str,
    update: Optional["Update"] = None,
    *,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Log a structured event.

    Args:
        action: Short verb/identifier for what happened (e.g. ``"ping"``,
            ``"new_member"``, ``"message_received"``).
        update: Optional Telegram update; standard context is auto-extracted.
        level: Logging level (default INFO).
        **fields: Extra structured key=value context (outcome, counts, etc.).
            Do NOT pass message bodies or secrets.

    Example:
        >>> log_event("ping", update, outcome="replied", thread_id=5)
    """

    payload: dict[str, Any] = {"action": action}
    payload.update(context_from_update(update))
    # Explicit fields win over auto-extracted ones.
    payload.update(fields)
    get_logger().log(level, action, extra=payload)
