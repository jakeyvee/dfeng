# Storage scaling plan — when & how to migrate off Google Sheets

**Ticket:** VOL-217 · **Project:** Dongfeng Experience Community · **Status:** post-launch planning artifact (no code changes)

This is a **forward-looking planning doc**, not a v1 deliverable. Google Sheets is
the v1 member store and is the right call for launch: zero infra, admin-editable in
a familiar UI, and adequate up to roughly **~1,000 active members**. This doc
defines:

1. The **observable triggers** that say "it's time to migrate".
2. A short **options comparison** (Supabase vs SeaTable vs staying on Sheets) with a recommendation.
3. A **target `members` table schema** mapped from the v1 Sheets columns.
4. The **migration shape** (export → load → cut over behind the existing service interface → verify → fallback).
5. The **anti-lock-in story**: the abstraction seams that already exist in code, what leaks, and a recommended follow-up issue.

Nothing here blocks v1 or changes behaviour. Do **not** implement any of it until a trigger below fires.

---

## 1. When to migrate — observable trigger thresholds

The PRD notes Sheets is fine through ~1,000 members but gets sluggish / quota-bound
approaching **1,500–2,000 active members**. The relevant Google quotas (per
`docs/google-sheets-setup.md` and the `write_queue.py` module docstring) are:

- **300 read requests / minute / project**
- **300 write requests / minute / project**
- **60 requests / minute / user** (the service account is one "user")

Each member upsert costs **1 read + 1 write** today, because
`GoogleSheetsService.update_member_row` first calls `find_row_by_telegram_id`
(a `col_values` read) and then writes. The `WriteQueue` already throttles to
`min_write_interval = 1.1s` (~54 writes/min sustained) precisely to stay under the
60 req/min/user ceiling. That throttle is the early-warning canary: when normal
traffic routinely saturates it, the headroom is gone.

Migrate when **any one** of the following is observed. Each is tied to a concrete,
already-emitted signal (logs / queue stats from VOL-206 + VOL-212), so no new
instrumentation is required to watch for them.

| # | Trigger | Concrete threshold | How it's observed |
|---|---------|--------------------|-------------------|
| T1 | **Sheets API quota errors (429s)** | Any sustained `429 RESOURCE_EXHAUSTED` from gspread — e.g. `member_persist_retry` with `error_type` reflecting a 429/`APIError` appearing more than a few times/day, or any `member_persist_exhausted`. | `member_persist_retry` (WARNING) and `member_persist_exhausted` (ERROR, `outcome=needs_reconciliation`) logs from `write_queue.WriteQueue._process` / `_handle_exhausted`. Grep `action=member_persist_retry` / `action=member_persist_exhausted`. |
| T2 | **Write-queue backlog** | `pending` regularly > ~50, or `inflight` pinned, i.e. the queue is not draining within the 1.1s throttle. | `WriteQueue.stats()` → `{pending, inflight, dead_letter, processed_ok, ...}`, surfaced by the admin `/sheets_status` command (VOL-206). Also the `member_enqueued` log carries a live `pending` count. |
| T3 | **Dead-letter growth** | `dead_letter` > 0 outside of a known Sheets outage, or any non-trivial `dropped_full` count. | `WriteQueue.stats()["dead_letter"]` / `["dropped_full"]` and `WriteQueue.dead_letters()` (PII-free), plus the `member_persist_exhausted` ERROR log. A growing dead-letter list means writes are being permanently lost. |
| T4 | **Active member count** | Approaching **~1,500** (plan the migration) / **~2,000** (execute it). | Metric #1 in `docs/metrics-and-reporting.md`: `=COUNTA(A2:A)` row count of the Members tab, cross-checked against Telegram's `getChatMemberCount`. |
| T5 | **Workbook sluggishness / latency** | `find_row_by_telegram_id` is an **O(rows)** full-column scan; once the sheet is large each upsert's read climbs, the per-write round-trip slows, and the queue throttle stops being the bottleneck. Watch for rising time-to-drain at steady join volume, and the workbook itself feeling laggy for admins in the browser. | Indirectly: `pending` staying elevated under unchanged join rate (T2), and admin reports. (No per-call latency metric exists in v1; rising `pending` is the proxy.) |
| T6 | **Admin workflow pain** | Admins editing the `Notes` / `Status` / `Deletion requested` / `Last reconciled` columns (the admin-owned range) find the sheet slow, hit "calculating…" stalls, or fear clobbering bot writes; reconciliation of dead-letters becomes a recurring chore. | Qualitative — admin feedback + frequency of `/reconcile` / `/sheets_status` use. Tie to T1–T3 (reconciliation load scales with quota pressure). |

