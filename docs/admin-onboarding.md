# Admin Onboarding & Operating-Procedure Handoff — Dongfeng Experience Community (VOL-215)

The launch handoff pack for the admin team operating the **Dongfeng Experience
Community** Telegram supergroup. Read this on day one. It tells each admin what
access they need, how to get it, what their tier does, how to use the moderation
tools, how to handle PDPA data requests, how to disable or escalate a bot issue,
and who owns what.

> **This is the operating handoff, not a rebuild.** The community, bot, and
> workbook are already built and documented. This doc points you to the real
> runbooks rather than duplicating them. The authoritative sources are:
> - `docs/telegram-setup.md` — group, six topics, L1/L2/L3 tiers, bot admin rights
> - `docs/google-sheets-setup.md` — workbook + service account + named-admin sharing
> - `docs/pdpa-policy.md` — consent + member-data deletion path
> - `docs/moderation-runbook.md` — native vs bot actions, command table, kill-switches, daily workflow, emergency spam response
> - `docs/production-deployment.md` — deploy, secrets, rollback / disable
> - `docs/launch-smoke-test.md` and `docs/qa-checklist.md` — launch readiness
> - `docs/metrics-and-reporting.md`, `docs/launch-seeding-plan.md`,
>   `content/pinned-messages.md`, `docs/tone-guide.md`

---

## 1. Admin roster + access matrix

Launch admin team. **Lucia** and **Travis** are confirmed; the **L3 Owner** and
the **1–3 additional reps** are TBC and are recorded below as **PENDING LAUNCH
RISKS** (see §6 and the risk callouts). Tiers, Telegram toggles, and the
honest "Telegram can't enforce L1 vs L2" caveat all come from
`docs/telegram-setup.md` §9.

| Admin | Tier | Role | Telegram admin rights (per `telegram-setup.md` §9) | Google Sheets access (per `google-sheets-setup.md` §4) | Status |
|---|---|---|---|---|---|
| **Lucia** | **L1** | Community Lead / Community Management | Delete Messages · Ban/Restrict · Pin · Manage Topics · Manage Invite Links/Approve. **No** Change Group Info, **No** Add Admins. Custom title "Community". | **Editor** on the `Members` workbook, by her **named Google account**. | ✅ Confirmed |
| **Travis** | **L2** | Dongfeng Support | Same toggles as L1 (Telegram gives L1/L2 identical toggles). Plus the **procedural** mandate to own escalation in *Support & Assistance*. Custom title "DF Support". | **Editor** on the `Members` workbook, by his **named Google account**. | ✅ Confirmed |
| **L3 Owner** | **L3** | Management / Owner | All L2 toggles **plus** Change Group Info/Settings + Add New Admins; is (or is delegated by) the Telegram **Owner**. Custom title "Management". | **Owner** of the `Members` workbook (ownership stays with the Dongfeng Experience / L3 Management account). | ⚠️ **TBC — PENDING LAUNCH RISK** (§6) |
| **Additional rep #1** | TBC (likely L1 or L2) | TBC | Per the chosen tier's toggle set above. | Editor by named Google account. | ⚠️ **TBC — PENDING LAUNCH RISK** (§6) |
| **Additional rep #2** | TBC | TBC | Per chosen tier. | Editor by named Google account. | ⚠️ **TBC — PENDING LAUNCH RISK** (§6) |
| **Additional rep #3** | TBC | TBC | Per chosen tier. | Editor by named Google account. | ⚠️ **TBC — PENDING LAUNCH RISK** (§6) |

> **Required coverage this roster addresses:**
> - **L1 Community Management** — content, engagement, moderation (pin/delete/mute), approve members, Announcements posts, workbook read/edit. → Lucia.
> - **L2 Dongfeng Support** — all L1 + product/servicing/ownership escalation in *Support & Assistance*. → Travis.
> - **L3 Management / Owner Access** — all L2 + group settings, bot configuration (`.env` / `DFENG_*`), workbook ownership. → TBC owner.

