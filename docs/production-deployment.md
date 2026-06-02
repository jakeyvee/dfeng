# Production Deployment Runbook — Dongfeng Experience Community bot (VOL-213)

Operator runbook to deploy the bot against the **live** Dongfeng Experience
Community supergroup, securely, with monitoring and a fast rollback. This is the
production counterpart to `docs/deployment.md` (which covers local dev + the
polling/webhook basics).

**Who runs this:** the **L3 (Management) / Owner** who controls bot config and
the Google Sheets workbook (per `docs/telegram-setup.md` §9 and
`docs/moderation-runbook.md` §4).

Cross-references:
- Supergroup + bot admin rights → `docs/telegram-setup.md`
- Google workbook + service account → `docs/google-sheets-setup.md`
- Kill-switch flags + raid playbook → `docs/moderation-runbook.md` §6
- Dev basics, polling vs webhook → `docs/deployment.md`
- Smoke test after deploy → `docs/launch-smoke-test.md`

---

## 1. Prerequisites

Before deploying, all of these must be DONE:

- [ ] **Supergroup provisioned** (VOL-196): six topics, bot promoted to admin
      with the required rights (§5 below). Real IDs recorded in the gitignored
      `config/group-setup.yaml`.
- [ ] **Google workbook + service account** provisioned (VOL-198): `Members` tab
      with the canonical 12-column header, workbook shared with the service
      account as Editor, JSON key downloaded and kept secret.
- [ ] A **production host** with either Docker (+ Compose) **or** Python 3.11+
      and systemd. The host runs **exactly one** bot instance (never two pollers
      on the same token).
- [ ] You can read the host's process logs (journald or `docker logs`).

---

## 2. Secret provisioning (NEVER committed)

Two secrets and a set of sensitive IDs must reach the bot **only** at runtime,
never via source control:

| Secret / sensitive value | Env key | How to provision |
|---|---|---|
| Telegram bot token | `TELEGRAM_BOT_TOKEN` | Secret manager / env var. From @BotFather. |
| Google service-account JSON | `GOOGLE_APPLICATION_CREDENTIALS` | A **PATH** to a mounted read-only JSON file **or** the raw JSON as the value. |
| Workbook id | `DFENG_SHEETS_WORKBOOK_ID` | From `docs/google-sheets-setup.md`. |
| Group + six topic IDs | `DFENG_GROUP_ID`, `DFENG_TOPIC_*` | From `config/group-setup.yaml` (VOL-196). |
| Admin Telegram IDs | `DFENG_ADMIN_IDS` | From `config/group-setup.yaml` `admins:` register. |
| Invite links | `DFENG_INVITE_LINK_*` | Join-grant secrets (VOL-202). |
| Webhook secret (webhook mode only) | `DFENG_WEBHOOK_SECRET_TOKEN` | `openssl rand -hex 16`. |

**The rule:** the repo only ever contains `*.example` templates with
`<PLACEHOLDER>` values. Real values live in:
- `.env.production` (gitignored — copied from `.env.production.example`), and
- the mounted Google creds JSON (gitignored: `*.json` / `service-account*.json`).

Verify nothing real is tracked before/after deploy:

```bash
git check-ignore .env.production secrets/google-creds.json   # both must print
git status --porcelain | grep -E '\.env\.production$|\.json$' # must be empty
```

### Choosing a secret mechanism

1. **Mounted secret file (recommended for Docker)** — keep the Google JSON on the
   host (e.g. `./secrets/google-creds.json`, gitignored), mount it **read-only**
   into the container at the path `GOOGLE_APPLICATION_CREDENTIALS` points to.
   `docker-compose.yml` already does this. The token + IDs come from
   `env_file: .env.production`.
2. **systemd `EnvironmentFile`** — put `.env.production` at
   `/opt/dfeng-bot/.env.production` with `chmod 0600`, owned by the `dfeng` user;
   keep the Google JSON as a separate `0600` file the user can read.
