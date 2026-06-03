# Entry-source invite links & QR assets — VOL-202

Operator runbook for the **six entry sources** that funnel people into the
**Dongfeng Experience Community** and for recording *which channel brought each
member in* (the workbook's **"Entry source"** column,
`services/schema.py` → `ENTRY_SOURCES`).

> **Who runs this:** an admin who can call the Bot API with the bot token and the
> group id (an L1+ admin holding the *Invite via Link* right, or a Level 3 who
> owns the bot config). Work top-to-bottom; the **checklist** at the end mirrors
> the acceptance criteria.

---

## Two entry modes — pick one

| Mode | Entry point | Onboarding | PII privacy |
|------|-------------|-----------|-------------|
| **A. Deep-link DM onboarding (recommended)** | bot deep link `https://t.me/<bot>?start=<source>` | happens in the **private bot chat** BEFORE joining; a single-use group invite is granted on completion | ✅ phone/plate never typed in a public topic |
| **B. Group invite links** (the rest of this doc) | named `t.me/+...` group invite links | happens **in the group** after joining | ⚠️ phone/plate are typed in General (visible to all) |

### Mode A — deep-link DM onboarding (Option A)

Telegram won't let a bot DM a user who hasn't started it, so the entry point is a
**bot deep link**, not a group invite link. Flow:

1. QR / Linktree / salesperson link → `https://t.me/<DFENG_BOT_USERNAME>?start=<token>`
   where token ∈ `showroom | roadshow | event | linktree | salesperson | website`
   (mapped to the entry source in `handlers/dm_onboarding.py`).
2. User taps → opens the bot DM → presses **Start** → the bot asks every question
   **privately** (Owner/Prospect → model → PDPA consent → optional phone/plate).
3. On completion the bot mints a **single-use** invite link (`member_limit=1`) and
   DMs it — the user joins already vetted. Unfinished users are never let in.

**Enable it:** set `DFENG_BOT_USERNAME` (e.g. `DongfengSGBot`) and
`DFENG_FEATURE_DM_ONBOARDING=1` in `.env`, then generate the deep-link QR codes:

```bash
python scripts/generate_qr.py        # with DFENG_BOT_USERNAME set -> deep-link QR PNGs
```

In Mode A you do **not** share the group invite links as the public entry; keep
the group on "Approve New Members" only as a backstop (or rely solely on the
single-use links). The rest of this runbook (Mode B) covers the group-invite-link
mechanism for deployments that keep onboarding in-group.

---

## 0. The six entry sources

| # | Source id (canonical, MUST match `schema.ENTRY_SOURCES`) | Tracked by a named invite link? | Env var |
|---|----------------------------------------------------------|:-------------------------------:|---------|
| 1 | `salesperson`         | No — salesperson adds the customer directly (also the **default** fallback) | — |
| 2 | `showroom QR`         | **Yes** | `DFENG_INVITE_LINK_SHOWROOM` |
| 3 | `roadshow QR`         | **Yes** | `DFENG_INVITE_LINK_ROADSHOW` |
| 4 | `event QR`            | **Yes** | `DFENG_INVITE_LINK_EVENT` |
| 5 | `Linktree`            | **Yes** | `DFENG_INVITE_LINK_LINKTREE` |
| 6 | `website placeholder` | No — external website URL, not a group invite link | — |

The four **link-tracked** sources each get a **separate named Telegram invite
link**. The bot reads the `invite_link` string Telegram echoes on the join
update and maps it back to the source id.

---

## 1. Why this mechanism (and the honest Telegram limitation)

**Telegram group invite links are NOT bot deep links.** A `/start` parameter is
**not** available to the bot after someone joins a private group, so you cannot
"tag" a join via a `t.me/<bot>?start=...` link the way you can for a bot DM.

The reliable mechanism is **separate named invite links, one per source**:

1. Create one invite link per source via the Bot API `createChatInviteLink`
   (with a `name`, e.g. `"showroom QR"`), optionally `creates_join_request=true`
   for invite-only approval.
2. Telegram echoes the exact `invite_link` string back on the join update —
   `chat_member.invite_link` for direct joins, `chat_join_request.invite_link`
   for approval joins.
