# End-to-End Launch QA — Dongfeng Experience Community bot (VOL-214)

Full end-to-end QA for launch. Every ticket scenario below is mapped to either an
**AUTOMATED** in-repo test (cited by name + result) or a **MANUAL** live-group
check (steps + expected result + PASS/FAIL box).

A fully live Telegram + Google Sheets run is NOT possible in this environment (no
live group / no credentials), so logic-level behaviour is exercised by the
automated suite and the remaining live-group behaviour (actual Telegram
delete/mute/pin, real Sheets rows) is captured as manual checks.

> **Cross-reference, do not duplicate:** `docs/launch-smoke-test.md` (VOL-213) is
> the deploy-side *"is each subsystem alive once"* check. This document is the
> *functional* QA. Where a manual item here overlaps a smoke-test item, it cites
> the smoke-test section instead of repeating the steps. Run the smoke test FIRST
> on the staging/live group, then the manual items here.
>
> See also: `docs/moderation-runbook.md` (admin ops, log review, required bot
> rights), `docs/pdpa-policy.md` (consent rules), `config/sheets-schema.md`
> (workbook columns).

---

## How to run the automated suite

pytest is **not** installed in the repo `.venv`; the suite is written with the
stdlib `unittest` framework (no new dependencies). From the repo root:

