# Moderation & Operations Runbook — Dongfeng Experience Community (VOL-211)

Operational guide for admins moderating the **Dongfeng Experience Community**
Telegram supergroup. Covers what to do **natively in Telegram** vs **with the
bot's commands**, the admin **rights** the bot needs, **per-tier** duties, the
**daily workflow**, **escalation** ownership, an **emergency spam** playbook, and
how to **review the bot's automated moderation logs**.

Cross-references:
- Group provisioning, tiers L1/L2/L3, bot admin rights → `docs/telegram-setup.md`.
- Where logs go / how to run the bot → `docs/deployment.md`.
- Feature flags for the automated moderation subsystems →
  `src/dfeng_bot/config.py` (`FeatureFlags`).

---

## 1. Native Telegram actions vs bot commands

Most moderation can be done **two ways**: natively (long-press / topic menus in
the Telegram app) or via a **bot command** (reply to a message). Humans and the
bot can both do the same underlying actions — they call the same Bot/Client API.
Pick whichever is faster for the situation.

| Action | Native Telegram (in the app) | Bot command | Notes / when to use which |
|---|---|---|---|
| **Pin a message** | Long-press message → **Pin** | `/pin` (reply) | Either. Use `/pin` when you're already typing; native when browsing. |
| **Delete a message** | Long-press → **Delete** | `/del` or `/delete` (reply) | Either. `/del` logs the action for audit; native is one tap. |
| **Mute (temporary/permanent)** | Tap user → **Promote/Restrict** → toggle Send Messages, set duration | `/mute <minutes>` (reply or id) | `/mute 30` is the fastest for a time-bounded mute; native for fine-grained per-permission control. |
| **Unmute** | User → **Restrict** → re-enable Send Messages | `/unmute` (reply or id) | Either. |
| **Ban / remove member** | Tap user → **Ban** / **Remove** | `/ban` (reply or id) | Either. `/ban` logs admin id + target. |
| **Unban** | Group → **Members** / removed list → unban | `/unban` (reply or id) | `/unban` uses `only_if_banned` so it never re-adds someone. |
| **Approve new member** | **Join requests** screen → Approve | `/approve` (reply or id) | Native is the normal path; `/approve` is a convenience for the approval flow. The onboarding handler (VOL-203) may also auto-handle requests. |
| **Trust a new member (links)** | — (no native equivalent) | `/trust` (reply or id) | Bot-only. Lifts the new-user link restriction (VOL-209) for that member. |
| **Slow mode** | **Edit → Permissions → Slow Mode** | — (native only) | Native only. Key emergency lever (see §6). |
| **Close a topic (admin-only posting)** | Topic header → **Close Topic** | — (native only) | Native only. Used for Announcements & Events. |
| **Anti-spam / flood / link auto-moderation** | — | runs automatically (no command) | The bot acts on its own; review via logs (§7). |

**Rule of thumb:** routine single actions → whichever is at hand. Anything you
want an **audit trail** for (bans, mutes, mass deletes during a raid) → prefer
the **bot command**, because every command logs `admin id → target → action →
outcome` in the structured logs (§7).

---

## 2. Telegram admin RIGHTS the bot needs

The bot's commands are just Bot API calls; they only succeed if the **bot
account** holds the matching admin right in the group. These are exactly the
rights granted in `docs/telegram-setup.md` §7. If a right is missing, the command
**fails gracefully** — the bot logs the failure (`outcome=failed
error_type=...`) and replies a friendly "the bot may be missing the '<right>'
admin right" message. It never crashes.

| Bot command(s) | Bot API call | Required bot admin right (`telegram-setup.md` §7) |
|---|---|---|
| `/pin` | `pin_chat_message` | **Pin Messages** |
| `/del`, `/delete` | `delete_message` | **Delete Messages** |
| `/mute`, `/unmute` | `restrict_chat_member` | **Ban / Restrict Members** |
| `/ban`, `/unban` | `ban_chat_member` / `unban_chat_member` | **Ban / Restrict Members** |
| `/approve` | `approve_chat_join_request` | **Invite Users via Link** |
| `/modhelp`, `/trust` | (no Telegram API call) | none (admin gate only) |
| automated anti-spam / flood / link delete + restrict | `delete_message`, `restrict_chat_member` | **Delete Messages** + **Ban / Restrict Members** |