3. The bot maps that string → source id (`services/entry_source.py`).

### Limitation & chosen fallback

Some join paths **cannot** expose a source:

* a member shares the **primary** invite link, or any link not in the registry;
* someone **adds** a user directly (no link at all);
* a `new_chat_members` service message (classic add) carries no invite link.

For all of these the resolver returns the **documented default
`salesperson`** (`DEFAULT_ENTRY_SOURCE` in `services/entry_source.py`) — chosen
because the most common un-tracked path in practice is a salesperson inviting a
customer directly. The onboarding/qualification flow (VOL-204) **may optionally
confirm the source** with the member to correct a defaulted value. Operators who
want an explicit "unknown" bucket can simply ensure every QR/Linktree source has
its own link set, leaving `salesperson` as the catch-all for true direct adds.

---

## 2. Prerequisites

* The bot is an **admin** in the group with **Invite Users via Link** ON
  (see `docs/telegram-setup.md` §7). Without this right, `invite_link` is **not**
  populated on join updates and `createChatInviteLink` fails.
* You have:
  * `TELEGRAM_BOT_TOKEN` (from `.env` / secret manager — never paste into chat),
  * `DFENG_GROUP_ID` (the negative `-100…` supergroup id).
* `app.ALLOWED_UPDATES` already includes `CHAT_MEMBER` and `CHAT_JOIN_REQUEST`
  (added in VOL-202), so both join paths reach the bot.

---

## 3. Create the four named invite links (Bot API)

Run one call per link-tracked source. The `name` is operator-facing only; the
**link string** is what maps to the source. Set `creates_join_request=true` to
keep the community **invite-only with approval** (recommended — matches
`docs/telegram-setup.md` §6); set it to `false` if you want instant joins.

> Replace `<TOKEN>` and `<GROUP_ID>` with real values. **Do not commit the
> output** — the returned `invite_link` is a join grant.

```bash
# Showroom QR
curl -s "https://api.telegram.org/bot<TOKEN>/createChatInviteLink" \
  -d chat_id=<GROUP_ID> \
  -d name='showroom QR' \
  -d creates_join_request=true

# Roadshow QR
curl -s "https://api.telegram.org/bot<TOKEN>/createChatInviteLink" \
  -d chat_id=<GROUP_ID> \
  -d name='roadshow QR' \
  -d creates_join_request=true

# Event QR
curl -s "https://api.telegram.org/bot<TOKEN>/createChatInviteLink" \
  -d chat_id=<GROUP_ID> \
  -d name='event QR' \
  -d creates_join_request=true

# Linktree
curl -s "https://api.telegram.org/bot<TOKEN>/createChatInviteLink" \
  -d chat_id=<GROUP_ID> \
  -d name='Linktree' \
  -d creates_join_request=true
```

Each call returns JSON like:

```json
{"ok": true, "result": {"invite_link": "https://t.me/+AbCdEf123", "name": "showroom QR", "creates_join_request": true, ...}}
```

Copy the `invite_link` value for each.

> **Manual alternative (Telegram app):** Group → title → **Edit** → **Invite
> Links** → **Create a new link** → set a **Link name** (e.g. `showroom QR`) and
> toggle **Request Admin Approval** (= `creates_join_request`) → **Create**, then
> copy the link. Repeat for all four. The app-created link works identically —
> Telegram still echoes its string on the join update.

> **`creates_join_request` semantics:**
> * `true`  → clicking the link creates a **join request** (admin/bot approval);
>   the bot sees it as a `chat_join_request` update. Invite-only.
> * `false` → clicking the link **joins immediately**; the bot sees it as a
>   `chat_member` update. Both paths carry the `invite_link`, so source tracking
>   works either way.

---

## 4. Fill the bot config (link → source mapping)

Put each returned link in the matching env var (in your **gitignored `.env`** or
secret manager — see `.env.example` for placeholders):

```dotenv
DFENG_INVITE_LINK_SHOWROOM=https://t.me/+<showroom link>
DFENG_INVITE_LINK_ROADSHOW=https://t.me/+<roadshow link>
DFENG_INVITE_LINK_EVENT=https://t.me/+<event link>
DFENG_INVITE_LINK_LINKTREE=https://t.me/+<linktree link>
```