```
PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

- `PYTHONPATH=src` imports the real `dfeng_bot` package; `tests` lets the test
  modules import the shared fakes (`_fakes.py`, `_config.py`).
- The suite uses fakes for Telegram `Update`/`Context`/`Bot` and an in-memory
  `FakeSheetsService`. It performs **no network I/O** and needs no live Telegram
  token or gspread credentials.

### Recorded result (this QA pass)

```
Ran 73 tests in ~0.01s
OK
```

**73 passed, 0 failed, 0 errors.** (Date: 2026-05-31, env: repo `.venv`,
Python 3.12.13, python-telegram-bot 21.11.1.)

Module inline self-tests (separate from the suite, also green) were re-run after
the defect fix below:
`qualification, onboarding, support_redirect, antispam, flood_control,
link_restrictions, write_queue, metrics` — all `... self-tests passed`.

### Test files

| File | Tests | Covers (scenario #) |
|---|---|---|
| `tests/test_entry_source.py` | 7 | Entry sources (1) |
| `tests/test_onboarding_record.py` | 14 | Owner/Prospect/skip records + idempotency (2,3,4,5) |
| `tests/test_write_queue.py` | 5 | Sheets-outage resilience (6) |
| `tests/test_support_redirect.py` | 8 | Support redirect in/out + verbatim copy (7,8) |
| `tests/test_antispam.py` | 7 | Spam removal / legit-not-flagged (9) |
| `tests/test_link_restrictions.py` | 10 | New-user link trust transitions (10) |
| `tests/test_flood_control.py` | 6 | Cross-topic flood limiting (11) |
| `tests/test_admin_moderation.py` | 9 | Admin gating + command registration (12) |
| `tests/test_pdpa_and_pii.py` | 5 | PDPA gate, non-blocking persist, PII-safe logs |
| `tests/test_log_event_action_field.py` | 2 | Regression for DEFECT D1 (see below) |
| **Total** | **73** | |

PII hygiene: fixtures use obviously-fake values only (phone `000-FAKE-PHONE`,
plate `FAKEPLATE1`). Tests assert these never appear in any non-PII record cell,
in dead-letter records, or in captured log output.

---

## Scenario matrix (pass/fail for every ticket scenario)

### Scenario 1 — Six entry sources resolve correctly

| Entry source | Mechanism | Coverage | Result |
|---|---|---|---|
| showroom QR | named invite link → resolver | AUTOMATED `test_four_link_tracked_sources_resolve_by_link` | PASS |
| roadshow QR | named invite link → resolver | AUTOMATED (same) | PASS |
| event QR | named invite link → resolver | AUTOMATED (same) | PASS |
| Linktree | named invite link → resolver | AUTOMATED (same) | PASS |
| salesperson | **fallback default** (no link) | AUTOMATED `test_salesperson_resolves_via_fallback_when_no_link` | PASS |
| website placeholder | **fallback default** (no link, see note) | AUTOMATED `test_website_placeholder_is_not_link_tracked_falls_back` | PASS |

Also: `test_unknown_link_falls_back_to_default`, `test_schema_has_exactly_six_sources`,
`test_every_resolved_value_is_a_valid_schema_source`.

> **By-design note (not a defect):** only four sources are tracked by a named
> invite link. `salesperson` (members added directly) and `website placeholder`
> (an external URL, no group invite link) are **not** link-resolvable, so a join
> with no/unknown link resolves to the documented default
> `DEFAULT_ENTRY_SOURCE = "salesperson"` (see `services/entry_source.py` +
> `docs/entry-links.md`). The automated tests assert this honestly. **Manual
> follow-up (M1)** verifies the live link strings are wired so the four QR/Linktree
> sources actually resolve in production.

**M1 (MANUAL)** — Live entry-source attribution. In staging, create one named
invite link per QR source via the Bot API (`docs/entry-links.md`), set the
`DFENG_INVITE_LINK_*` env vars, join through each link with a test account, and
confirm the Sheets row's *Entry source* column shows the matching source.
Expected: showroom/roadshow/event/Linktree map to their source; a direct add maps
to `salesperson`. PASS ☐ FAIL ☐

---

### Scenario 2 — BOX owner, declines phone/plate

- **AUTOMATED** `test_record_has_box_tag_and_empty_optional_fields`: record has
  `Tag="BOX Owner"`, empty `Optional phone`, empty `Optional plate`, and **empty
  `Consent timestamp`** (consent ts dropped when no optional data is provided, per
  `docs/pdpa-policy.md §4`). Required fields still persist. **Result: PASS.**
- Also `test_box_owner_tag`. **Manual confirmation:** smoke test §3 + §4.

### Scenario 3 — 007 owner, provides phone/plate after consent

- **AUTOMATED** `test_consent_timestamp_set_when_optional_data_provided`:
  `Tag="007 Owner"`, phone+plate stored (fake values), `Consent timestamp` set.
  Also `test_phone_only_still_sets_consent`, `test_007_owner_tag`. **Result: PASS.**
- **AUTOMATED** `test_consent_shown_before_optional_capture` (PDPA notice shown
  before any field is requested) + `test_finish_persists_and_clears_pii_from_user_data`
  (full async capture→persist path; PII cleared from memory after write).
  **Result: PASS.**
- **Manual confirmation:** smoke test §3 + §4 (real row in `Members` tab).

### Scenario 4 — VIGO owner

- **AUTOMATED** `test_vigo_owner_tag`, `test_tags_match_schema`. **Result: PASS.**

### Scenario 5 — User skips qualification → default Prospect

- **AUTOMATED** `test_skip_qualification_defaults_to_prospect`,
  `test_resolve_tag_preserves_valid_owner_tags`, `test_unknown_model_returns_none`.
  `resolve_tag(None)`/`resolve_tag("garbage")` → `"Prospect"`. **Result: PASS.**

### Scenario 6 — Sheets write fails temporarily → onboarding still completes

- **AUTOMATED** `test_transient_failure_then_success_persists` (fail twice, succeed
  on 3rd via backoff retries), `test_persistent_failure_dead_letters_without_pii`
  (exhaust → dead-letter, **no PII in the dead-letter record**),
  `test_onboarding_completes_even_if_queue_full` (bounded queue overflow →
  dead-letter, `enqueue` returns immediately), `test_backoff_is_monotonic_and_capped`,
  `test_stats_shape_is_stable`. **Result: PASS.**
- **AUTOMATED** `test_finish_is_nonblocking_when_sheets_raises`: the async
  onboarding finish path swallows a raising Sheets service and still confirms the
  member (non-blocking). **Result: PASS.**
- **Manual confirmation:** smoke test §4 + `/sheets_status` (queue drained,
  dead-letter 0). Live Sheets-down behaviour is **M2** below.

**M2 (MANUAL)** — Live Sheets outage. In staging, point the bot at a workbook the
service account cannot reach (or revoke access briefly), onboard a test member,
and confirm: onboarding completes for the user; logs show `member_persist_retry`
then `member_persist_exhausted ... needs_reconciliation`; `/sheets_status` shows a
non-zero dead-letter; `/reconcile` lists the Telegram ID (no phone/plate). Restore
access and backfill. PASS ☐ FAIL ☐

---

### Scenario 7 — Support keyword OUTSIDE Support → redirect

- **AUTOMATED** `test_redirect_fires_outside_support_topic` (nudges in a non-support
  topic; the exact `SUPPORT_REDIRECT_MESSAGE` is sent in-thread),
  `test_detects_each_required_keyword`, `test_verbatim_copy_matches_ticket`
  (the response string is byte-for-byte the ticket copy). **Result: PASS.**
- **Manual confirmation:** smoke test §5.

### Scenario 8 — Support keyword INSIDE Support → does NOT loop

- **AUTOMATED** `test_no_loop_inside_support_topic` (message already in the Support
  topic ⇒ no nudge ⇒ no loop), plus `test_cooldown_suppresses_repeat_nudge`
  (per-user/thread cooldown) and `test_no_redirect_for_non_support_chatter`.
  **Result: PASS.**

---

### Scenario 9 — Spam removed; legit Dongfeng message NOT flagged

- **AUTOMATED** `test_crypto_promos_flagged`, `test_external_ads_flagged`,
  `test_suspicious_links_flagged` (crypto/ad/link verdicts),
  `test_legit_dongfeng_chatter_not_flagged` (no false positives on normal chatter),
  `test_allowlist_exempts_community_domain`, `test_repetition_trips_after_threshold`,
  `test_repetition_does_not_trip_outside_window`. **Result: PASS.**
- **Manual confirmation:** smoke test §6 (real delete by a non-admin account).

### Scenario 10 — New-user link blocked before trust, allowed after

- **AUTOMATED** `test_detects_links_and_mentions` / `test_clean_text_has_no_link`
  (`message_has_link`), trust transitions
  (`test_fresh_member_not_trusted_then_trusted_by_age`,
  `test_clean_messages_earn_trust`, `test_qualified_member_trusted`,
  `test_admin_approved_trusted`, `test_unknown_member_trusted`), and the store-level
  blocked→allowed transition (`test_join_then_clean_messages_cross_threshold`,
  `test_admin_trust_immediately_allows_links`). **Result: PASS.**
- **Manual confirmation:** smoke test §7 (block + `/trust` lifts it).

### Scenario 11 — Flooding across multiple topics → rate limiting

- **AUTOMATED** `test_burst_trips_above_max`,
  `test_counts_across_topics_to_one_limit` (thread id is never an input — all
  topics share one per-user counter), `test_slow_sender_never_trips`,
  `test_window_expiry_resets`, `test_users_are_independent`,
  `test_outer_map_bounded`. **Result: PASS.**
- **Manual confirmation:** smoke test §8 (real auto-expiring mute).

---

### Scenario 12 — Admin can delete/mute/pin/approve/remove + review logs

Logic-level gating + registration is automated; the actual Telegram side-effects
(real pin/delete/mute/ban/approve, native long-press equivalence, and log review)
are MANUAL (cite smoke test §9 and `docs/moderation-runbook.md §7`).

- **AUTOMATED** `test_moderation_commands_registered` (`/pin /del /delete /mute
  /unmute /ban /unban /approve /modhelp` all register),
  `test_core_admin_commands_registered` (`/health /stats /sheets_status /reconcile
  /trust`), `test_nonadmin_delete_denied_no_api_call` /
  `test_nonadmin_pin_denied` (non-admin ⇒ "Not authorised." + **no Bot API call**),
  `test_admin_delete_calls_api` / `test_admin_ban_calls_api` /
  `test_admin_mute_is_time_bounded` (admin ⇒ the right Bot API call fires; mute is
  time-bounded/reversible), `test_health_denies_nonadmin` /
  `test_health_allows_admin`. **Result: PASS.**

**M3 (MANUAL)** — Live admin moderation. Per smoke test §9 + `moderation-runbook
§1/§2`: as an admin, `/pin`, `/del`, `/mute 1`, `/ban`+`/unban`, `/approve` a
pending join request, and confirm each succeeds and logs
`action=cmd_<name> ... outcome=...` with the admin id. As a non-admin, confirm
"Not authorised." + `outcome=denied`. Review the automated-moderation logs per
`moderation-runbook §7` (`journalctl`/`docker logs`, grep filters). PASS ☐ FAIL ☐

---

## Defects found

### D1 — `log_event(action=...)` keyword collision (was BLOCKING) — FIXED (trivial)

**Found by:** building the onboarding finish-path test; the success log emitted
`member_persist_failed` even though the FakeSheetsService captured the row.

**Root cause:** `log_event(action, update, *, level, **fields)` took `action` as a
normal positional-or-keyword parameter. Several handlers log an `action=<verb>`
STRUCTURED FIELD (e.g. `action="deleted"`, `"mute"`, `"notify"`, `"appended"`).
Passing `action=` as a field collided with the parameter →
`TypeError: log_event() got multiple values for argument 'action'`.

**Call sites affected** (via AST scan): `handlers/onboarding.py` (member_persisted),
`handlers/antispam.py` (×4), `handlers/flood_control.py` (×5),
`handlers/link_restrictions.py` (×3).

**Impact (pre-fix):**
- `onboarding._finish_and_persist` (direct write path): the `member_persisted`
  success log raised; the surrounding `try/except` masked it as
  `member_persist_failed`. Onboarding still completed (non-blocking), but the
  success audit log was wrong/missing.
- `antispam.check` **spam-removed** path: the offending `log_event(...,
  action="deleted", outcome="removed")` is **NOT** wrapped in `try/except`. It
  raised AFTER the delete, so `metrics.bump("spam_action")` and the consuming
  `raise ApplicationHandlerStop` were **skipped**, and the global error handler
  fired. The message was deleted, but the audit log + spam metric were lost and
  downstream handlers were not stopped for that update. Flood-control and
  link-restriction outcome logs were similarly affected (mostly on already-
  side-effected paths).

**Fix applied (trivial, obvious correctness):** made the first parameter of
`log_event` **positional-only** (`def log_event(action, update=None, /, *, level,
**fields)`), so an `action=` field now lands in `**fields` and *wins* in the
logged output (the event name remains the log message). No call sites changed; no
behaviour changed beyond the logs/metrics now emitting correctly. Regression
locked by `tests/test_log_event_action_field.py` and the success-log assertion in
`test_finish_persists_and_clears_pii_from_user_data`.

**Severity:** was **blocking** for the moderation/observability acceptance
(automated audit logging + spam metric); now **resolved**, all 73 tests green and
all module self-tests green.

### No other defects

No PII/secret leakage was found: `build_member_record`, the write-queue
dead-letter records, and the onboarding finish-path logs were all asserted
PII-free with fake fixtures. No secret values appear in any test artifact.

---

## Launch readiness decision

### Decision: **GO-WITH-RISKS**

The automated logic-level QA is fully green (73/73), the one blocking defect found
(D1) was a trivial, obvious correctness fix and is now fixed + regression-tested,
and every ticket scenario is covered by either an automated test or a defined
manual live-group check. Remaining risk is the **live-group / live-Sheets manual
verification (M1–M3)** that cannot run in this environment, plus the documented v1
operational trade-offs below.

### Known risks & conditions to clear

| # | Risk | Severity | Condition to clear |
|---|---|---|---|
| R1 | Manual live items **M1–M3** + `docs/launch-smoke-test.md` not yet executed on a real/staging group (real Telegram delete/mute/pin/approve; real Sheets rows; live entry-link attribution). | Medium | Run the smoke test then M1–M3 on the staging clone of the live supergroup; record PASS for each before opening to the public. |
| R2 | Automated-moderation feature flags ship **dark** (`antispam`, `flood_control`, `link_restrictions`, `sheets` default OFF; only the prod env template enables them). The automated tests force-enable per case, so a prod env that forgets a flag silently disables that subsystem. | Medium | Confirm the production `.env` sets `DFENG_FEATURE_ANTISPAM/_FLOOD_CONTROL/_LINK_RESTRICTIONS/_SHEETS=1`; verify via the startup `safe_summary()` (smoke-test "Before you start"). |
| R3 | In-memory, single-instance state: spam repetition memory, flood tracker, trust store, support-redirect cooldown, and the write-queue pending/dead-letter list are **per-process and NOT shared**. A restart loses not-yet-flushed writes; multi-instance would double-count/under-enforce. | Low (accepted v1) | Keep single-instance; rare operator-initiated restarts only. For multi-instance, add a shared store (Redis) — documented as future work in the handler docstrings + `write_queue.py`. |
| R4 | Write-queue durability: pending + dead-letter are in-memory; a crash mid-flush loses those writes (records are idempotent + re-derivable; IDs are in the logs). | Low (accepted v1) | After any restart, check `/sheets_status` / `/reconcile` and backfill any dead-lettered IDs (M2). |
| R5 | Entry-source attribution depends on operators wiring named invite links; `salesperson` + `website placeholder` are fallback-only by design. | Low | M1 confirms the four link-tracked sources resolve; accept the documented fallback for the other two. |
| R6 | Bot admin-rights dependency: delete/mute/pin/approve fail gracefully (logged + friendly reply) if a right is missing — but the feature is then a no-op. | Low | Grant the full right set per `docs/telegram-setup.md §7`; smoke test §9 + the "Permission sanity" section catch a missing right. |

### Sign-off

- Automated suite: **73 passed / 0 failed** — reproduce with the command above.
- Blocking defects: **none open** (D1 fixed).
- PII/secrets in artifacts: **none** (fake fixtures; asserted).
- Recommendation: proceed to staging, clear R1/R2 (run smoke test + M1–M3 +
  confirm prod flags), then **GO** to public launch.

- QA date: 2026-05-31 · Env: repo `.venv`, Python 3.12.13, python-telegram-bot 21.11.1
- Remaining owners: M1–M3 + smoke test → L1/L3 on the staging group; flag/permission
  config (R2/R6) → L3 (`docs/moderation-runbook.md §4`).
