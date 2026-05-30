# Telegram supergroup provisioning runbook — VOL-196

Operator runbook to create and configure the **Dongfeng Experience Community**
Telegram supergroup exactly to spec, then record the resulting IDs for the bot.

> **Who runs this:** a Level 3 (Management) admin with a Telegram account, on a
> mobile or desktop Telegram client. Steps reference the **mobile app** UI; the
> Desktop/macOS app has the same options under slightly different menus (noted
> where they differ).
>
> **Outcome:** a private, invite-only, forum-enabled supergroup with the six
> required topics, the role tiers configured, the bot promoted as admin, and a
> filled-in `config/group-setup.yaml` feeding the bot's `.env`.
>
> Work top-to-bottom. The **acceptance checklist** at the end mirrors every
> requirement — tick it off as you go.

---

## 0. Before you start

- Decide the **Owner** (group creator) — must be a Level 3 / Management person.
  The creator is the Telegram *Owner* and cannot be changed except by transfer.
- Have the **bot's @username** ready (from VOL-197 / @BotFather). The bot must
  already exist; this ticket does not create it.
- Collect the **Telegram numeric user IDs** of everyone who will be an admin
  (L1/L2/L3). A user can get their own id from `@userinfobot` or `@RawDataBot`.
- Open `config/group-setup.example.yaml` alongside this runbook — you will copy
  it to `config/group-setup.yaml` and fill it in as you complete each step.

---

## 1. Create the supergroup

A plain "group" becomes a **supergroup** automatically once you enable Topics or
exceed 200 members. We force it immediately by enabling Topics in step 3.

1. Telegram → **New Message** → **New Group**.
2. Add **at least one** initial member (Telegram requires ≥1). Add the
   **bot's @username** now if convenient, or in step 7.
3. Group name: **`Dongfeng Experience Community`**. Tap **Create**.

---

## 2. Make it private and non-discoverable

By default a brand-new group is already private (no public link). Confirm and
lock it down:

1. Open the group → tap the title → **Edit** (pencil) → **Group Type**
   (Desktop: *Edit → Group Type*).
2. Select **Private**. There must be **NO public link / username** —
   `t.me/<name>` must NOT resolve to this group. If a public link field shows a
   username, clear it so the group is **Invite Link only**.
3. Result: the group is **not searchable** and not publicly discoverable. People
   can only join via an invite link (and, per step 6, only after approval).

> Record in setup notes: `is_private: true`, `public_username: null`.

---

## 3. Enable Topics (forum mode)

1. Group → title → **Edit** → toggle **Topics** **ON**
   (Desktop: *Edit → Topics*). Confirm.
2. Telegram converts the chat to a **forum supergroup** and auto-creates a
   pinned **General** topic (this is the built-in topic with
   `message_thread_id = 1`). It is **NOT** one of our six topics.
   - Recommended: **rename General** to one of our topics is NOT advised because
     General behaves specially (it cannot be deleted and is always shown first).
     Instead, leave General as a lightweight landing/rules topic, or **close**
     it (admin-only) so chatter happens in the six purpose-built topics below.

> Record in setup notes: `forum_topics_enabled: true`.

---

## 4. Create the six topics — EXACT names, in order

Create each topic via the topics list → **＋ / Create topic** (Desktop:
right panel → **Create Topic**). Use these **exact** names and this **order**:

1. `Announcements & Events`
2. `BOX Owners Lounge`
3. `007 Owners Club`
4. `VIGO Owners Circle`
5. `General Community Chat`
6. `Support & Assistance`

> Tip: names must match **character-for-character** (including the `&` and the
> leading `007`). Copy-paste them from this list to avoid typos.

### Capture each topic's thread_id

The bot needs the numeric `message_thread_id` of each topic:

- **Easiest:** with the bot already an admin (step 7), post any message in each
  topic; the bot's structured logs print `thread_id=<n>` for that topic
  (see `docs/deployment.md` → *Finding chat / topic / user IDs*). Then `/ping`
  in a topic replies `pong (thread_id=<n>)`.