3. **Cloud secret manager** — inject the same keys as env vars at container
   start (AWS Secrets Manager / GCP Secret Manager / Doppler / etc.). For the
   Google creds you may pass the **raw JSON** as the value of
   `GOOGLE_APPLICATION_CREDENTIALS` (the Sheets client accepts a path OR raw JSON).

`config.safe_summary()` (logged at startup) redacts the token and credentials —
it is the only config view that should ever be logged.

---

## 3. Fill in the production config

```bash
cp .env.production.example .env.production
# edit .env.production and replace every <PLACEHOLDER>
```

Transcribe from `config/group-setup.yaml` (VOL-196), minding the topic mapping
(`docs/telegram-setup.md` §4 — display name → env key):

| # | Topic (display name)   | Env key                     |
|---|------------------------|-----------------------------|
| 1 | Announcements & Events | `DFENG_TOPIC_ANNOUNCEMENTS`  |
| 2 | BOX Owners Lounge      | `DFENG_TOPIC_BOX`           |
| 3 | 007 Owners Club        | `DFENG_TOPIC_007`           |
| 4 | VIGO Owners Circle     | `DFENG_TOPIC_VIGO`          |
| 5 | General Community Chat | `DFENG_TOPIC_GENERAL` (= `1`, built-in General) |
| 6 | Support & Assistance   | `DFENG_TOPIC_SUPPORT`        |
| – | (welcome post target)  | `DFENG_WELCOME_TOPIC` (`0` = General) |

Then set the Sheets workbook id + creds path, `DFENG_ADMIN_IDS`, trust threshold,
spam/flood thresholds, and confirm the **launch feature flags** (§4).

### Launch feature-flag matrix (what `.env.production.example` sets)

| Flag | Env key | Prod | Code default | Why |
|---|---|:--:|:--:|---|
| Welcome | `DFENG_FEATURE_WELCOME` | ON | ON | onboarding |
| Qualification | `DFENG_FEATURE_QUALIFICATION` | ON | ON | tag flow |
| Optional capture | `DFENG_FEATURE_OPTIONAL_CAPTURE` | ON | ON | PDPA-gated phone/plate |
| Support redirect | `DFENG_FEATURE_SUPPORT_REDIRECT` | ON | ON | route support questions |
| Sheets | `DFENG_FEATURE_SHEETS` | ON | OFF | enable real member writes |
| Write queue | `DFENG_WRITE_QUEUE_ENABLED` | ON | ON | resilient writes |
| Metrics | `DFENG_METRICS_ACTIVITY` | ON | ON | launch metrics |
| **Anti-spam** | `DFENG_FEATURE_ANTISPAM` | **ON** | **OFF** | PRD: anti-spam live day one |
| **Flood control** | `DFENG_FEATURE_FLOOD_CONTROL` | **ON** | **OFF** | rate-limit raids |
| **Link restrictions** | `DFENG_FEATURE_LINK_RESTRICTIONS` | **ON** | **OFF** | block new-user link spam |

> **Why the moderation flags default OFF in code but ON in prod:** anti-spam,
> flood control, and link restrictions **delete / mute / restrict** members. They
> ship dark so a fresh checkout (or a dev/test run) never moderates a real group
> by accident. The PRD requires anti-spam active at launch, so production
> explicitly turns all three ON. They are the documented **kill-switches**: to
> disable one fast during an incident, flip it to `0` and restart — no redeploy
> (§9 and `docs/moderation-runbook.md` §6).

---

## 4. Polling vs webhook (default polling for v1)

Selected via `DFENG_RUN_MODE` (see also `docs/deployment.md` §3).

- **Polling (default, recommended for v1):** no public URL/TLS; the bot pulls
  updates. Just run the single process. Keep `DFENG_RUN_MODE=polling`.
- **Webhook (optional, scale):** Telegram pushes to a public HTTPS endpoint.
  Requires a public URL with valid TLS (terminate at a reverse proxy/LB, forward
  to the listen port). Set:
  - `DFENG_RUN_MODE=webhook`
  - `DFENG_WEBHOOK_URL` (public https URL)
  - `DFENG_WEBHOOK_LISTEN` (default `0.0.0.0`), `DFENG_WEBHOOK_PORT` (default 8443)
  - `DFENG_WEBHOOK_SECRET_TOKEN` (`openssl rand -hex 16`) — Telegram echoes it in
    `X-Telegram-Bot-Api-Secret-Token`; PTB verifies and rejects forged calls.

  In Docker, publish the port (uncomment `ports:` in `docker-compose.yml`).

