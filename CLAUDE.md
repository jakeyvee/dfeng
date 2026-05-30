# CLAUDE.md — Dongfeng Experience Community bot

Guidance for AI agents and developers extending this repo. **Read this before
implementing a feature ticket.** Foundation laid by VOL-197.

## Tech stack (do not deviate)

- **Python 3.11+**
- **python-telegram-bot v21+** — async `Application` / `ContextTypes` API only.
  No sync API, no other Telegram libraries.
- **gspread + google-auth** — Google Sheets (later tickets). Sync clients; wrap
  calls in `asyncio.to_thread` so they don't block the event loop.
- **python-dotenv** — local `.env` loading only.
- **stdlib `logging`** — structured output via `log_event()`; no extra logging libs.

Dependencies live in `requirements.txt` (canonical) and `pyproject.toml`.

## Architecture

```
main.py  -> Config.from_env() -> configure_logging() -> app.run(config)
app.py   -> build_application(): Application + bot_data[config] + register_handlers + error_handler
handlers/__init__.py -> register_handlers(application, config)   <-- THE extension point
```

- **Config** (`config.py`): one immutable dataclass, built once from env via
  `Config.from_env()`, stored in `application.bot_data["config"]`. Read it in
  handlers with `get_config(context)` (from `handlers/base.py`). Never read
  `os.environ` in handlers.
- **Handlers** live in `handlers/`. Each module owns one concern. `__init__.py`
  wires them up.
- **Services** (`services/`) are interfaces to external systems (Sheets). Depend
  on the interface, not the concrete client.

## How to add a feature ticket

1. Add any new settings as typed fields on the relevant dataclass in
   `config.py`, with sane defaults, and document the env key in `.env.example`.
2. Put logic in a new or existing module under `handlers/` (or `services/`).
3. Register handlers inside `register_handlers()` in `handlers/__init__.py`.
   **Do not edit `app.py`** for features.
4. Gate the feature behind a `FeatureFlags` entry if it should ship dark.
5. Log outcomes with `log_event(action, update, outcome=..., ...)`.

### Handler groups & ordering

PTB runs handlers by ascending **group** number; within a group, the first match
wins (raise `ApplicationHandlerStop` to consume an update). Defined in
`handlers/__init__.py`:

- `GROUP_PREFILTER = -1` — **reserved** for anti-spam / flood control. Register
  these here so they run first and can drop abusive updates.
- `GROUP_COMMANDS = 0` / `GROUP_MEMBERSHIP = 0` — commands, joins, callbacks.
- `GROUP_MESSAGES = 1` — generic message handling (runs after commands).

### Named extension points (where each future ticket plugs in)

| Concern                         | Ticket(s)        | Where to implement                                         |
|---------------------------------|------------------|------------------------------------------------------------|
| Entry-source tracking           | VOL-202 (done)   | `services/entry_source.py` (`resolve_entry_source`); captured in `membership` + `join_request` handlers, stashed in `context.user_data["entry_source"]` |
| Onboarding / welcome            | VOL-203 (done)   | `membership.on_new_member()` -> `welcome.send_welcome()`   |
| Qualification flow              | VOL-204 (done)   | `handlers/qualification.py`; entered via `welcome.start_qualification` or `/qualify`; text fallback in `messages.handle_message`, `qual:`-namespaced callbacks routed from `messages.handle_callback_query`; resolved tag stashed in `context.user_data["tag"]` (`qualification.TAG_KEY`) for VOL-205 |
| PDPA / Sheets persistence       | VOL-198/205/206  | `services/sheets.py` (`build_sheets_service`); call from `on_new_member` |
| Support redirection             | —                | extension point in `messages.handle_message`               |
| Anti-spam                       | VOL-208 (done)   | `handlers/antispam.py`, registered in `GROUP_PREFILTER`     |
| New-user link restriction       | VOL-209 (done)   | `handlers/link_restrictions.py` (`message_has_link` + `is_trusted` + `TrustStore`); prefilter in `GROUP_PREFILTER` after anti-spam; join time recorded via `membership.on_new_member` -> `record_join`; admin `/trust` command |
| Flood control / rate limits     | —                | new module, register in `GROUP_PREFILTER`; thresholds in `config.rate_limits` |
| Admin / moderation commands     | —                | `commands.build_command_handlers()`, gate with `is_admin()` |

## Conventions

- **Replying in-thread:** always reply via `reply_in_thread(update, text, context=context)`
  so messages land in the originating forum topic (`message_thread_id`).
- **Admin checks:** `is_admin(update, context)` before any privileged action.
- **Logging / PII:** use `log_event()`. **Never log** message bodies, tokens, or
  PII (phone/email). Log IDs, usernames (public handles), actions, and outcomes.
  `config.safe_summary()` is the only safe way to log config.
- **Secrets:** `.env` and `*.json` creds are gitignored. Only `.env.example`
  (placeholders) is committed. Inject real secrets via env in production.
- **Allowed updates:** `chat_member` is requested explicitly in `app.ALLOWED_UPDATES`.
  If you need a new update type delivered, add it there.
- **Import-clean:** every module must import without side effects beyond
  optional `.env` loading. Verify with `python -m py_compile` / `python -c "import ..."`.

## Running & testing

See `README.md` (quick start) and `docs/deployment.md` (full guide, polling vs
webhook, secrets). Smoke test: `/ping` replies in-thread; a member join logs
`action=new_member` followed by `action=welcome_sent`.

### Welcome onboarding (VOL-203)

`handlers/welcome.py` posts a single welcome (`WELCOME_MESSAGE`, the verbatim
six-topic copy) on each new member join. Where it posts: joins are observed in
the forum's "General" topic, so by default the welcome replies there; if
`DFENG_TOPIC_WELCOME` (`config.topics.welcome`) is set (> 0) it posts into that
welcome topic instead. Gated by `DFENG_FEATURE_WELCOME` (default ON). Duplicate
join signals are deduped per-process via an in-memory `{telegram_id: ts}` map
with a 10-minute TTL (`DEDUPE_TTL_SECONDS`) — single-instance only. After
welcoming it calls `welcome.start_qualification()`, the no-op hand-off seam
VOL-204 fills in (currently logs `qualification_pending`).