**Rule of thumb:** T4 (≈1,500 members) is the *plan-now* signal; T1/T2/T3
appearing **before** then means quota pressure arrived early (e.g. a roadshow
join spike) and should be treated as "migrate sooner". A single transient 429
during a 50-join spike is expected and absorbed by the queue — it's the
*sustained / recurring* pattern that trips the trigger.

---

## 2. Options comparison

Three realistic paths. All of them sit behind the **same** bot-side interface
(`SheetsService` / `build_sheets_service`; see §5), so the choice is about the
backend, not a bot rewrite.

| Dimension | **Stay on Sheets (longer)** | **Supabase (Postgres)** | **SeaTable (spreadsheet-like DB)** |
|-----------|-----------------------------|--------------------------|------------------------------------|
| Data model | Positional rows; no real types | Real relational schema, typed columns, constraints, enums | Typed columns + views, but a hosted-app data model |
| Scale ceiling | ~1–2k members, then quota/latency bound | Millions of rows; indexed PK lookups are O(log n) | Comfortably past 2k; soft row caps by plan |
| Admin-editable | Excellent (native Sheets UI) | Indirect — Supabase Studio / SQL, or a future admin portal (out of scope) | **Good** — grid UI close to a spreadsheet for non-technical admins |
| Concurrency safety | Manual: bot-owned vs admin-owned **column split** to avoid clobbering | Native — row locks, transactions; no column-ownership hack needed | Row-level; better than Sheets, weaker guarantees than Postgres |
| Async fit with the bot | gspread is **sync**, wrapped in `asyncio.to_thread` | Async-native Postgres drivers (`asyncpg` / `supabase-py`) match the async PTB bot | HTTP API; async via `httpx`, similar to today's to_thread pattern |
| Query / reporting | `COUNTA`, manual `jq` over logs | Real SQL — the VOL-212 metrics become queries, not grep | API + built-in views; weaker ad-hoc SQL |
| PDPA / data residency | Google (named-account sharing, per-sheet scope) | Choose region at project create (e.g. Singapore `ap-southeast-1`); RLS; explicit access control | Hosted (cloud) or self-host; residency depends on plan/host |
| Cost | Free | Free tier covers this volume; ~US$25/mo Pro if needed | Free tier; paid tiers per seats/rows |
| Ops burden | None (already provisioned) | Low (managed Postgres) — backups, branching, dashboards included | Low (managed) — but a second vendor with its own model |
| Lock-in risk | n/a | Low — it's standard Postgres; `pg_dump` exports anywhere | Higher — SeaTable's API/model is proprietary |

### Recommendation: **Supabase (managed Postgres)**

Rationale, specific to this bot:

- **Schema fit.** The v1 data is already a clean, typed, single-key table
  (`schema.MEMBER_COLUMNS`, keyed by `Telegram ID`, with two constrained enums —
  `TAGS`, `ENTRY_SOURCES`). That maps **directly** onto a Postgres `members`
  table with a `bigint` primary key and two `CHECK`/enum constraints (see §3).
  Postgres expresses the existing invariants as real constraints instead of the
  current convention-and-data-validation approach.
- **Kills the trigger conditions at the source.** A PK lookup is an indexed
  O(log n) point read, so the **T5 full-column-scan problem disappears** and the
  T1 read+write quota model (1 read + 1 write per upsert) is replaced by a single
  `INSERT ... ON CONFLICT (telegram_id) DO UPDATE` (a true upsert) with no
  per-project request quota in this regime. The `WriteQueue` throttle/backoff can
  stay as-is (cheap insurance) or be relaxed.
- **Async-native.** The bot is async python-telegram-bot v21. An async Postgres
  driver removes the gspread "sync wrapped in `to_thread`" friction
  (CLAUDE.md tech-stack note), though keeping `to_thread`-style wrapping is also
  fine for a drop-in backend.
- **Concurrency without the hack.** The bot-owned (1–8) vs admin-owned (9–12)
  **column split** exists purely to keep bot appends from clobbering concurrent
  admin edits in Sheets. With row-level writes / transactions in Postgres that
  split is no longer load-bearing for safety — the bot can update only its own
  columns by name, and admin edits are independent rows of work.