---

## 5. Grant + verify the bot's Telegram admin rights

The bot must be a group **administrator** with the rights from
`docs/telegram-setup.md` §7. Grant the **whole set** (do not narrow per-command):

| Bot admin right | Powers |
|---|---|
| **Delete Messages** | welcome cleanup, anti-spam/flood/link deletes, `/del` |
| **Ban / Restrict Members** | mute/restrict (flood, spam escalation), `/mute` `/ban` |
| **Pin Messages** | `/pin`, pin announcements |
| **Manage Topics** | act inside forum topics; create/close/reopen |
| **Invite Users via Link** | approve join requests (`/approve`, onboarding) |

It also needs to **reply in topic threads** (welcome + redirects post into the
originating `message_thread_id`) and post the welcome — covered by being an admin
member that can send messages in the open topics.

**Graceful degradation (already implemented):** if a right is missing, the
affected command/automation logs `outcome=...failed` and (for commands) replies a
friendly "the bot may be missing the '<right>' admin right" message — it never
crashes (`docs/moderation-runbook.md` §2). So a missing right degrades that one
feature, it does not take the bot down.

**Verify after start:** `/ping` in a topic replies `pong (thread_id=<n>)` in that
same thread (proves thread read + reply). Then run the full
`docs/launch-smoke-test.md`.

---

## 6. Start the bot

### Option A — Docker (recommended)

```bash
cp .env.production.example .env.production    # fill in real values
mkdir -p secrets && cp /path/to/google-key.json secrets/google-creds.json  # gitignored
docker compose up -d --build
docker compose logs -f                        # watch startup
```

`restart: unless-stopped` recovers from crashes and host reboots. The creds JSON
is mounted **read-only** at the path `GOOGLE_APPLICATION_CREDENTIALS` points to.

### Option B — systemd (simple host)

```bash
sudo useradd -r -s /usr/sbin/nologin dfeng       # once
sudo mkdir -p /opt/dfeng-bot && sudo chown dfeng:dfeng /opt/dfeng-bot
# deploy the repo to /opt/dfeng-bot, create the venv + install:
python3.11 -m venv /opt/dfeng-bot/.venv
/opt/dfeng-bot/.venv/bin/pip install -r /opt/dfeng-bot/requirements.txt
# place secrets (0600, owned by dfeng):
sudo install -o dfeng -g dfeng -m 0600 .env.production /opt/dfeng-bot/.env.production
# install + start the unit:
sudo cp deploy/systemd/dfeng-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now dfeng-bot
journalctl -u dfeng-bot -f
```

### Option C — Procfile / PaaS

`Procfile` declares one `worker` process. Set the same env keys as
`.env.production.example` via the platform's config/secret store, ensure
`PYTHONPATH` includes `src/` (or `pip install .`), and scale the worker to
**exactly 1**.

On a clean start the logs show `action=startup` with the redacted
`safe_summary()` (features, topic ids, admin count), then
`action=starting_polling`.

---

## 7. Logs — where they go & how to access

The bot writes **structured logs to stdout/stderr** (`DFENG_LOG_FORMAT=kv`
default, or `json` for aggregators). No log files are written by the app.

| Deploy | Access logs |
|---|---|
| Docker | `docker compose logs -f` (or `docker logs -f dfeng-bot`) |
| systemd | `journalctl -u dfeng-bot -f` |
| PaaS | the platform's log viewer / drain |

Compose caps log size (`max-size: 10m`, `max-file: 5`); journald rotates per host
policy. Never log message bodies/PII — only ids, actions, outcomes (enforced in
code via `log_event`).

---

## 8. What to monitor + v1 alerting

**Watch for these (highest signal first):**