The automated subsystems also rely on **Manage Topics** indirectly (so the bot
can read/act inside forum topics) — keep the full §7 right set enabled. The
single source of truth for the toggles is `docs/telegram-setup.md` §7; do not
narrow them per-command, grant the whole set.

> **Graceful degradation, documented:** every command wraps its API call in
> `try/except`. A `BadRequest`/`Forbidden` from a missing right is logged and
> answered with a friendly failure — the moderator can fall back to the native
> action. Examples: `/pin` without *Pin Messages* → "Couldn't pin…"; `/ban`
> without *Ban / Restrict Members* → "Couldn't ban…"; `/approve` with no pending
> request → "no pending request, or missing 'Invite Users via Link'…".

---

## 3. Authorisation — who can run the bot commands

All moderation commands are gated by `is_admin(update, context)`
(`src/dfeng_bot/handlers/base.py`), which checks the user's id against
`DFENG_ADMIN_IDS` (`Config.is_admin`). The bot does **not** read L1/L2/L3 tiers —
every configured admin id (any tier) can run every moderation command; the tier
distinction is **organisational** (role register in `config/group-setup.yaml`),
per `telegram-setup.md` §9.

- A **non-admin** who runs `/pin`, `/del`, `/mute`, `/ban`, `/approve`, etc.:
  - gets a brief **"Not authorised."** reply, and
  - the attempt is **logged** at WARNING: `action=cmd_<name> outcome=denied`
    with the caller's `telegram_id` / `username`. No privileged action runs.
- Keep `DFENG_ADMIN_IDS` in sync with the group's actual admins; removing an id
  here revokes the bot commands even if the person is still a Telegram admin.

---

## 4. Per-tier runbook (L1 / L2 / L3)

Tiers and their Telegram toggles are defined in `docs/telegram-setup.md` §9. The
bot gives all tiers the same command access; duties below are the **procedural**
split.

### L1 — Community Management (daily moderation)
- **Daily driver of moderation.** Pin/unpin, delete spam, mute/unmute, ban/unban.
- **Approve new members** from the join-requests screen (or `/approve`).
- **Post Announcements** in *Announcements & Events* (a closed topic; L1 is an
  admin so it can post there — see `telegram-setup.md` §8).
- Watch *General Community Chat* and the owners topics; keep conversation healthy.
- Reviews automated-moderation logs (§7) for false positives / missed spam.

### L2 — Dongfeng Support (escalation)
- **All L1 abilities** plus the mandate to handle **product / servicing /
  support escalation** in **Support & Assistance**.
- Picks up issues the bot **redirects** into Support & Assistance (the
  `support_redirect` nudge — VOL-207). See §8.
- Escalates anything requiring Management (config, policy, bans of established
  members) to L3.

### L3 — Management (config & ownership)
- **All L2 abilities** plus **Change Group Info / Settings** and **Add New
  Admins**; the Telegram **Owner** is an L3.
- Owns **bot configuration** (`.env` / `DFENG_*`, including `DFENG_ADMIN_IDS` and
  the feature flags) and **Google Sheets / workbook ownership** (later tickets).
- Enables/disables the automated moderation feature flags (§6) and the emergency
  levers; approves changes to thresholds.

---

## 5. Daily moderation workflow & escalation ownership

**Daily (L1):**
1. Clear the **join-requests** queue — approve legitimate requests (native screen
   or `/approve`); decline obvious spam accounts.
2. Skim the active topics. Delete spam (`/del` or long-press), mute repeat
   offenders (`/mute 30`), pin anything that should stay visible (`/pin`).
3. Use `/trust` on legitimate new members who hit the new-user link restriction
   and need to share a link early.
4. Skim the bot's automated-moderation logs (§7) for `antispam_action` /
   `flood_control` / `link_restriction` events; reverse any false positive
   (`/unmute`, `/unban`) and tune thresholds with L3 if needed.

**Escalation ownership:**
| Situation | Owner |
|---|---|
| Routine spam / pins / mutes / member approvals | **L1** |
| Product / servicing / support questions (Support & Assistance) | **L2** |
| Banning an **established** member, policy calls, repeat-raid decisions | **L2 → L3** |
| Changing config / feature flags / thresholds / admin list / Sheets | **L3** |
| Active raid in progress | **L1 acts immediately**, notifies **L3** (see §6) |