- **Without the bot:** add `@RawDataBot` temporarily, post in each topic, read
  `message_thread_id` from its dump, then remove it.

Write each id into the matching slot in `config/group-setup.yaml`.

### Topic → config mapping (IMPORTANT)

The bot's `Config` (`src/dfeng_bot/config.py`) predates these display names and
exposes six **generic** env slots. Pin each display-name topic to one env slot —
**do not rename the env keys**, only fill in the thread ids:

| # | Topic (display name)        | Bot env var (`.env`)         | Config field            |
|---|-----------------------------|------------------------------|-------------------------|
| 1 | Announcements & Events      | `DFENG_TOPIC_ANNOUNCEMENTS`  | `topics.announcements`  |
| 2 | BOX Owners Lounge           | `DFENG_TOPIC_WELCOME`        | `topics.welcome`        |
| 3 | 007 Owners Club             | `DFENG_TOPIC_QUALIFICATION`  | `topics.qualification`  |
| 4 | VIGO Owners Circle          | `DFENG_TOPIC_EVENTS`         | `topics.events`         |
| 5 | General Community Chat      | `DFENG_TOPIC_GENERAL`        | `topics.general`        |
| 6 | Support & Assistance        | `DFENG_TOPIC_SUPPORT`        | `topics.support`        |

> The pairing is arbitrary but **fixed** — every later ticket and the setup
> template (`config/group-setup.example.yaml`) assume exactly this mapping.

---

## 5. Default member permissions

This sets what an ordinary **Member** can do group-wide.

1. Group → title → **Edit** → **Permissions** (Desktop: *Edit → Permissions*).
2. Set the group-wide member permissions so members **can**:
   - **Send Messages** (and media/links/etc. per your moderation appetite —
     leave **Send Messages** ON so members can post in the five open topics).
   - **Add Reactions** — leave ON (members react everywhere, including
     Announcements & Events).
3. **"Add Members"** — your call; recommended **OFF** so growth is controlled
   and only goes through the approval flow (step 6).
4. Group-wide "Pin Messages" / "Change Group Info" — leave **OFF** for members
   (admins handle these).

> Per-topic exceptions (e.g. Announcements being admin-only) are set on the
> **topic itself** in step 8, not here.

---

## 6. Invite-only with approval (join requests)

To be truly invite-only, new joins should require admin/bot approval:

1. Group → title → **Edit** → **Invite Links** → open the **primary invite
   link** settings → enable **Approve New Members**
   (a.k.a. *Request to Join* / *Approve new members*).
2. Now anyone using the invite link creates a **join request** that an admin —
   or the bot, once VOL-203 onboarding ships — must approve. No one joins
   silently.
3. Share the invite link only through controlled channels. Treat it as
   sensitive: record it **only** in the gitignored `config/group-setup.yaml`,
   never in the committed template.

> Record in setup notes: `approve_new_members: true`, `primary_invite_link`.

---

## 7. Add the bot and promote it to admin

1. Add the bot (`@<bot_username>`) to the group if not already present.
2. Group → title → **Edit** → **Administrators** → **Add Admin** → select the
   bot → enable exactly these rights:

   | Bot admin right            | On? | Why                                              |
   |----------------------------|-----|--------------------------------------------------|
   | **Delete Messages**        | ✅  | moderation / removing spam                        |
   | **Ban / Restrict Members** | ✅  | mute, restrict, ban (flood control, anti-spam)    |
   | **Pin Messages**           | ✅  | pin announcements                                 |
   | **Manage Topics**          | ✅  | create/close/reopen forum topics                  |
   | **Invite Users via Link**  | ✅  | manage + approve invite links / join requests     |
   | Change Group Info          | ❌  | not needed                                        |
   | Add New Admins             | ❌  | not needed — keep admin granting human-only       |
   | Remain Anonymous           | ❌  | bot posts as itself                               |

3. Save. The bot can now moderate, manage topics, and (later tickets) approve
   join requests.

