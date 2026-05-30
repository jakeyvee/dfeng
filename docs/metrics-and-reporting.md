# Launch Metrics & Reporting — Dongfeng Experience Community bot (VOL-212)

Lightweight, no-warehouse instrumentation + a repeatable procedure so an admin
can compute the seven PRD launch metrics from two sources only:

1. **Structured bot logs** — every event goes through `log_event()`
   (`src/dfeng_bot/logging_setup.py`). Each line carries `action=<name>` plus
   context fields (`telegram_id`, `username`, `thread_id`, `outcome`, …). Format
   is `kv` (default) or `json` (`DFENG_LOG_FORMAT=json`, recommended for
   reporting — easier to `jq`).
2. **Google Sheets member workbook** — one row per member; the source of truth
   for total members, tags, entry source, and joined timestamp. Schema:
   `src/dfeng_bot/services/schema.py` (columns: `Telegram ID`, `Telegram
   username`, `Tag`, `Optional phone`, `Optional plate`, `Consent timestamp`,
   `Entry source`, `Joined timestamp`, plus admin columns).

There is **no BI dashboard** in v1 (out of scope). This doc is the dashboard.

> **PRD targets (Month 1 / 3 / 6 / 12):** The numeric checkpoint targets come
> from the project PRD, which is **not committed to this repo**. Each metric
> below has a `TARGETS:` line — fill the four numbers in from the PRD before the
> first report. The data sources and queries are complete and ready to run now.

---

## 0. Where the logs live & how to collect them

Per `docs/deployment.md`, the bot logs to **stdout/stderr** as a single
long-lived process (systemd unit / container). To get a log file to query:

```bash
# systemd (journald): export the bot's logs for a window to a file
journalctl -u dfeng-bot --since "7 days ago" -o cat > /tmp/dfeng-7d.log

# container (docker): same idea
docker logs --since 168h dfeng-bot > /tmp/dfeng-7d.log 2>&1
```

For the `jq` examples below, run the bot with `DFENG_LOG_FORMAT=json` so each
line is a JSON object. The `grep` examples work with either format.

A note on **windows**: "weekly" = a rolling 7-day window. Scope the collection
step (`--since "7 days ago"`) to the window, then the queries below count within
that file. Telegram is the live system of record for *current* membership; logs
are the system of record for *events over time*.

### Quick reference — canonical event actions (see `src/dfeng_bot/metrics.py`)

| Action (`action=`)        | Emitted by                         | Added/Existing |
|---------------------------|------------------------------------|----------------|
| `message_activity`        | `messages.handle_message`          | **NEW (VOL-212)** |
| `qualification_started`   | `qualification.py`                 | existing (VOL-204) |
| `qualification_complete`  | `qualification.py` (`tag=`,`path=`)| existing (VOL-204) |
| `support_redirect`        | `support_redirect.py` (`matched_keyword=`) | existing (VOL-207) |
| `support_redirect_skipped`| `support_redirect.py` (cooldown)   | existing (VOL-207) |
| `antispam_action`         | `antispam.py` (`outcome=removed`)  | existing (VOL-208) |
| `flood_control`           | `flood_control.py` (`outcome=actioned`) | existing (VOL-210) |
| `link_restriction`        | `link_restrictions.py` (`outcome=removed`) | existing (VOL-209) |
| `cmd_delete`              | `moderation.py` (`outcome=deleted`)| existing (VOL-211) |

`message_activity` is the only NEW event. It is flag-gated on
`DFENG_METRICS_ACTIVITY` (default ON) and logs **only** `telegram_id`,
`thread_id`, `tag` (if known), and `is_question` (a coarse heuristic boolean) —
never the message body, phone, or plate.

---

## 1. Total community members

- **Primary source — Sheets:** row count of the member workbook (exclude the
  header row). Each member is one row keyed by `Telegram ID`.
  - Sheets formula in a spare cell: `=COUNTA(A2:A)` (column A = `Telegram ID`).
