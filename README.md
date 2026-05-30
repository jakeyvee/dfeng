# Dongfeng Experience Community Bot

A private, invite-only Telegram supergroup bot for **Dongfeng Singapore**'s
experience community. This repository is the bot's runtime foundation (Linear
**VOL-197**); onboarding, qualification, PDPA persistence, anti-spam, flood
control, and moderation ship in later tickets on top of this scaffold.

## What this foundation provides

- Async **python-telegram-bot v21+** `Application` runtime
- Deployable as **long-polling** (default) or **webhook**, selected via config
- Typed `Config` dataclass loaded from environment variables
- Central `register_handlers()` dispatcher with clear extension points
- New-member join detection (service messages **and** `chat_member` updates)
- A `/ping` health command that replies **in the same topic/thread**
- Structured logging via `log_event(...)` (key=value or JSON)
- Global error handler so one bad update never crashes the bot

## Quick start

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then edit: token, group id, topic ids, admin ids
python -m dfeng_bot.main
```

Then in your test supergroup, send `/ping` inside a topic — the bot replies
`pong (thread_id=<n>)` in that same topic.

See **[docs/deployment.md](docs/deployment.md)** for full setup, finding chat /
topic / user IDs, polling-vs-webhook, and production deployment.

## Project layout

```
src/dfeng_bot/
  config.py          # typed Config dataclass loaded from env
  logging_setup.py   # structured logging + log_event() helper
  app.py             # builds Application, error handler, runs polling/webhook
  main.py            # entrypoint: python -m dfeng_bot.main
  handlers/
    __init__.py      # register_handlers(application, config) dispatcher
    base.py          # reply_in_thread(), is_admin(), get_config()
    membership.py    # new-member join handling + on_new_member() hook
    messages.py      # generic message + callback-query handlers
    commands.py      # /start, /ping, /health
  services/
    sheets.py        # Google Sheets interface PLACEHOLDER (later tickets)
docs/deployment.md   # local dev + production deployment
CLAUDE.md            # stack, conventions, how to extend (read before adding features)
```

## Configuration

All settings come from environment variables (loaded from `.env` locally). Every
key is documented in **[.env.example](.env.example)**. Secrets are never
committed — `.env` and `*.json` credentials are gitignored.

## Extending the bot

Add feature handlers via `register_handlers()` in `src/dfeng_bot/handlers/` —
never edit `app.py` for features. The named extension points (onboarding,
qualification, Sheets persistence, support redirection, anti-spam, link
restrictions, flood control, admin commands) are documented inline and in
**CLAUDE.md**. Read CLAUDE.md before adding a feature ticket.
