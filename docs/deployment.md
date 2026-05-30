# Deployment & Operations — Dongfeng Experience Community bot

## 1. Prerequisites

- Python 3.11+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- A test supergroup with **Topics (forum mode) enabled** and the bot added as an
  **administrator** (admin rights are required to receive `chat_member` updates
  and, later, to moderate)

## 2. Local development

```bash
# 1. Create a virtualenv (Python 3.11+)
python3.11 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure secrets
cp .env.example .env
#   then edit .env and set at least:
#     TELEGRAM_BOT_TOKEN   (from BotFather)
#     DFENG_GROUP_ID       (your test supergroup chat id, e.g. -1001234567890)
#     DFENG_TOPIC_*        (message_thread_id of each topic; see below)
#     DFENG_ADMIN_IDS      (your own Telegram user id)

# 4. Run (long-polling, default)
python -m dfeng_bot.main
```

`.env` is gitignored. Never commit real tokens.

### Finding chat / topic / user IDs

- **Group chat id**: temporarily add `@RawDataBot` or check the bot logs — every
  update is logged with `chat_id`.
- **Topic (thread) ids**: post a message in each topic; the structured logs print
  `thread_id=<n>` for that topic. Put those numbers in the `DFENG_TOPIC_*` vars.
- **Your user id**: message `@userinfobot`, or read `telegram_id` from the logs.

### Smoke test (acceptance criteria)

1. Send `/ping` inside any topic → the bot replies **in that same topic** with
   `pong (thread_id=<n>)`. This proves thread-context read + in-thread reply.
2. Add a new member (or have someone join) → logs show
   `action=new_member ... member_id=<id>` and `action=new_member_hook`.

## 3. Run modes: polling vs webhook

Selected via `DFENG_RUN_MODE`.

### Long-polling (default, recommended for v1)
- No public URL or TLS needed. Simplest for dev and small-scale prod.
- The bot pulls updates from Telegram. Run as a single long-lived process
  (systemd unit, container, etc.). Do **not** run two pollers on the same token.

```bash
DFENG_RUN_MODE=polling python -m dfeng_bot.main
```

### Webhook (optional, for scale / serverless-ish deploys)
- Telegram pushes updates to a public HTTPS endpoint you host.
- Requires a public URL with valid TLS (terminate TLS at a reverse proxy/LB and
  forward to the bot's listen port).

```bash
DFENG_RUN_MODE=webhook \
DFENG_WEBHOOK_URL=https://bot.example.com/telegram \
DFENG_WEBHOOK_PORT=8443 \
DFENG_WEBHOOK_SECRET_TOKEN=$(openssl rand -hex 16) \
python -m dfeng_bot.main
```

`DFENG_WEBHOOK_SECRET_TOKEN` is echoed by Telegram in the
`X-Telegram-Bot-Api-Secret-Token` header and verified by PTB, rejecting forged
requests.

## 4. Secrets handling

- Local: `.env` (gitignored). Production: inject env vars via your platform's
  secret manager (e.g. systemd `EnvironmentFile` with `0600` perms, container
  secrets, cloud secret store). Never bake secrets into the image or repo.
- The Google service-account JSON (`GOOGLE_APPLICATION_CREDENTIALS`, used by
  later Sheets tickets) is gitignored (`*.json`). Mount it at runtime.
- `config.safe_summary()` is the only config view that should be logged — it
  redacts the token and credentials.

## 5. Production process

Run as a restart-on-failure service. Example systemd unit:

```ini
[Unit]
Description=Dongfeng Experience Community bot
After=network-online.target

[Service]
WorkingDirectory=/opt/dfeng-bot
EnvironmentFile=/opt/dfeng-bot/.env
ExecStart=/opt/dfeng-bot/.venv/bin/python -m dfeng_bot.main
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

The global error handler keeps a single bad update from crashing the process;
`Restart=always` covers the rest.

## 6. Logging

- Structured: `DFENG_LOG_FORMAT=kv` (default) or `json` for aggregators.
- Level via `DFENG_LOG_LEVEL` (`INFO` default).
- **Convention:** never log message bodies, tokens, or PII (phone/email). Log
  IDs, actions, and outcomes only.
