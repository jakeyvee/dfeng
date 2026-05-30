# Launch Smoke Test — Dongfeng Experience Community bot (VOL-213)

A short **deploy-side** checklist to confirm each subsystem is alive in
production (or a staging clone of the live supergroup) right after deploying per
`docs/production-deployment.md`. Tick each box; note the log line you saw.

> **Scope:** this verifies the deployment is wired correctly (token, IDs, admin
> rights, Sheets, flags). It is NOT exhaustive functional QA — full end-to-end
> testing is **VOL-214**. Don't re-test every edge case here; just confirm each
> subsystem responds once.

**Before you start**
- [ ] Bot is running (`action=startup` then `action=starting_polling` in logs).
- [ ] Startup `safe_summary()` shows the expected `features` (anti-spam, flood,
      link restrictions, sheets all `true`) and the six topic ids.
- [ ] You have a **non-admin test account** in the group (most checks need a
      non-admin, since admins are exempt from spam/flood/link rules by default).
- [ ] You can tail logs (`docker compose logs -f` / `journalctl -u dfeng-bot -f`).

Legend: **PASS** ☐ / **FAIL** ☐ — fill the relevant box; jot the observed log
`action=...`.

---

## 1. Health / connectivity
- [ ] `/ping` in any topic → replies `pong (thread_id=<n>)` **in that same topic**.
  - PASS ☐  FAIL ☐ — log: `action=cmd_ping`

## 2. Welcome on join
- [ ] A new member joins (or approve a pending join request) → bot posts the
      welcome message.
  - PASS ☐  FAIL ☐ — log: `action=new_member` then `action=welcome_sent`

## 3. Qualification → tag
- [ ] Complete the qualification flow as the new member → a tag is assigned
      (BOX / 007 / VIGO Owner or Prospect).
  - PASS ☐  FAIL ☐ — log: `action=qualification...` with the resolved `tag=`

## 4. Sheets write (row appears)
- [ ] After qualification (+ optional PDPA capture), a **row appears** in the
      `Members` tab for the test member (Telegram ID, username, tag, entry source,
      timestamps populated; admin columns untouched).
  - PASS ☐  FAIL ☐ — log: write enqueued/written (no `member_persist_exhausted`)
- [ ] `/sheets_status` (admin) shows the queue healthy (pending/in-flight drained,
      dead-letter 0).
  - PASS ☐  FAIL ☐ — log: `action=cmd_sheets_status outcome=ok`

## 5. Support-keyword redirect
- [ ] Post a support-flavoured message **outside** Support & Assistance → bot
      nudges toward the Support topic.
  - PASS ☐  FAIL ☐ — log: `action=support_redirect matched_keyword=...`

## 6. Anti-spam removal
- [ ] As the **non-admin** test account, post a clearly spammy link / blocked
      keyword (use a known shortener or scam-pattern, NOT a real victim link) →
      the message is removed.
  - PASS ☐  FAIL ☐ — log: `action=antispam_action ... outcome=removed`

## 7. New-user link restriction
- [ ] As a **brand-new, untrusted** non-admin (just joined, < trust threshold),
      post a normal link → it is blocked/removed (and a friendly notice unless
      `DFENG_LINK_SILENT=1`).
  - PASS ☐  FAIL ☐ — log: `action=link_restriction ... outcome=removed`
- [ ] An admin runs `/trust` on that member → they can then post a link.
  - PASS ☐  FAIL ☐ — log: `action=cmd_trust outcome=ok`

## 8. Flood control
- [ ] As the non-admin test account, send more than `DFENG_RATE_LIMIT_MESSAGES`
      messages within `DFENG_RATE_LIMIT_WINDOW_SECONDS` (default > 8 / 10s) → the
      configured action fires (default: temporary auto-expiring mute).
  - PASS ☐  FAIL ☐ — log: `action=flood_control ... outcome=muted` (or your action)
  - Note: the default mute auto-expires (`DFENG_RATE_LIMIT_MUTE_SECONDS`); reverse
    early with `/unmute` if needed.

## 9. Admin moderation command
- [ ] An admin replies to a message with `/del` (or `/pin` / `/mute 1`) → the
      action succeeds and is logged with the admin id.
  - PASS ☐  FAIL ☐ — log: `action=cmd_delete ... outcome=...`
- [ ] A **non-admin** runs a moderation command → "Not authorised." + logged
      `outcome=denied` (confirms the admin gate).
  - PASS ☐  FAIL ☐ — log: `action=cmd_... outcome=denied`

## 10. Metrics / observability commands
- [ ] `/stats` (admin) → reports process-lifetime metric counters.
  - PASS ☐  FAIL ☐ — log: `action=cmd_stats outcome=ok`
- [ ] `/sheets_status` checked in §4 above.

---

## Permission sanity (if anything above failed with `outcome=...failed`)
- [ ] Re-check the bot's admin rights (`docs/telegram-setup.md` §7 /
      `docs/production-deployment.md` §5): Delete Messages, Ban/Restrict, Pin,
      Manage Topics, Invite via Link. A missing right degrades that one feature
      gracefully (logged, friendly reply) — it does not crash the bot.

## Alerting check
- [ ] Confirm the v1 alert path (cron grep / log drain) fires on a test pattern
      (`docs/production-deployment.md` §8).

---

## Result

- Deploy date / env: ____________________
- Tester: ____________________
- All subsystems PASS? ☐ Yes  ☐ No (list failures + tickets) ____________________

Hand off to **VOL-214** for full end-to-end QA.