- **Cross-check — Telegram:** group member count shown in the Telegram client
  (or `getChatMemberCount` via the Bot API). Use this to spot drift between the
  workbook and the live group (members who left, or joined before the bot).
- **From logs (lower bound, optional):** distinct members the bot has seen join.
  ```bash
  grep 'action=new_member ' /tmp/dfeng-7d.log | grep -o 'member_id=[0-9]*' | sort -u | wc -l
  ```
- **Type:** authoritative (Sheets). **TARGETS:** M1 __ / M3 __ / M6 __ / M12 __.

---

## 2. Weekly active members as % of total  *(PROXY)*

- **Definition:** distinct members who posted at least one message in the last
  7 days ÷ total members (metric #1).
- **Source — logs:** the NEW `message_activity` event, one per legitimate
  (non-spam, non-command) message. Count distinct `telegram_id`.
- **PROXY note:** "active" here = *posted a message*. Lurkers who only read are
  not counted (Telegram does not expose per-user read activity to bots). Mark
  the figure "active = posted ≥1 msg / 7d".
- **Compute (json logs):**
  ```bash
  # distinct posters in the window
  DISTINCT=$(jq -r 'select(.action=="message_activity") | .telegram_id' /tmp/dfeng-7d.log | sort -u | wc -l)
  echo "weekly active posters: $DISTINCT"
  # then: weekly active % = DISTINCT / total_members (from metric #1) * 100
  ```
  kv-format equivalent:
  ```bash
  grep 'action=message_activity ' /tmp/dfeng-7d.log | grep -o 'telegram_id=[0-9]*' | sort -u | wc -l
  ```
- **TARGETS:** M1 __% / M3 __% / M6 __% / M12 __%.

---

## 3. Owner-initiated messages per week in BOX / 007 / VIGO lounges  *(PROXY)*

- **Definition:** count of `message_activity` events where `tag` is an Owner tag
  (`BOX Owner` / `007 Owner` / `VIGO Owner`) AND the message landed in a model
  lounge topic.
- **Sources:** `tag` comes from qualification (stashed in `user_data` and logged
  on each activity event) and/or the Sheets `Tag` column. `thread_id` identifies
  the topic.
- **Mapping model lounges → `thread_id`:** the lounge topic ids are deployment
  config (the `DFENG_TOPIC_*` family in `.env`; see `docs/deployment.md`
  "Finding chat / topic / user IDs"). Record the BOX/007/VIGO lounge thread ids
  once, then filter by them. *If model lounges are not yet separate topics, drop
  the `thread_id` filter and report owner messages community-wide — mark as
  such.*
- **PROXY notes:** (a) `tag` is only known for members who completed/were
  defaulted by qualification and whose `user_data` is live this process —
  back-fill unknowns from the Sheets `Tag` column by joining on `telegram_id`;
  (b) per-process `user_data` resets on restart, so for a long window prefer the
  Sheets join over the logged `tag`.
- **Compute (json logs, replace lounge ids):**
  ```bash
  LOUNGES="111 222 333"   # BOX, 007, VIGO thread ids from .env
  jq -r --argjson l "[${LOUNGES// /,}]" '
    select(.action=="message_activity")
    | select((.tag // "") | test("Owner"))
    | select(.thread_id as $t | $l | index($t))
    | .telegram_id' /tmp/dfeng-7d.log | wc -l
  ```
- **TARGETS:** M1 __ / M3 __ / M6 __ / M12 __ owner messages/week.

---

## 4. Prospect-initiated questions per week in model lounges + General  *(PROXY)*

- **Definition:** count of `message_activity` events where `tag == "Prospect"`,
  `is_question == true`, and `thread_id` is a model lounge or General.
- **PROXY / approximation:** "question" is hard to classify. The bot uses a
  **coarse, documented heuristic** (`metrics.looks_like_question`): the message
  contains a `?` OR starts with an interrogative word (who/what/when/where/why/
  how/which/is/are/can/could/do/does/did/should/would/will/may/any…). This
  over- and under-counts; treat it as a directional proxy, not an exact count.
  The heuristic reads the text transiently and **never logs it**.
- **Compute (json logs):**
  ```bash
  TOPICS="111 222 333 444"   # BOX, 007, VIGO, General thread ids
  jq -r --argjson l "[${TOPICS// /,}]" '
    select(.action=="message_activity")
    | select((.tag // "") == "Prospect")
    | select(.is_question == true)
    | select(.thread_id as $t | $l | index($t))
    | .telegram_id' /tmp/dfeng-7d.log | wc -l
  ```
  kv quick count (questions from prospects, any topic):
  ```bash
  grep 'action=message_activity ' /tmp/dfeng-7d.log | grep 'is_question=True' | grep 'tag="Prospect"' | wc -l
  ```
- **TARGETS:** M1 __ / M3 __ / M6 __ / M12 __ prospect questions/week.

---

## 5. % of support-keyword posts auto-routed to Support & Assistance

- **Definition:** support-keyword messages the bot redirected ÷ all support-
  keyword occurrences detected.
- **Sources — logs (both already emitted by `support_redirect.py`):**
  - numerator: `action=support_redirect` (`outcome=redirected`) — a nudge sent.
  - denominator: `support_redirect` **plus** `support_redirect_skipped`
    (`outcome=cooldown`). Both fire only when a keyword matched, so their sum =
    total support-keyword posts the bot saw (outside the Support topic). This is
    exactly the data needed — no extra logging required.
- **Caveat:** keyword posts made *inside* the Support topic are intentionally
  not detected (no self-redirect loop), so the denominator is "support-keyword
  posts in non-support topics". That matches the metric's intent (routing *to*
  Support).