| Signal | Log pattern | Meaning / action |
|---|---|---|
| Write-queue exhaustion | `action=member_persist_exhausted` / `NEEDS_RECONCILIATION` | a member row dead-lettered after retries — run `/reconcile`, fix Sheets, re-add. |
| Reconciliation needed | `needs_reconciliation` | same — Sheets write gave up; admin follow-up. |
| Error-level events | `action=error level=ERROR` (or `level=40`) | unexpected exception in a handler. Investigate. |
| Permission failures | `outcome=...failed` | bot missing an admin right (§5) — re-grant. |
| Anti-spam action **rate** | `action=antispam_action` volume | a spike may mean a raid (escalate per runbook §6) or false positives (tune). |
| Flood / link actions | `action=flood_control` / `action=link_restriction` | review for false positives; `/unmute` `/unban` `/trust` as needed. |

Admin in-chat observability (no host access needed): `/sheets_status` (queue
pending/in-flight/dead-letter), `/reconcile` (dead-lettered IDs), `/stats`
(process-lifetime metric counters).

**Lightweight v1 alerting (pick one):**

- **grep + cron** on the host — e.g. a 5-minute cron that greps the last window
  of journald for the critical patterns and emails/Telegrams the owner on a hit:

  ```bash
  # /etc/cron.d/dfeng-alert — check the last 5 min for exhaustion/errors
  */5 * * * * dfeng journalctl -u dfeng-bot --since "-5 min" \
    | grep -E 'member_persist_exhausted|needs_reconciliation|level=ERROR' \
    | grep -q . && echo "dfeng-bot: critical log event" | mail -s "dfeng-bot alert" owner@example.com
  ```

  (Docker equivalent: `docker logs --since 5m dfeng-bot | grep -E ...`.)

- **Log drain** — set `DFENG_LOG_FORMAT=json` and ship stdout to a hosted log
  service (Better Stack / Papertrail / Loki / CloudWatch), then alert on the same
  patterns there. Recommended once volume grows.

A heavier SLA/alerting stack is **out of scope** for v1 (and explicitly out of
scope for this ticket).

---

## 9. Rollback / disable a feature (launch day)

### Stop the bot fast

| Deploy | Command |
|---|---|
| Docker | `docker compose stop` (or `docker compose down` to remove the container) |
| systemd | `sudo systemctl stop dfeng-bot` |
| PaaS | scale the `worker` to 0 |

Stopping leaves the group fully functional; only automation/onboarding pauses.
(The in-memory write queue is lost on stop — accepted v1; affected Telegram IDs
are logged and records are re-derivable. See `.env.example` write-queue notes.)

### Disable a risky feature WITHOUT a redeploy

Every automated subsystem checks its feature flag on each update, so flipping a
flag (in `.env.production`) and restarting cleanly disables it — **no rebuild,
no code change**. These are the kill-switches (`docs/moderation-runbook.md` §6):

```bash
# edit .env.production, set the flag(s) to 0, e.g.:
#   DFENG_FEATURE_ANTISPAM=0          # stop automated spam deletes
#   DFENG_FEATURE_FLOOD_CONTROL=0     # stop rate-based mutes
#   DFENG_FEATURE_LINK_RESTRICTIONS=0 # stop new-user link blocks
#   DFENG_FEATURE_SUPPORT_REDIRECT=0  # stop the support nudge

docker compose up -d            # Docker: re-reads env_file, recreates container
# or
sudo systemctl restart dfeng-bot   # systemd: re-reads EnvironmentFile
```

Config changes (thresholds, flags) take effect only after this restart. To
re-enable, set the flag back to `1` and restart again.

### Roll back to a previous version

Redeploy the previous image tag / git revision and restart. State is in Telegram
+ Google Sheets (not local), so a version rollback loses only the in-memory write
queue (re-derivable). Storage migration is tracked separately (VOL-217).

---

## 10. Post-deploy

1. Run `docs/launch-smoke-test.md` against the live (or staging) group.
2. Confirm the v1 alert (cron/drain) fires on a test pattern.
3. Hand monitoring to the on-call admin (`docs/moderation-runbook.md` §5/§7).

Full end-to-end QA is **VOL-214** — not duplicated here.
