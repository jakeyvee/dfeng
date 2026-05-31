# Dongfeng Experience Community Bot

A private, invite-only **Telegram supergroup bot** for **Dongfeng Singapore**'s
owner + prospect community (BOX, 007, VIGO). The bot welcomes new members, tags
them as owners or prospects, stores members in a Google Sheet, redirects support
questions, blocks spam, and gives admins moderation tools.

This repository contains the **complete v1 launch build**. The code is done and
tested; what remains is the **real-world setup** an operator must do once
(create the Telegram group, the Google Sheet, and deploy the bot). Those steps
are listed below and in the linked guides.

- 👉 **Going live?** Start with **[Part A – Set-up guide](#part-a--set-up-guide-for-the-person-deploying-the-bot)**.
- 👉 **Running the community day-to-day (e.g. Lucia)?** Go straight to
  **[Part B – Maintaining guide](#part-b--maintaining-guide-for-non-technical-admins)**.

---

## What the bot does

| Capability | What members experience | Docs |
|---|---|---|
| Welcome | New joiners get a friendly message pointing to the six topics | (VOL-203) |
| Qualification | Bot asks "Owner or Prospect?" → model, and tags them | (VOL-204) |
| Member record | Saves each member to a Google Sheet (optional phone/plate, PDPA-gated) | `docs/google-sheets-setup.md`, `docs/pdpa-policy.md` |
| Support routing | Support keywords get nudged to **Support & Assistance** | (VOL-207) |
| Anti-spam | Auto-removes crypto/ads/scam-link/repeat spam | (VOL-208) |
| New-user link block | New members can't post links until trusted | (VOL-209) |
| Flood control | Rate-limits message floods across all topics | (VOL-210) |
| Admin tools | `/pin /del /mute /ban /approve …` for moderators | `docs/moderation-runbook.md` |
| Metrics | Lightweight launch metrics from logs + the sheet | `docs/metrics-and-reporting.md` |

### Where to find each guide

| You want to… | Read |
|---|---|
| Create the Telegram group + topics | `docs/telegram-setup.md` |
| Apply the avatar + pinned messages | `docs/apply-branding-runbook.md` (copy in `content/pinned-messages.md`) |
| Create the Google Sheet + service account | `docs/google-sheets-setup.md` |
| Make the six entry links + QR codes | `docs/entry-links.md` (`scripts/generate_qr.py`) |
| Deploy the bot to a server | `docs/production-deployment.md` |
| Test everything before launch | `docs/launch-smoke-test.md`, `docs/qa-checklist.md` |
| Onboard the admin team | `docs/admin-onboarding.md` |
| Moderate day-to-day | `docs/moderation-runbook.md` |
| Seed week-one conversation | `docs/launch-seeding-plan.md`, `content/seed-content-calendar.md` |
| PDPA / data rules | `docs/pdpa-policy.md` |
| Plan for growth beyond ~1,500 members | `docs/storage-scaling-plan.md` |
| Tone of voice | `docs/tone-guide.md` |

---

## Remaining steps to go live

The code is complete and tested. These are the **real-world actions** that must
be done by a person with the right accounts — the bot cannot do them itself.
Do them roughly in this order. (Owner = who should do it.)

1. **Create the bot account** — in Telegram, message **@BotFather**, run
   `/newbot`, and copy the **bot token**. *(Owner: technical/L3)*
2. **Create the supergroup + six topics** — follow **`docs/telegram-setup.md`**:
   turn on Topics, create the six topics with exact names, make it private/
   invite-only, lock **Announcements & Events** to admins, and add the bot as an
   admin with the listed rights. Record the **group ID** and the **six topic
   (thread) IDs** into `config/group-setup.yaml`. *(Owner: technical/L3)*
3. **Apply branding + pin messages** — follow **`docs/apply-branding-runbook.md`**
   using the approved copy in `content/pinned-messages.md`. *(Owner: L1, e.g. Lucia)*
   - ⚠️ Needs the **group avatar image** from stakeholders (square, 512×512 px)
     and a final brand-colour decision — both currently open (see
     `docs/branding-assets.md`).
4. **Create the Google Sheet + service account** — follow
   **`docs/google-sheets-setup.md`**: make the workbook with the header row,
   create a Google Cloud service account, download its JSON key, share the
   workbook with the service-account email **and** with named admins. *(Owner: technical/L3)*
5. **Create the six entry links + QR codes** — follow **`docs/entry-links.md`**;
   run `scripts/generate_qr.py` to make the showroom/roadshow/event QR images;
   set up the Linktree button and note the website placeholder. *(Owner: L1 + technical)*
6. **Deploy the bot** — follow **`docs/production-deployment.md`**: copy
   `.env.production.example` → `.env.production`, fill in the token, IDs, admin
   IDs and Google credentials, then start it (Docker or systemd). The launch
   feature flags (incl. anti-spam, flood control, link restrictions) are already
   switched **on** in that template. *(Owner: technical/L3)*
7. **Smoke-test in the live/staging group** — run **`docs/launch-smoke-test.md`**
   and clear risks **R1/R2** in `docs/qa-checklist.md`. *(Owner: technical + L1)*
8. **Onboard the admin team** — follow **`docs/admin-onboarding.md`**: promote
   Lucia (L1) and Travis (L2) in Telegram, share the sheet with their Google
   accounts, and **confirm the L3 owner + 1–3 extra reps** (currently TBC). *(Owner: L3)*
9. **PDPA sign-off** — get the responsible stakeholder to confirm the consent
   wording and retention rules in `docs/pdpa-policy.md` (open items listed there). *(Owner: L3/compliance)*
10. **Seed week one** — load the prompts in `content/seed-content-calendar.md`
    and assign owner seeders per `docs/launch-seeding-plan.md`. *(Owner: L1)*

> Outstanding stakeholder inputs (not blockers for the code, but needed before a
> polished launch): **group avatar asset**, **brand-colour lock**, **named L3
> owner + extra moderators**, **PDPA final sign-off**. All are tracked as launch
> risks in the relevant docs.

---

## Part A — Set-up guide (for the person deploying the bot)

This is the condensed end-to-end path. Each step links to the full doc.

### A1. Prerequisites
- A Telegram account (to create the bot and the group).
- A Google account / Google Cloud access (for the member sheet).
- A small always-on Linux server **or** Docker host to run the bot.
- This repository.

### A2. Run it locally first (optional but recommended)
```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # edit: TELEGRAM_BOT_TOKEN, DFENG_GROUP_ID, DFENG_TOPIC_*, DFENG_ADMIN_IDS
python -m dfeng_bot.main
```
In a test supergroup, send `/ping` inside a topic — the bot replies
`pong (thread_id=<n>)` in that same topic. See **`docs/deployment.md`** for how
to find chat/topic/user IDs and polling-vs-webhook.

### A3. Provision the real services
1. **Telegram group** → `docs/telegram-setup.md` (records IDs into `config/group-setup.yaml`).
2. **Pinned messages + avatar** → `docs/apply-branding-runbook.md`.
3. **Google Sheet + service account** → `docs/google-sheets-setup.md`.
4. **Entry links + QR** → `docs/entry-links.md` + `scripts/generate_qr.py`.

### A4. Deploy to production
Follow **`docs/production-deployment.md`**. In short:
```bash
cp .env.production.example .env.production   # fill in ALL secrets + IDs (never commit this file)
docker compose up -d                         # or use deploy/systemd/dfeng-bot.service
```
Confirm the bot has its Telegram admin rights (delete, restrict/mute, ban, pin,
manage topics, approve join requests).

### A5. Verify and hand off
- Run **`docs/launch-smoke-test.md`** (welcome, qualification, sheet write,
  support redirect, spam removal, link block, flood control, an admin command,
  `/sheets_status`, `/stats`).
- Review **`docs/qa-checklist.md`** (decision: GO-WITH-RISKS) and clear R1/R2.
- Hand the team over with **`docs/admin-onboarding.md`**.

### A6. Run the tests (developers)
```bash
PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```
All 73 tests should pass. The bot is configured entirely by environment
variables documented in `.env.example` / `.env.production.example`; secrets are
never committed (`.env*`, `*.json` keys, and filled `config/*.yaml` are
gitignored).

---

## Part B — Maintaining guide (for non-technical admins)

**For Lucia and the moderation team.** You don't need to touch code or servers.
The bot runs by itself; your job is to keep the community friendly and tidy.
Everything here is done **inside the Telegram app**. Keep the
**`docs/moderation-runbook.md`** open beside you for your first week.

### B1. The golden rules
- 🧡 **Tone first.** Friendly, owner-led, never salesy. See `docs/tone-guide.md`.
- **The bot handles the boring stuff** — welcoming people, tagging them, deleting
  obvious spam, and nudging support questions to the right place. You don't have
  to do any of that manually.
- **You step in for judgement calls** — answering members, pinning good posts,
  and dealing with people who cause trouble.
- **Never share a member's phone number or car plate** with anyone. That data is
  private (PDPA). See B5.

### B2. Your daily 5-minute check
1. Open the group and skim each topic for anything off-tone or unanswered.
2. Make sure prospect questions in the model lounges got a warm reply (if not,
   answer or tag an owner — see `docs/launch-seeding-plan.md`).
3. Glance at **Support & Assistance**; make sure Travis/support is picking up issues.
4. Pin anything genuinely great (a good owner story, an event notice).

### B3. The buttons and commands you'll actually use
You do most moderation with Telegram's own long-press menu (hold a message →
**Pin / Delete / Reply**). The bot also gives you **typed commands** — type them
as a message; for ones that act on a person, **reply to that person's message**
first, then type the command.

| You want to… | Do this |
|---|---|
| **Pin** a great post | Long-press the message → **Pin**, or reply to it with `/pin` |
| **Delete** a bad/spam post | Long-press → **Delete**, or reply with `/del` |
| **Mute** someone for 30 min | Reply to their message with `/mute 30` |
| **Un-mute** someone | Reply with `/unmute` |
| **Remove/ban** a bad actor | Reply with `/ban` (and `/unban` to reverse) |
| **Approve** a pending join | Reply/approve, or `/approve` |
| **Trust** a genuine member early so they can post links | Reply with `/trust` |
| **See the help list** | Type `/modhelp` |
| **Check the member sheet is healthy** | Type `/sheets_status` |
| **See community stats so far** | Type `/stats` |

Only admins can use these. If a normal member types them, nothing happens.
Full reference: `docs/moderation-runbook.md`.

### B4. Common situations
- **Crypto / scam / advert appears** → the bot usually deletes it within seconds.
  If one slips through, long-press → **Delete**, and `/ban` the poster if it's
  clearly a spam account. Big raid? See the "Emergency spam response" section of
  `docs/moderation-runbook.md` (slow mode + tighten settings).
- **A new member's link got blocked and they're confused** → that's the new-user
  link rule. If they're clearly genuine, reply to them with `/trust` and they can
  post links from then on.
- **Someone keeps flooding messages** → the bot rate-limits them automatically;
  if needed, `/mute 60` to cool things down.
- **An off-topic or heated thread** → gently redirect with a friendly note; mute
  only if someone won't stop.

### B5. Privacy / PDPA — what you must know
- Members may optionally give a phone number and car plate. These live in the
  Google Sheet and are **confidential** — never repost them in chat or share them.
- **If a member asks to be removed / "delete my data":**
  1. Open the member Google Sheet.
  2. Find their row by their **Telegram ID**.
  3. Clear their personal cells (and mark the **Deletion requested** column).
  4. Reply to confirm it's done.
  Full steps: `docs/pdpa-policy.md`. When in doubt, escalate to the L3 owner.

### B6. If the bot misbehaves (stops replying, deletes good posts, etc.)
You can't fix code, but you **don't need to** — just escalate:
1. Note **what happened** and **roughly when** (a screenshot helps; never include
   anyone's phone/plate).
2. Contact the **bot owner / technical contact** (filled into
   `docs/admin-onboarding.md` — keep that contact handy).
3. They can pause the bot or turn off a single misbehaving feature in seconds
   using the "kill-switch" steps in `docs/production-deployment.md` — no full
   rebuild needed.

### B7. Who does what
- **Lucia — L1 Community Lead:** day-to-day moderation, pinning, approving
  members, posting Announcements, keeping tone right, handling deletion requests.
- **Travis — L2 Dongfeng Support:** picks up service/charging/warranty/technical
  questions in **Support & Assistance**.
- **L3 Management/Owner (TBC):** group settings, the bot, and the Google Sheet
  ownership; the escalation point when something breaks.

Full role detail and the contact register: `docs/admin-onboarding.md`.

---

## Project layout (for developers)

```
src/dfeng_bot/
  config.py            # typed Config from env (feature flags, IDs, thresholds)
  logging_setup.py     # structured logging + log_event()
  app.py               # builds Application, lifecycle hooks, runs polling/webhook
  main.py              # entrypoint: python -m dfeng_bot.main
  metrics.py           # launch-metric event names + counters
  policy.py            # verbatim PDPA consent constant + field lists
  handlers/            # welcome, qualification, onboarding, support_redirect,
                       # antispam, flood_control, link_restrictions, moderation,
                       # membership, messages, commands  (+ register_handlers)
  services/
    schema.py          # canonical member-sheet columns/enums (single source of truth)
    sheets.py          # Google Sheets service (gspread, lazy)
    write_queue.py     # async write queue: retries, backoff, dead-letter
    entry_source.py    # invite-link → entry-source resolver
tests/                 # 73 unittest cases (run with PYTHONPATH=src:tests)
docs/ , config/ , content/ , scripts/ , deploy/   # runbooks, templates, assets
CLAUDE.md              # stack + conventions + how to extend (read before adding features)
```

**Extending the bot:** add handlers via `register_handlers()` in
`src/dfeng_bot/handlers/` — never edit `app.py` for features. Read **CLAUDE.md**
first. Every setting is an environment variable documented in `.env.example`.