### Per-admin setup checklist

Run this for **each** admin as they are onboarded. Two halves: Telegram promotion
and Sheets sharing. Tick every box before the admin is considered "live".

**Lucia (L1) — Community Lead**
- [ ] Collect Lucia's **numeric Telegram user ID** (`@userinfobot` / `@RawDataBot`) — `telegram-setup.md` §0.
- [ ] Telegram → group → **Edit → Administrators → Add Admin → Lucia**, set the **L1 toggle set** per `telegram-setup.md` §9 (Delete, Ban/Restrict, Pin, Manage Topics, Manage Invite Links; **NOT** Change Group Info, **NOT** Add Admins). Set custom title "Community".
- [ ] Add Lucia's Telegram ID to **`DFENG_ADMIN_IDS`** and to the `admins:` role register in `config/group-setup.yaml` (L3 task; bot reads only the IDs, not tiers — `telegram-setup.md` §9).
- [ ] Share the **`Members`** workbook to Lucia's **named Google account** as **Editor** (`google-sheets-setup.md` §4) — named account only, never "anyone with the link".
- [ ] Confirm Lucia understands **bot-owned cols 1–8 are read-only**; humans edit only **cols 9–12** (`Notes`, `Status`, `Deletion requested`, `Last reconciled`) — `google-sheets-setup.md` §1.

**Travis (L2) — Dongfeng Support**
- [ ] Collect Travis's numeric Telegram user ID.
- [ ] Promote in Telegram with the **same toggle set as L1** (Telegram cannot scope to "Support topic only" — the escalation duty is procedural), custom title "DF Support".
- [ ] Add Travis's Telegram ID to `DFENG_ADMIN_IDS` and the `admins:` register with `level: L2`.
- [ ] Share the `Members` workbook to Travis's named Google account as **Editor**.
- [ ] Brief Travis that **he owns *Support & Assistance*** escalation and picks up `support_redirect` nudges (`moderation-runbook.md` §4/§8).

**L3 Owner (TBC) — Management** — *⚠️ block until named (§6)*
- [ ] **Name the L3 Owner.** Must be a Level 3 / Management person; is the Telegram group **Owner** (creator) or delegated by them.
- [ ] Confirm Owner holds Change Group Info + Add New Admins in Telegram (`telegram-setup.md` §9).
- [ ] Confirm Owner **owns** the `Members` workbook and the GCP project / service account (`google-sheets-setup.md` §1–§4).
- [ ] Owner controls **bot configuration**: `.env.production`, `DFENG_ADMIN_IDS`, and the feature flags / kill-switches (`production-deployment.md` §2–§4, §9).

**Additional rep #1–3 (TBC)** — *⚠️ onboard or carry as risk (§6)*
- [ ] Decide each rep's **tier** (L1 or L2), then run the matching checklist above (Telegram toggles per tier + add ID to `DFENG_ADMIN_IDS`/register + share workbook by named Google account as Editor).
- [ ] If a rep is **not** named/onboarded by launch, record them as a **pending launch risk** (§6) and proceed with Lucia + Travis as the minimum viable admin team.

---

## 2. What each tier does — quick reference

Summary only. The full per-tier runbook is **`docs/moderation-runbook.md` §4**;
the Telegram toggle mapping is **`docs/telegram-setup.md` §9**. Don't re-derive
permissions here — follow those.

- **L1 — Community Management (Lucia).** The daily driver. Approve new members,
  pin/delete/mute/unmute/ban/unban, post in *Announcements & Events* (closed topic
  — admins can post, members react only), keep the lounges and *General* healthy,
  and review the bot's automated-moderation logs for false positives. No
  settings/bot/Sheets-ownership access.
- **L2 — Dongfeng Support (Travis).** Everything L1 can do **plus** owns
  **product / servicing / ownership escalation** in *Support & Assistance*, and
  picks up questions the bot redirects there. The L1↔L2 line is **organisational**
  (the role register), not Telegram-enforced.