How the mapping is consumed (no code changes needed when links rotate — just
update the env and restart):

* `config.py` loads these into `Config.invite_links` (`InviteLinks` sub-config).
* `services/entry_source.py` owns the canonical `link → source id` map
  (`ENV_BY_SOURCE`) and the resolver `resolve_entry_source(invite_link) -> str`.
* On each join, `handlers/membership.py` / `handlers/join_request.py` read the
  `invite_link` off the update, resolve the source, **stash it in
  `context.user_data["entry_source"]`**, and log it. VOL-205 reads that value to
  write the workbook's **"Entry source"** column. (VOL-202 does **not** write to
  Sheets.)

**Unknown / missing link → `salesperson`** (the documented default, §1).

---

## 5. Linktree button URL & website placeholder URL

These two are **not** group invite links in the same way — they are *external
surfaces* that ultimately point people at a Telegram link:

* **Linktree** — In Linktree, add a button labelled e.g. *"Join the Dongfeng
  Community on Telegram"* whose **URL is the `DFENG_INVITE_LINK_LINKTREE` link**
  from §3. Because it is the dedicated Linktree-named link, every join through it
  resolves to source `Linktree`. If you later A/B test multiple Linktree buttons,
  create additional named links and extend `ENV_BY_SOURCE`.
* **Website placeholder** — the public website is **out of scope** (VOL-202 does
  not implement it). For now, document the intended link target only. When the
  site ships, point its "Join community" CTA at a dedicated named invite link and
  add a `DFENG_INVITE_LINK_WEBSITE` env + an `ENV_BY_SOURCE` entry mapping it to
  the existing `website placeholder` source id. Until then, joins attributable to
  the website fall back to the default (`salesperson`); the `website placeholder`
  source id already exists in the schema for when the link is wired up.

---

## 6. Generate the QR codes

QR codes are required for **showroom QR, roadshow QR, event QR** (Linktree is
generated too for convenience). The script reads the same `DFENG_INVITE_LINK_*`
env vars and writes one PNG per configured source.

```bash
# 1. Make sure the DFENG_INVITE_LINK_* vars are set (e.g. your .env is loaded).
# 2. Install the QR dependency (also in requirements.txt):
pip install "qrcode[pil]"
# 3. Generate (writes assets/qr/<source>.png):
python scripts/generate_qr.py
# Optional: custom output dir
python scripts/generate_qr.py --out /tmp/qr
```

Output files: `assets/qr/showroom_qr.png`, `assets/qr/roadshow_qr.png`,
`assets/qr/event_qr.png`, `assets/qr/linktree.png`.

* The generated PNGs are **gitignored** (`assets/qr/*.png`) because they encode
  real invite links; only `assets/qr/.gitkeep` is committed.
* Sources whose env var is empty are **skipped** with a warning, so you can roll
  out incrementally.
* **Printing the physical QR is out of scope** — hand the PNGs to whoever
  produces the showroom standees / roadshow banners / event signage.

---

## 7. Verify

* **Resolver logic** — `services/entry_source.py` has runnable docstring
  examples; run them with:

  ```bash
  python -m doctest src/dfeng_bot/services/entry_source.py -v
  ```

* **End-to-end** — with `DFENG_LOG_LEVEL=INFO`, join via a tracked link and
  confirm the bot logs `entry_source=<source id>` on `new_member` /
  `chat_join_request`. The link strings themselves are **never** logged.

---

## Checklist

- [ ] Bot is admin with **Invite via Link** ON.
- [ ] Four named invite links created (`showroom QR`, `roadshow QR`, `event QR`,
      `Linktree`), with `creates_join_request` set to your invite-only choice.
- [ ] `DFENG_INVITE_LINK_*` env vars filled in `.env` (real links, NOT committed).
- [ ] QR PNGs generated for showroom, roadshow, event (and Linktree).
- [ ] Linktree button URL = the `Linktree` named link; website placeholder target
      documented.
- [ ] Resolver verified (doctest); joins log a valid `entry_source`.
- [ ] Default/fallback understood: missing/unknown link → `salesperson`.
```