---

## 6. EMERGENCY SPAM RESPONSE playbook (raid)

When the group is hit by a coordinated spam/bot raid, act fast. Steps roughly in
priority order — do what stops the bleeding first.

1. **Enable Slow Mode** (native, fastest blunt instrument):
   **Edit → Permissions → Slow Mode → 30s–60s**. Caps the flood rate instantly,
   group-wide. (Native only; there's no bot command.)
2. **Mute / ban the offenders:**
   - Reply to a spam message with `/mute 60` (temporary) or `/ban` (remove).
   - For an obvious bot account, `/ban` and `/del` its messages.
   - Bulk: delete the spam (`/del` per message or native multi-select), ban the
     accounts.
3. **Tighten the automated anti-spam** (L3 / config, `src/dfeng_bot/config.py`):
   - Ensure `DFENG_FEATURE_ANTISPAM=1` (flag `features.antispam`).
   - Raise `DFENG_SPAM_RESTRICT_AFTER` from 0 to a small N so the bot
     auto-restricts repeat offenders after N removed messages
     (`SpamSettings.restrict_after` / `restrict_seconds`).
   - Turn on **flood control** `DFENG_FEATURE_FLOOD_CONTROL=1` and consider
     `DFENG_RATE_LIMIT_ACTION=mute_delete` with a tighter
     `DFENG_RATE_LIMIT_MESSAGES` / `_WINDOW_SECONDS`.
   - Turn on **link restrictions** `DFENG_FEATURE_LINK_RESTRICTIONS=1` so new
     accounts can't drop links during the raid.
   - Config changes require a **restart** of the bot process to take effect
     (`docs/deployment.md` §5).
4. **Lock down posting if it's overwhelming:** **Close** the noisy topics
   (topic header → Close Topic) so only admins can post until it passes; reopen
   after. *Announcements & Events* is already closed.
5. **Disable a risky/misbehaving bot feature quickly** (if the bot itself is
   over-moderating or a feature backfires): set the relevant flag to `0` and
   restart —
   - `DFENG_FEATURE_ANTISPAM=0` — stop automated spam deletes,
   - `DFENG_FEATURE_FLOOD_CONTROL=0` — stop rate-based mutes,
   - `DFENG_FEATURE_LINK_RESTRICTIONS=0` — stop new-user link blocks,
   - `DFENG_FEATURE_SUPPORT_REDIRECT=0` — stop the support nudge.
   These flags ship features **dark** and let L3 cut any one of them without a
   code change (`FeatureFlags` in `config.py`).
6. **After the raid:** review the logs (§7), `/unmute` / `/unban` any false
   positives, relax Slow Mode / reopen topics, and revert any temporary threshold
   changes with L3.

> The flags `antispam` / `flood_control` / `link_restrictions` are the
> cross-referenced kill-switches: each automated moderation subsystem checks its
> flag on every update, so flipping it off (and restarting) disables it cleanly.

---

## 7. Reviewing the bot's AUTOMATED moderation actions (logs)

The bot moderates automatically and **logs every action** via `log_event`
(`src/dfeng_bot/logging_setup.py`). Reviewing these is how admins audit what the
bot did and catch false positives.

**What gets logged** (action name → subsystem):
| Log `action` | Subsystem | Key fields (all PII-safe) |
|---|---|---|
| `antispam_action` | anti-spam (VOL-208) | `category`, `rule`, `action` (deleted/flagged/restrict), `outcome` |
| `flood_control` | flood control (VOL-210) | `count`, `window_seconds`, `action`, `deleted`, `muted`, `outcome` |
| `link_restriction` | new-user links (VOL-209) | `reason`, `domain`, `action`, `outcome` |
| `support_redirect` | support nudge (VOL-207) | `matched_keyword`, `thread_id`, `outcome` |
| `cmd_pin` / `cmd_delete` / `cmd_mute` / `cmd_unmute` / `cmd_ban` / `cmd_unban` / `cmd_approve` / `cmd_trust` | admin commands (VOL-211) | `target_id` / `target_message_id`, `outcome` (incl. `denied` for rejected non-admin attempts) |

Every line also carries the standard context: `telegram_id` (for commands, this
is the **admin** who ran it), `username`, `chat_id`, `thread_id`, `update_type`.
**No message bodies, tokens, or PII** are ever logged — only ids, the matched
rule/category, actions, and outcomes.

**Where the logs go** (per `docs/deployment.md` §6): structured logs are written
to **stdout/stderr** of the bot process. In production the bot runs as a service
(systemd unit in `deployment.md` §5), so:

- **systemd host:** `journalctl -u dfeng-bot` (the unit name from `deployment.md`
  §5), e.g. `journalctl -u dfeng-bot -f` to follow live.
- **container host:** `docker logs -f <container>` (or the platform's log viewer
  / aggregator).
- **format:** `DFENG_LOG_FORMAT=kv` (default, `action=... key=value`) or
  `json` (one JSON object per line — set this when shipping to a log aggregator).

**How to read / filter** (kv format examples):
- All automated moderation: `journalctl -u dfeng-bot | grep -E 'action=(antispam_action|flood_control|link_restriction)'`
- Just deletions/mutes: `... | grep -E 'outcome=(removed|deleted|muted|restricted)'`
- Failures (missing-right / API errors) to fix permissions:
  `... | grep 'outcome=.*failed'`
- A specific member's history: `... | grep 'telegram_id=<id>'` (commands) or
  `'target_id=<id>'` (who an admin actioned).
- Rejected admin-command attempts: `... | grep 'outcome=denied'`.

> **Future enhancement (documented, not built):** an admin bot command (e.g.
> `/modlog`) could surface the most recent automated actions in-chat so admins
> don't need host log access. Today, review is via the host logs above.

---

## 8. Support escalation guidance (Support & Assistance, L2)

- The bot's **support redirect** (VOL-207, flag `DFENG_FEATURE_SUPPORT_REDIRECT`,
  default ON) watches general chatter for support keywords and nudges users to
  post in **Support & Assistance**, logging `support_redirect`. It does **not**
  resolve the issue — it routes it.