- **L3 — Management / Owner (TBC).** Everything L2 can do **plus** group settings,
  **bot configuration** (`.env` / `DFENG_*`, `DFENG_ADMIN_IDS`, feature flags), and
  **workbook ownership**. The Telegram Owner is an L3. This is the only line
  Telegram actually enforces.

> **Honest limitation (from `telegram-setup.md` §9):** Telegram has only *Owner*
> and *Administrator*. L1 and L2 get **identical** permission toggles; their
> difference is procedural. The bot does **not** read tiers — every admin ID in
> `DFENG_ADMIN_IDS` can run every bot command.

---

## 3. Using the tools — native Telegram + bot commands

You can moderate **two ways**, and they do the same thing under the hood: do it
**natively** in the Telegram app (long-press a message, topic menus, the
join-requests screen) or with a **bot command** (reply to a message). Prefer the
**bot command** for anything you want an audit trail on (bans, mutes, mass deletes
during a raid) — every command logs `admin id → target → action → outcome`. The
full native-vs-command table is **`docs/moderation-runbook.md` §1**, and the
command-to-required-bot-right mapping is **§2** there.

**Moderation commands** (reply to a message; admin-gated — `moderation-runbook.md` §1–§3):
`/pin` · `/del` (or `/delete`) · `/mute <minutes>` · `/unmute` · `/ban` · `/unban`
· `/approve` · `/modhelp` (lists them in-chat) · `/trust` (lifts the new-user link
restriction for a member; bot-only, no native equivalent).

**Operational / observability commands** (admin-gated):
`/sheets_status` (write-queue pending / in-flight / dead-letter) · `/reconcile`
(lists dead-lettered Telegram IDs to backfill) · `/stats` (process-lifetime metric
counters — see `docs/metrics-and-reporting.md` §8). Also `/health` and `/ping`
(replies `pong (thread_id=<n>)` for a quick connectivity check).

**Member-facing flow commands** (not moderation): `/qualify` re-opens the
qualification/tag flow; `/profile` re-opens optional PDPA-gated phone/plate
capture. Admins rarely need these but should know they exist.

> If a command fails with a "the bot may be missing the '<right>' admin right"
> message, the bot is missing a Telegram admin right — re-grant the full set per
> `telegram-setup.md` §7 / `production-deployment.md` §5. The command **degrades
> gracefully**; it never crashes the bot. You can always fall back to the native
> action.

---

## 4. PDPA / data handling for admins

The full policy is **`docs/pdpa-policy.md`** (v1, LOCKED). What admins must know:

- The workbook splits into **bot-owned columns 1–8** (treat as read-only) and
  **admin-owned columns 9–12**: `Notes`, `Status`, `Deletion requested`,
  `Last reconciled` (`google-sheets-setup.md` §1). Humans only ever edit 9–12.
- Optional personal data (**phone**, **vehicle plate**) is consent-gated and only
  present if the member provided it after the consent notice. **Never share a
  member's phone number or vehicle plate**, and never put PII in logs or chat.

### Handling a deletion request (admin steps — `pdpa-policy.md` §6)

1. **Find the member's row** by matching the **`Telegram ID`** column to the
   requester's Telegram ID (match on ID, never on username — usernames change).
2. **Mark the request:** enter the request date in the **`Deletion requested`**
   column so the action is auditable.
3. **Clear / redact the row:** either delete the entire row, **or** clear/redact
   the personal fields (`Telegram username`, `Optional phone`, `Optional plate`,
   the mandatory identifiers) **and** clear `Consent timestamp`. Leave **no
   recoverable** personal data for that member.
4. **Confirm back to the user:** reply confirming their data has been removed from
   the community workbook and that they have been / will be removed from the
   community as requested.

A member **leaving** the community is handled the same way (steps 1 + 3); no user
confirmation is needed for a voluntary leave. Retention rule: member data is kept
**only until** the member leaves or requests removal (`pdpa-policy.md` §5).