- **PDPA-friendly.** Create the project in a Singapore region, use Row Level
  Security, and keep PII columns (`Optional phone`, `Optional plate`) access-
  controlled. The retention/deletion flow (`Deletion requested` / `Status`) maps
  to a real status column and an actual `DELETE`/anonymise statement.
- **Low lock-in.** It's plain Postgres; if we ever leave, `pg_dump` moves the
  data anywhere. (SeaTable's value is the admin grid UI, but it trades that for a
  more proprietary model and a weaker concurrency/SQL story — and an admin portal
  is explicitly **out of scope** for now, so the grid UI isn't a deciding factor
  yet.)

**When SeaTable would win instead:** if the dominant requirement turned out to be
"non-technical admins must keep editing rows in a spreadsheet-grid UI and we will
*not* build any admin portal", SeaTable's grid is closer to the Sheets experience
than Supabase Studio. Given the structured schema, async bot, and PDPA posture,
Postgres is the stronger default.

**Staying on Sheets longer** is valid *only* while none of T1–T6 fire. Once
quota errors or dead-letters appear, it stops being a no-ops option.

---

## 3. Target schema — proposed `members` table

Direct mapping from `src/dfeng_bot/services/schema.py`
(`BOT_COLUMNS` + `ADMIN_COLUMNS` = `MEMBER_COLUMNS`). The **Telegram ID stays the
primary key**. The two enums (`TAGS`, `ENTRY_SOURCES`) become Postgres enums (or
`CHECK` constraints). Consent and join timestamps become real `timestamptz`.
Admin reconciliation columns are preserved verbatim.

| Sheets column (v1) | Target field | Type | Constraints / notes |
|--------------------|--------------|------|---------------------|
| Telegram ID | `telegram_id` | `bigint` | **PRIMARY KEY**. `schema.KEY_COLUMN`; stable identity. Enables true upsert (`ON CONFLICT`). |
| Telegram username | `telegram_username` | `text` | Nullable. Public `@handle`; may be empty. |
| Tag | `tag` | `member_tag` enum | NOT NULL. Enum values = `schema.TAGS`: `BOX Owner`, `007 Owner`, `VIGO Owner`, `Prospect`. |
| Optional phone | `optional_phone` | `text` | Nullable. **PII** (`schema.PII_COLUMNS`) — never logged; RLS-restricted. |
| Optional plate | `optional_plate` | `text` | Nullable. **PII** — never logged; RLS-restricted. |
| Consent timestamp | `consent_at` | `timestamptz` | NOT NULL. ISO-8601 UTC when PDPA consent captured. |
| Entry source | `entry_source` | `entry_source` enum | NOT NULL. Enum values = `schema.ENTRY_SOURCES`: `salesperson`, `showroom QR`, `roadshow QR`, `Linktree`, `event QR`, `website placeholder`. |
| Joined timestamp | `joined_at` | `timestamptz` | NOT NULL. When the member joined the community. |
| Notes | `notes` | `text` | Nullable. Admin-owned (free text). |
| Status | `status` | `text` | Nullable. Admin-owned lifecycle label (`active` / `left` / `NEEDS_RECONCILIATION` — `schema.RECONCILE_STATUS_VALUE`). |
| Deletion requested | `deletion_requested` | `text` / `timestamptz` | Nullable. Admin-owned; PDPA deletion/retention marker. |
| Last reconciled | `last_reconciled_at` | `timestamptz` | Nullable. Admin-owned; last reconciliation pass. |

Reference DDL sketch (illustrative — do not run as part of v1):

```sql
create type member_tag   as enum ('BOX Owner','007 Owner','VIGO Owner','Prospect');
create type entry_source as enum ('salesperson','showroom QR','roadshow QR',
                                  'Linktree','event QR','website placeholder');

create table members (
  telegram_id         bigint primary key,
  telegram_username   text,
  tag                 member_tag  not null,
  optional_phone      text,        -- PII
  optional_plate      text,        -- PII
  consent_at          timestamptz not null,
  entry_source        entry_source not null,
  joined_at           timestamptz not null,
  -- admin-owned (the bot writes only `status` for the reconcile flag)
  notes               text,
  status              text,
  deletion_requested  timestamptz,
  last_reconciled_at  timestamptz
);
```