- **L2 (Dongfeng Support) owns Support & Assistance:** monitor that topic, pick
  up redirected questions, and handle product / servicing / support
  **escalation**. Telegram can't scope an admin to one topic (`telegram-setup.md`
  §9), so this is a **procedural** responsibility reinforced by the role register.
- Out of scope here (per the ticket): full CS ticketing, payments, sales,
  bookings, warranty — those live outside Telegram. L2 routes such requests to
  the proper channel rather than resolving them in-chat.
- Escalate to **L3** anything needing config/policy changes or action against an
  established member.

---

## 9. Acceptance criteria checklist

- [x] **Bot admin permissions declared / limitations documented** — §2 maps each
      command to its required Telegram right (cross-ref `telegram-setup.md` §7),
      and documents graceful failure when a right is missing.
- [x] **Authorised admins can moderate; non-admins cannot** — all commands gate
      on `is_admin`; non-admin attempts get "Not authorised." and are logged
      `outcome=denied` (§3).
- [x] **Bot commands implemented** — `/pin`, `/del`/`/delete`, `/mute`,
      `/unmute`, `/ban`, `/unban`, `/approve`, `/modhelp` in
      `src/dfeng_bot/handlers/moderation.py`, registered via
      `build_moderation_handlers()` in `register_handlers` (app.py untouched).
- [x] **Graceful permission-error handling** — every API call is wrapped in
      `try/except`, logs the failure, and replies a friendly message; never
      crashes (§2).
- [x] **Native vs bot-command table** — §1.
- [x] **Per-tier runbook (L1/L2/L3)** — §4, cross-ref `telegram-setup.md` §9.
- [x] **Daily workflow & escalation ownership** — §5.
- [x] **Emergency spam response playbook** — §6, cross-ref the
      antispam/flood/link feature flags.
- [x] **Automated moderation logs reviewable via a documented process** — §7
      (`journalctl` / `docker logs`, grep filters), cross-ref `deployment.md` §6.
- [x] **Support escalation guidance** — §8.
- [x] **PII/secrets kept out of logs** — only ids, actions, outcomes; no message
      bodies/tokens (per `logging_setup.py` convention).
