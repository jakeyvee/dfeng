"""Application builder and runner.

Builds the python-telegram-bot :class:`Application`, stores the config, registers
all handlers, installs a global error handler, and runs in either long-polling
(default) or webhook mode based on ``config.run_mode``.
"""

from __future__ import annotations

import html
import traceback

from telegram import Update
from telegram.ext import Application, ContextTypes

from .config import Config
from .handlers import register_handlers
from .handlers.base import CONFIG_KEY
from .logging_setup import get_logger, log_event

# Updates we ask Telegram to deliver. CHAT_MEMBER is NOT included by default by
# Telegram, so we must request it explicitly to detect invite-link joins.
ALLOWED_UPDATES = [
    Update.MESSAGE,
    Update.EDITED_MESSAGE,
    Update.CALLBACK_QUERY,
    Update.CHAT_MEMBER,
    Update.MY_CHAT_MEMBER,
    # VOL-202: invite-only links with creates_join_request=true emit join
    # requests carrying the invite_link we map back to an entry source.
    Update.CHAT_JOIN_REQUEST,
]


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler so one bad update never crashes the bot.

    Logs structured error context. Future tickets may additionally notify an
    admin chat here.
    """

    err = context.error
    tb = "".join(traceback.format_exception(type(err), err, err.__traceback__)) if err else ""
    upd = update if isinstance(update, Update) else None
    log_event(
        "error",
        upd,
        level=40,  # logging.ERROR
        error_type=type(err).__name__ if err else "unknown",
        error=html.unescape(str(err)) if err else "",
        # Truncate traceback to keep log lines bounded.
        traceback=tb[-2000:],
    )


async def _post_init(application: Application) -> None:
    """Start the Sheets write-queue worker once the event loop is running (VOL-206).

    The queue routes onboarding's ``persist_member`` writes through a resilient
    async layer (retries + backoff + dead-letter) so a Sheets outage never blocks
    onboarding. Stored in ``bot_data`` so handlers (onboarding, ``/sheets_status``)
    can reach it. No-op-safe when Sheets is the Null service.
    """

    from .services.write_queue import WRITE_QUEUE_KEY, build_write_queue

    config: Config = application.bot_data[CONFIG_KEY]
    if not config.write_queue.enabled:
        return
    queue = build_write_queue(config)
    application.bot_data[WRITE_QUEUE_KEY] = queue
    queue.start()


async def _post_shutdown(application: Application) -> None:
    """Drain + stop the write-queue worker on a clean shutdown (VOL-206)."""

    from .services.write_queue import WRITE_QUEUE_KEY

    queue = application.bot_data.get(WRITE_QUEUE_KEY)
    if queue is not None:
        await queue.stop(drain=True)


def build_application(config: Config) -> Application:
    """Construct and configure the Application (without running it)."""

    application = (
        Application.builder()
        .token(config.bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    # Make config available to every handler via context.application.bot_data.
    application.bot_data[CONFIG_KEY] = config

    register_handlers(application, config)
    application.add_error_handler(error_handler)
    return application


def run(config: Config) -> None:
    """Build and run the bot in the configured mode (blocking)."""

    log = get_logger()
    application = build_application(config)

    if config.run_mode == "webhook":
        if not config.webhook.url:
            raise RuntimeError("DFENG_RUN_MODE=webhook but DFENG_WEBHOOK_URL is empty")
        log.info(
            "starting_webhook",
            extra={
                "action": "starting_webhook",
                "listen": config.webhook.listen,
                "port": config.webhook.port,
            },
        )
        application.run_webhook(
            listen=config.webhook.listen,
            port=config.webhook.port,
            webhook_url=config.webhook.url,
            secret_token=config.webhook.secret_token or None,
            allowed_updates=ALLOWED_UPDATES,
            drop_pending_updates=True,
        )
    else:
        log.info("starting_polling", extra={"action": "starting_polling"})
        application.run_polling(
            allowed_updates=ALLOWED_UPDATES,
            drop_pending_updates=True,
        )