Notes:

- **Enums** make the v1 "allowed values" lists (today enforced only by optional
  Sheets data-validation) into hard DB constraints.
- The bot/admin **column-ownership split** becomes a *convention* (the bot writes
  bot-owned columns + the single `status` reconcile flag), no longer a *safety
  mechanism* — Postgres row writes don't clobber each other the way concurrent
  Sheets cell writes can.
- **PII** columns map 1:1 and remain off-logs; enforce access with RLS so only the
  service role and named admins can read them.

---

## 4. Migration shape

High-level, low-risk, reversible. Designed so the bot's call sites never change
(§5) — only the backend behind `build_sheets_service` is swapped.

1. **Provision** a Supabase project in a Singapore region. Create the `members`
   table + enums (§3). Configure RLS so the bot's service role can read/write and
   named admins can read/edit; restrict PII columns.
2. **Export** the current Members tab (e.g. download as CSV, or read via the
   existing `GoogleSheetsService`). Volume is small — at the ~1.5–2k-member
   trigger this is **a few thousand rows of text**: a seconds-to-minutes job, not
   a data-engineering project.
3. **Load / backfill** the export into `members`, mapping columns per §3 and
   coercing the timestamp strings to `timestamptz` and enums. Validate row count
   matches `COUNTA(A2:A)` and that every `Tag` / `Entry source` is a legal enum
   value (catch any historical drift here).
4. **Implement a `SupabaseMembersService`** that satisfies the same surface the
   bot already depends on — `append_member` / `find_member` and the schema-aware
   methods (`ensure_header` no-ops or verifies the table, `find_row_by_telegram_id`
   → a PK lookup, `append_member_row` / `update_member_row` → upsert,
   `flag_needs_reconciliation` → set `status`). Have `build_sheets_service` return
   it under a config flag (e.g. a `DFENG_STORAGE_BACKEND` switch).
5. **Cut over** by flipping the factory flag. Because `WriteQueue` rebuilds the
   service per drain via its `service_factory` (`lambda: build_sheets_service(config)`),
   the queue picks up the new backend with no queue changes. `persist_member`
   (the VOL-205 seam) is unchanged.
6. **Verify** in production: new joins land in Postgres; `WriteQueue.stats()`
   shows `dead_letter == 0` and `pending` draining; spot-check a handful of
   members against the old sheet.
7. **Keep Sheets as a read-only fallback** for one retention cycle: leave the
   workbook in place (read-only to the bot) so reporting/back-reference still
   works and a rollback (flip the flag back) is trivial. Decommission once
   confidence is high and the VOL-212 reporting queries have been repointed to SQL.

**Effort note:** small data volume, mechanical mapping, and a pre-existing
interface make this a **modest** effort — the real work is (a) writing the new
backend class against the existing Protocol and (b) the careful one-time
backfill/verify, not a bot rearchitecture.

---

## 5. Replaceability / anti-lock-in

The bot was built so storage is replaceable. The seams **already in code**:

- **`SheetsService` Protocol** (`services/sheets.py`) — a `runtime_checkable`
  `Protocol` (`append_member`, `find_member`) that callers can depend on instead
  of a concrete client. CLAUDE.md states the rule: *"Services are interfaces to
  external systems… Depend on the interface, not the concrete client."*
- **`build_sheets_service(config)` factory** — the single construction point. It
  already returns one of **three** implementations (`GoogleSheetsService`,
  `NullSheetsService`, and — at migration time — a new backend) chosen by config.
  A new backend slots in here with no caller changes.
- **`persist_member` seam (VOL-205)** — `handlers.onboarding.persist_member` is
  the *one* write path (`ensure_header` → `find` → `update`/`append`). All
  persistence flows through it.
- **`WriteQueue` (VOL-206)** — wraps `persist_member` and, critically, takes a
  `service_factory` (`lambda: build_sheets_service(config)`) that it calls **per
  drain**, so swapping the backend behind the factory is automatically picked up.
  Its `persister` is `persist_member`, also unchanged by a backend swap.

A future migration therefore = **implement one new class behind the existing
`SheetsService` surface + flip a factory flag**. The queue, retry/backoff,
reconciliation, throttle, and onboarding call sites all stay as-is.

### Leakage to clean up (Sheets-shaped assumptions)