> **Limitation — approving join requests:** the bot can approve/decline join
> requests **only** while it holds the *Invite Users via Link* admin right and
> your code handles `chat_join_request` updates. The VOL-197 foundation already
> requests `chat_member`; `chat_join_request` handling lands with onboarding
> (VOL-203). Until then, **admins approve requests manually** in the group.

---

## 8. Lock Announcements & Events to admin-only posting (reactions stay on)

**Goal:** in *Announcements & Events*, only admins post; members can still
**react** but **cannot post**.

**Telegram mechanism — "closed topic":** Telegram lets you mark a forum topic as
**Closed**. In a closed topic, **only admins can send messages**; everyone else
can still **read and add reactions**. This is the exact, native, supported way to
get "announcements + reactions, no member posts".

1. Open the **Announcements & Events** topic → topic header → **⋯ / Edit** →
   toggle **Close Topic** **ON** (Desktop: right-click the topic →
   **Close Topic**). The topic shows a small lock.
2. Verify: as the bot/admin you can still post there; a non-admin test account
   cannot send a message but **can** tap a reaction emoji.

> **Honest limitation:** Telegram has **no per-topic "members may react but not
> post" permission flag**. The *closed topic* is the mechanism that produces that
> behaviour. Consequences to know:
> - "Closed" is **all-or-nothing for non-admins**: every non-admin is blocked
>   from posting, every admin can post. You cannot allow *some* members to post.
> - Reactions are governed by the **group-wide "Add Reactions" permission**
>   (step 5) and the group's **allowed reactions** set — they remain available
>   to members in a closed topic. Keep "Add Reactions" ON or members won't be
>   able to react anywhere.
> - The other five topics stay **open** (not closed), so members post normally.

---

## 9. Admin role tiers (L1 / L2 / L3) — mapping to Telegram

**Telegram has only two native ranks: _Owner_ and _Administrator_.** There is no
native three-tier system. We therefore:

1. Map each tier onto Telegram admin **right toggles** as closely as Telegram
   allows, and
2. Keep an **out-of-band role register** (in `config/group-setup.yaml` →
   `admins:`) as the authoritative record of who is L1/L2/L3, since Telegram
   cannot store the distinction.

Promote each person via **Edit → Administrators → Add Admin** and set toggles:

| Privilege (Telegram admin toggle)        | L1 Community Mgmt | L2 Support | L3 Management |
|------------------------------------------|:-----------------:|:----------:|:-------------:|
| Delete Messages                          | ✅ | ✅ | ✅ |
| Ban / Restrict Users (mute, restrict)    | ✅ | ✅ | ✅ |
| Pin Messages                             | ✅ | ✅ | ✅ |
| Manage Topics (incl. post in Announcements via closed-topic admin) | ✅ | ✅ | ✅ |
| Manage Invite Links / Approve members    | ✅ | ✅ | ✅ |
| Change Group Info / Settings             | ❌ | ❌ | ✅ |
| Add New Admins                           | ❌ | ❌ | ✅ |
| Owner (group creator, can transfer/delete, owns bot config + Google Sheets) | — | — | ✅ (Owner) |
| **Custom admin title** (cosmetic label)  | "Community" | "DF Support" | "Management" |

Notes:
- **L1 (Community Management):** standard moderator. Posts announcements (it's an
  admin, so it can post in the closed Announcements topic), approves members,
  pins, deletes, mutes/restricts, moderates. No settings/bot/Sheets access.
- **L2 (Dongfeng Support):** **all L1 rights** plus the organisational mandate to
  handle product / servicing / support **escalation** in *Support & Assistance*.
  Telegram cannot scope an admin to "escalations in one topic", so L2 = L1 toggles
  **plus** the role-register designation; the escalation responsibility is
  procedural, optionally reinforced by the bot in a later ticket.
- **L3 (Management):** **all L2 rights** plus **Change Group Info**, **Add New
  Admins**, and is (or is delegated by) the **Owner** — controls group settings,
  the **bot configuration** (`.env` / `DFENG_*`), and **Google Sheets ownership**
  (later tickets). The Telegram **Owner** must be an L3.