> **Unresolved PDPA items (launch risks, `pdpa-policy.md` §8):** final policy
> sign-off owner, a PDPA/Data-Protection-Officer contact, and a data-breach
> procedure are all **TBD**. Carry these as launch risks (§6) and route any
> breach or formal privacy request to the L3 Owner until an owner is named.

---

## 5. Disabling or escalating a bot issue during launch

The bot's automated moderation subsystems are designed to be **switched off fast
without a redeploy** — they are the documented **kill-switches**. Full procedure:
`docs/production-deployment.md` §9 and the raid playbook `docs/moderation-runbook.md` §6.

**If a bot feature misbehaves (over-deleting, wrongly muting, etc.):** an **L3**
edits `.env.production`, sets the relevant flag to `0`, and **restarts** the
process (no rebuild, no code change):

- `DFENG_FEATURE_ANTISPAM=0` — stop automated spam deletes
- `DFENG_FEATURE_FLOOD_CONTROL=0` — stop rate-based mutes
- `DFENG_FEATURE_LINK_RESTRICTIONS=0` — stop new-user link blocks
- `DFENG_FEATURE_SUPPORT_REDIRECT=0` — stop the support nudge

Restart to apply: Docker `docker compose up -d`; systemd `sudo systemctl restart
dfeng-bot`; PaaS re-deploy/restart the single worker (`production-deployment.md` §9).

**If you need to stop the bot entirely:** Docker `docker compose stop`; systemd
`sudo systemctl stop dfeng-bot`; PaaS scale the worker to 0. Stopping leaves the
**group fully functional** — only automation/onboarding pauses (the in-memory
write queue is lost on stop; affected IDs are in the logs and re-derivable).

**During an active spam raid:** follow `moderation-runbook.md` §6 — enable native
**Slow Mode** first, then `/mute`/`/ban` offenders, optionally tighten thresholds
(L3), close noisy topics, and use the kill-switches above if the bot itself is
over-moderating.

**Who to contact:** raise bot/config/flag issues to the **L3 Owner** (owns
`.env.production` and the flags — `moderation-runbook.md` §4). See the ownership
register in §6 for the contact path (currently **TBC** — a launch risk).

---

## 6. Handoff notes / ownership register

The launch ownership record. Real names/contacts are **TBC** where unknown and
are flagged as launch risks — fill these in before opening to the public.

| Thing owned | Owner / location | Status |
|---|---|---|
| **Production bot owner** (runs deploy, holds `.env.production`, flips flags) | L3 Management / Owner — **TBC** | ⚠️ **PENDING LAUNCH RISK** |
| **Google Sheets workbook owner** (`Members` workbook + GCP project + service account) | Dongfeng Experience / L3 Management account — **TBC named account** | ⚠️ **PENDING LAUNCH RISK** |
| **Emergency contact path** (who to ping for a bot/raid/PDPA incident, and how) | **TBC** — name a person + channel (e.g. a Telegram DM / phone) | ⚠️ **PENDING LAUNCH RISK** |
| **Where the logs live** | Bot **stdout/stderr** → host logs: `journalctl -u dfeng-bot -f` (systemd) or `docker compose logs -f` (Docker) or the PaaS log viewer. Format `kv` (default) or `json`. No log files written by the app. (`production-deployment.md` §7, `moderation-runbook.md` §7) | ✅ Documented |
| **Where the secrets live** (NOT the values) | `TELEGRAM_BOT_TOKEN`, `GOOGLE_APPLICATION_CREDENTIALS` (path or raw JSON), `DFENG_SHEETS_WORKBOOK_ID`, group/topic IDs, `DFENG_ADMIN_IDS` — all injected at runtime via `.env.production` (gitignored) + a mounted `*.json` creds file (gitignored). Only `*.example` templates are committed. (`production-deployment.md` §2, `google-sheets-setup.md` §5) | ✅ Documented |
| **Role register** (authoritative who-is-L1/L2/L3) | `config/group-setup.yaml` → `admins:` (gitignored; holds real IDs) | ✅ Documented |
| **PDPA policy sign-off owner / DPO contact / breach process** | **TBD** (`pdpa-policy.md` §8) | ⚠️ **PENDING LAUNCH RISK** |