The current Protocol is honest about being "minimal append/lookup", but the
**richer surface that callers actually use is Sheets-shaped**. These assume a
spreadsheet and should be tidied / abstracted before (or as part of) a migration:

- **Row numbers & A1 ranges.** `find_row_by_telegram_id` returns a **1-based sheet
  row number**; `update_member_row` and `flag_needs_reconciliation` build **A1
  cell ranges** (`A{row}:{col}{row}`) via `_col_letter`. A Postgres backend has no
  row numbers — it would implement these by mapping a PK lookup to a synthetic
  "found/not-found" and doing an upsert, but the *names* (`find_row_by_telegram_id`)
  leak the sheet model.
- **`ensure_header` / header reconciliation.** The whole concept of a positional
  header row matching `schema.MEMBER_COLUMNS` (and `SheetsSchemaError` on drift)
  is Sheets-specific. A DB backend would no-op or replace it with a table/migration
  check.
- **`_record_to_row` positional mapping.** Records are mapped onto a **positional
  list in `MEMBER_COLUMNS` order**, with admin columns emitted as empty strings.
  That ordering contract is a spreadsheet artifact; a DB writes named columns.
- **Schema-aware constants that imply a sheet.** `RECONCILE_STATUS_COLUMN` reusing
  the admin `Status` cell, and the bot/admin **column split as a concurrency
  mechanism**, are Sheets race-avoidance hacks, not domain requirements.

None of these block v1 — they're noted so the migration doesn't silently carry the
spreadsheet model into the new backend.

### Recommended follow-up issue

**Yes — recommend a follow-up issue** to introduce a backend-neutral
`StorageBackend` interface that the current `SheetsService` Protocol is too
Sheets-shaped to be:

> **Proposed follow-up (e.g. VOL-2xx): "Extract a generic `MemberStore` /
> `StorageBackend` interface."**
> Define a small, backend-neutral Protocol in domain terms —
> `upsert_member(record)`, `get_member(telegram_id)`, `flag_needs_reconciliation(telegram_id)`
> — with no row numbers, A1 ranges, or positional-header assumptions. Make
> `GoogleSheetsService` and any future `SupabaseMembersService` both implement it,
> have `build_sheets_service` (or a renamed `build_member_store`) return it, and
> point `persist_member` at the neutral surface. This is a **pre-req that makes
> the §4 cutover a one-class change** rather than a leak-by-leak port. Keep it
> small; it can land independently of any actual migration.

This is **not urgent** (the existing factory + Protocol + queue already get us 90%
of the way), but doing it *before* a migration is what keeps the swap to "one new
class + a flag".

---

## 6. Acceptance-criteria checklist

- [x] **Triggers documented** with observable thresholds tied to real signals —
      quota 429s (T1), queue backlog (T2), dead-letter/dropped growth (T3),
      member count ~1.5–2k (T4), latency/sluggishness via O(rows) scan (T5),
      admin pain (T6) — each cross-referenced to VOL-206 `WriteQueue.stats()` /
      `member_persist_retry` / `member_persist_exhausted` logs and VOL-212 metrics.
- [x] **Recommended option + rationale** — Supabase (Postgres) over SeaTable /
      staying on Sheets, justified by schema fit, async-native drivers, PK upserts
      killing the quota/scan triggers, concurrency without the column-split hack,
      PDPA region/RLS, and low lock-in.
- [x] **Target schema** — `members` table mapping every `MEMBER_COLUMNS` field
      (bot + admin) to typed Postgres columns, `telegram_id` as PRIMARY KEY,
      `TAGS` / `ENTRY_SOURCES` as enums, consent/join as `timestamptz`, admin
      reconciliation columns preserved.
- [x] **Data migration shape** — provision → export → load/backfill → implement
      backend behind `SheetsService` → flip `build_sheets_service` flag → verify
      via `WriteQueue.stats()` → keep Sheets read-only fallback; with a
      data-volume/effort note (small, modest effort).
- [x] **Anti-lock-in abstraction captured** — documented the existing seams
      (`SheetsService` Protocol, `build_sheets_service`, `persist_member`,
      `WriteQueue` `service_factory`), flagged the Sheets-shaped leakage (row
      numbers / A1 ranges / `ensure_header` / positional `_record_to_row`), **and
      a follow-up issue is recommended** for a generic `StorageBackend` interface.
- [x] **No code / requirement changes** — this doc is the only artifact; v1 is
      unchanged.