- **Compute:**
  ```bash
  R=$(grep -c 'action=support_redirect '         /tmp/dfeng-7d.log)
  S=$(grep -c 'action=support_redirect_skipped ' /tmp/dfeng-7d.log)
  python3 -c "r,s=$R,$S; print(f'{100*r/(r+s):.0f}%' if r+s else 'n/a')"
  ```
  (json: `jq -r 'select(.action|test("support_redirect")) | .action'` then tally.)
- **Type:** computable from logs. **TARGETS:** M1 __% / M3 __% / M6 __% / M12 __%.

---

## 6. Bot onboarding completion rate

- **Definition:** members who completed qualification ÷ members who started it.
- **Sources — logs (both already emitted by `qualification.py`):**
  - started: `action=qualification_started` (on join hand-off and `/qualify`).
  - completed: `action=qualification_complete` (carries `tag=` and `path=`).
- **Compute:**
  ```bash
  STARTED=$(grep -c 'action=qualification_started '  /tmp/dfeng-7d.log)
  DONE=$(grep -c 'action=qualification_complete '    /tmp/dfeng-7d.log)
  python3 -c "s,d=$STARTED,$DONE; print(f'{100*d/s:.0f}%' if s else 'n/a')"
  ```
  Breakdown by resulting tag (Owner vs Prospect):
  ```bash
  grep 'action=qualification_complete ' /tmp/dfeng-7d.log | grep -o 'tag="[^"]*"\|tag=[^ ]*' | sort | uniq -c
  ```
- **Live cross-check:** `/stats` (§8) shows started/completed/rate for the
  current process lifetime.
- **Type:** computable from logs. **TARGETS:** M1 __% / M3 __% / M6 __% / M12 __%.

---

## 7. % of spam removed by automation vs manual

- **Definition:** automated removals ÷ (automated + manual) removals.
- **Automated — logs (already emitted):**
  - `action=antispam_action` with `outcome=removed` (VOL-208).
  - `action=flood_control` with `outcome=actioned` (VOL-210).
  - `action=link_restriction` with `outcome=removed` (VOL-209).
- **Manual — logs (where available):** `action=cmd_delete` with
  `outcome=deleted` — admin `/del` / `/delete` (VOL-211). *Manual side is
  "where-available": an admin deleting via the Telegram client UI (not the bot
  command) is invisible to the bot and cannot be counted.* Mark accordingly.