> **Never put secrets or PII in this doc, in chat, or in logs.** This register
> records **where** secrets live and **who** owns them — not the values.

### How TBC people/owners are handled

Every unknown name or contact above is recorded as a **PENDING LAUNCH RISK**, not
silently assumed. Minimum viable launch is **Lucia (L1) + Travis (L2)**; the L3
Owner, the additional reps, the emergency contact, and the PDPA sign-off/DPO are
to be named before public launch. Until the L3 Owner is named, treat
config/flag/PDPA-escalation decisions as **blocked** and route them to whoever
currently holds the Telegram Owner role and the workbook.

---

## 7. Day-one launch checklist

Pulls together the cross-ticket conditions for going live. References the source
tickets/docs — tick each before opening to the public.

- [ ] **Group live + pinned (VOL-201):** supergroup provisioned with the six
      topics, *Announcements & Events* closed, and pins posted from
      `content/pinned-messages.md` (`telegram-setup.md`).
- [ ] **Bot deployed with launch flags (VOL-213):** deployed per
      `production-deployment.md`; startup `safe_summary()` shows
      `DFENG_FEATURE_ANTISPAM` / `_FLOOD_CONTROL` / `_LINK_RESTRICTIONS` / `_SHEETS`
      all **ON** and the six topic IDs (clears QA **R2**).
- [ ] **Workbook shared to admins:** `Members` workbook shared to each admin's
      **named Google account** as Editor, service account as Editor, General
      access Restricted (`google-sheets-setup.md` §4).
- [ ] **Admins promoted:** Lucia (L1) and Travis (L2) promoted with the correct
      Telegram toggles and added to `DFENG_ADMIN_IDS` + the role register
      (§1 checklists). Additional reps + L3 Owner named or carried as risk (§6).
- [ ] **QA GO conditions cleared (VOL-214):** run `docs/launch-smoke-test.md` then
      the manual items **M1–M3** on the staging clone — clears **R1**; confirm prod
      flags + bot admin rights — clears **R2** (and **R6**). QA decision is
      **GO-WITH-RISKS** in `qa-checklist.md`.
- [ ] **Seeding plan ready (VOL-216):** `docs/launch-seeding-plan.md` +
      `content/seed-content-calendar.md` ready; seed owners named or their absence
      carried as a seeding risk.
- [ ] **Ownership register filled (§6):** L3 Owner, workbook owner, and emergency
      contact named — or explicitly accepted as launch risks.

---

## 8. Acceptance-criteria checklist (VOL-215)

- [ ] **Lucia (L1) / Travis (L2) — or substitutes — have access:** roster + access
      matrix + per-admin setup checklists (Telegram toggles per `telegram-setup.md` §9
      + named-account Sheets sharing per `google-sheets-setup.md` §4) — §1.
- [ ] **Additional reps onboarded or listed as pending risk:** reps #1–3 carry a
      per-tier checklist; if not named by launch they are recorded as PENDING
      LAUNCH RISKS — §1, §6.
- [ ] **Admins know native + bot tools:** native-vs-command orientation + the full
      command list, pointing to `moderation-runbook.md` §1–§3 — §3.
- [ ] **Admins know PDPA deletion handling:** locate by Telegram ID → mark
      `Deletion requested` → clear/redact → confirm to user; never share
      phone/plate — §4, per `pdpa-policy.md` §6.
- [ ] **Admins know how to disable / escalate the bot:** kill-switch feature flags
      + restart + stop, cross-ref `production-deployment.md` §9 and
      `moderation-runbook.md` §6 — §5.
- [ ] **Handoff notes include bot owner / workbook owner / emergency path:**
      ownership register with logs + secrets locations, TBCs flagged as launch
      risks — §6.
