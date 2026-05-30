"""Entrypoint: ``python -m dfeng_bot.main``.

Loads config from the environment, configures structured logging, and starts
the bot. Keep this thin — orchestration lives in ``app.py``.
"""

from __future__ import annotations

import sys

from .app import run
from .config import Config, ConfigError
from .logging_setup import configure_logging, get_logger


def main() -> int:
    try:
        config = Config.from_env()
    except ConfigError as exc:
        # Logging may not be configured yet; print to stderr and exit non-zero.
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    configure_logging(level=config.log_level, fmt=config.log_format)
    log = get_logger()
    log.info("startup", extra={"action": "startup", **config.safe_summary()})

    try:
        run(config)
    except KeyboardInterrupt:  # pragma: no cover - manual shutdown
        log.info("shutdown", extra={"action": "shutdown", "reason": "keyboard_interrupt"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