- **Compute:**
  ```bash
  AUTO=$(grep -hE 'action=antispam_action .*outcome=removed|action=flood_control .*outcome=actioned|action=link_restriction .*outcome=removed' /tmp/dfeng-7d.log | wc -l)
  MANUAL=$(grep -E 'action=cmd_delete .*outcome=deleted' /tmp/dfeng-7d.log | wc -l)
  python3 -c "a,m=$AUTO,$MANUAL; print(f'{100*a/(a+m):.0f}% automated' if a+m else 'n/a')"
  ```
- **Type:** computable from logs (manual side: bot-command deletions only).
  **TARGETS:** M1 __% / M3 __% / M6 __% / M12 __%.

---

## 8. `/stats` — live, process-lifetime snapshot (NOT historical)

`/stats` is an **admin-only** command (gated by `is_admin`). It reports tiny
in-memory counters tallied since the process last started — useful for a quick
"is instrumentation working / what happened this run" check. It is **not** a
substitute for the windowed log queries above (counters reset on every restart
and are single-instance). Reported figures, all PII-free integers:

- onboarding: `completed / started` (+ rate %)
- support redirects
- automated spam removals (antispam + flood + link)
- messages seen (with owner / prospect breakdown)

Counters live in `MetricCounters` (`src/dfeng_bot/metrics.py`), stored in
`application.bot_data`. They hold only small integers — no ids, text, or PII.

---

## 9. Repeatable weekly reporting procedure (for a new admin)

No project context required. Run once a week:

1. **Pick the window** and collect logs to a file (see §0):
   ```bash
   journalctl -u dfeng-bot --since "7 days ago" -o cat > /tmp/dfeng-7d.log
   ```
   (Run the bot with `DFENG_LOG_FORMAT=json` for the `jq` snippets; `grep`
   snippets work either way.)
2. **Total members (§1):** open the member workbook, read `=COUNTA(A2:A)`; note
   the Telegram member count too. Call this `TOTAL`.
3. **Record the topic thread ids** for the BOX / 007 / VIGO lounges and General
   from `.env` (`DFENG_TOPIC_*`) — needed for metrics #3 and #4. Do this once;
   they rarely change.
4. **Run each metric's snippet** (§2–§7) against `/tmp/dfeng-7d.log`. For #2,
   divide the distinct-poster count by `TOTAL`.
5. **Fill the report row** below; carry forward the PRD `TARGETS:` for the
   current checkpoint month and flag any miss.
6. **Sanity check** with `/stats` in the group (process-lifetime only) — numbers
   should be the same order of magnitude as the windowed counts since the last
   restart.

### Report template (copy per week)

| Metric | Value | Target (this month) | Proxy/Manual? |
|--------|-------|---------------------|---------------|
| 1. Total members | | | authoritative (Sheets) |
| 2. Weekly active % | | | PROXY (posted ≥1 msg) |
| 3. Owner msgs/wk (lounges) | | | PROXY (tag + topic) |
| 4. Prospect questions/wk | | | PROXY (`?`/interrogative heuristic) |
| 5. Support auto-route % | | | from logs |
| 6. Onboarding completion % | | | from logs |
| 7. Spam automated % | | | manual side = bot `/del` only |

---

## 10. Privacy / PII guarantee

Metrics collection does **not** expand the agreed personal-data scope:

- The only NEW event, `message_activity`, logs `telegram_id` (already logged
  bot-wide), `thread_id` (a forum topic id), `tag` (a BOX/007/VIGO/Prospect
  enum), and `is_question` (a boolean). **No message body, phone, or plate is
  ever logged** — the text is inspected transiently only to compute
  `is_question`. See the `metrics._selftest()` PII guard.
- In-memory `/stats` counters hold only small integers — no ids, no text, no PII.
- To disable the activity event entirely, set `DFENG_METRICS_ACTIVITY=0` (the
  weekly-active / owner / prospect metrics then become uncomputable from logs,
  but no feature behaviour changes).