- Use the **custom admin title** field purely as a visible label; it does **not**
  change permissions and is not a substitute for the role register.

> **Honest limitation:** the L1/L2/L3 boundary between "moderator" and "support"
> is **not enforceable by Telegram** — both get the same checkbox set. The
> distinction lives in the role register and (later) in bot logic. The only hard,
> Telegram-enforced line is **L3 (settings + add-admins + owner)** vs the rest.
>
> **Bot's view of admins:** the bot does **not** read tiers. Every admin's
> numeric id (any level) goes into `DFENG_ADMIN_IDS`; `Config.is_admin()` returns
> true for all of them. Per-level gating, if needed, is a future enhancement that
> would read the `admins:` register.

---

## 10. (Optional) Slow mode

If chat gets noisy, **Edit → Permissions → Slow Mode** sets a per-user cooldown
(e.g. 30s) between messages. It applies group-wide. Leave **off** initially;
record `slow_mode_seconds` if you enable it. (Programmatic flood control is a
separate future ticket via `GROUP_PREFILTER`.)

---

## 11. Record everything for the bot

1. Copy the template: `cp config/group-setup.example.yaml config/group-setup.yaml`
   (the `.yaml` copy is **gitignored** — it holds real ids).
2. Fill in every `<PLACEHOLDER>`: `group_id`, all six `thread_id`s, the
   `admins:` register, the invite-link setting, and the bot's id.
3. Transcribe the `env_mapping:` block into your `.env` (copy from
   `.env.example`), per the **Topic → config mapping** table in step 4:

   ```dotenv
   DFENG_GROUP_ID=-100xxxxxxxxxx
   DFENG_TOPIC_ANNOUNCEMENTS=<Announcements & Events thread_id>
   DFENG_TOPIC_WELCOME=<BOX Owners Lounge thread_id>
   DFENG_TOPIC_QUALIFICATION=<007 Owners Club thread_id>
   DFENG_TOPIC_EVENTS=<VIGO Owners Circle thread_id>
   DFENG_TOPIC_GENERAL=<General Community Chat thread_id>
   DFENG_TOPIC_SUPPORT=<Support & Assistance thread_id>
   DFENG_ADMIN_IDS=<id1>,<id2>,<id3>
   ```

4. `TELEGRAM_BOT_TOKEN` stays only in `.env` / your secret manager — never in
   the YAML file.
5. Smoke test: `python -m dfeng_bot.main`, then `/ping` inside each topic — it
   should reply `pong (thread_id=<n>)` in that same topic, confirming the ids.

---

## Access model — per-topic permission matrix

Legend: **Post** = can send messages in the topic · **React** = can add
reactions · ✅ allowed · ❌ not allowed. Admin rows assume the toggles in §9.

### Members (ordinary, non-admin)

| Topic                     | Post | React | Mechanism                          |
|---------------------------|:----:|:-----:|------------------------------------|
| Announcements & Events    | ❌   | ✅    | **Closed topic** (admin-only post) |
| BOX Owners Lounge         | ✅   | ✅    | Open topic + member "Send" perm    |
| 007 Owners Club           | ✅   | ✅    | Open topic + member "Send" perm    |
| VIGO Owners Circle        | ✅   | ✅    | Open topic + member "Send" perm    |
| General Community Chat    | ✅   | ✅    | Open topic + member "Send" perm    |
| Support & Assistance      | ✅   | ✅    | Open topic + member "Send" perm    |

### Admins — L1 / L2 / L3 (post + react everywhere)

| Topic                     | L1 Post | L1 React | L2 Post | L2 React | L3 Post | L3 React |
|---------------------------|:-------:|:--------:|:-------:|:--------:|:-------:|:--------:|
| Announcements & Events    | ✅      | ✅       | ✅      | ✅       | ✅      | ✅       |
| BOX Owners Lounge         | ✅      | ✅       | ✅      | ✅       | ✅      | ✅       |
| 007 Owners Club           | ✅      | ✅       | ✅      | ✅       | ✅      | ✅       |
| VIGO Owners Circle        | ✅      | ✅       | ✅      | ✅       | ✅      | ✅       |
| General Community Chat    | ✅      | ✅       | ✅      | ✅       | ✅      | ✅       |
| Support & Assistance      | ✅      | ✅       | ✅      | ✅       | ✅      | ✅       |

### Capability matrix (group-wide, not per-topic)

| Capability                                   | Member | L1 | L2 | L3 |
|----------------------------------------------|:------:|:--:|:--:|:--:|
| Read all topics                              | ✅     | ✅ | ✅ | ✅ |
| Post in the five open topics                 | ✅     | ✅ | ✅ | ✅ |
| Post in Announcements & Events               | ❌     | ✅ | ✅ | ✅ |
| Approve new members (join requests)          | ❌     | ✅ | ✅ | ✅ |
| Pin / delete / mute / restrict / moderate    | ❌     | ✅ | ✅ | ✅ |
| Support/servicing escalation (Support topic) | ❌     | ❌ | ✅ | ✅ |
| Change group settings / bot config / Sheets  | ❌     | ❌ | ❌ | ✅ |
| Add new admins / Owner                       | ❌     | ❌ | ❌ | ✅ |

> Reminder: Telegram enforces Member-vs-Admin and the L3-only settings line.
> The **L1↔L2** difference (the Support-escalation row) is **organisational**,
> recorded in the role register — Telegram gives both identical toggles.

---

## Acceptance criteria checklist

Tick each before closing VOL-196:

- [ ] Supergroup **`Dongfeng Experience Community`** created.
- [ ] Group is **Private** — no public username, `t.me/<name>` does not resolve,
      **not discoverable** in search.
- [ ] **Topics / forum mode is ON**.
- [ ] Exactly **six** topics exist with the **exact** names, in order:
      `Announcements & Events`, `BOX Owners Lounge`, `007 Owners Club`,
      `VIGO Owners Circle`, `General Community Chat`, `Support & Assistance`.
- [ ] **Announcements & Events** is a **closed topic**: members **cannot post**
      but **can react**; admins can post.
- [ ] Members **can post** in the other **five** topics and react in all six.
- [ ] **Invite-only**: primary invite link has **Approve New Members ON**
      (join requests require approval).
- [ ] Default member permissions set (Send Messages ON, Add Reactions ON,
      pin/settings OFF for members).
- [ ] **Bot promoted to admin** with: Delete Messages, Ban/Restrict,
      Pin Messages, Manage Topics, Invite via Link.
- [ ] **Admin tiers configured**: L1/L2/L3 promoted with the §9 toggles; L3 holds
      Change Group Info + Add Admins; Owner is an L3.
- [ ] **Out-of-band role register** filled in `config/group-setup.yaml`
      (`admins:` with `level` per person).
- [ ] **Setup note records**: `group_id`, all six `thread_id`s (mapped to the
      `DFENG_TOPIC_*` keys), `admin_ids` mapping, invite-approval setting, and
      the bot's required admin rights.
- [ ] Values transcribed into `.env`; `/ping` in each topic returns the correct
      `thread_id`.

---

## Summary of honest Telegram limitations

1. **No "react-only" topic permission.** "Members may react but not post" is
   achieved via a **closed topic** (admin-only posting; reactions stay on). It is
   all-or-nothing for non-admins — you cannot let only *some* members post.
2. **No native role tiers.** Telegram has only **Owner** and **Administrator**.
   L1/L2/L3 are an organisational construct kept in an out-of-band role register;
   only the **L3** line (settings / add-admins / owner) is Telegram-enforced.
   L1 vs L2 get identical permission toggles.
3. **Reactions depend on the group-wide "Add Reactions" permission** and the
   group's allowed-reaction set — not a per-topic switch.
4. **Bot join-request approval** needs the *Invite via Link* admin right **and**
   `chat_join_request` handling in code (lands with onboarding, VOL-203); until
   then admins approve manually.
5. **The built-in "General" topic** (`thread_id = 1`) is auto-created, always
   shown first, and cannot be deleted — it is **not** one of the six topics.
