# Member workbook schema — canonical definition

This is the **human-readable** mirror of the machine source of truth in
`src/dfeng_bot/services/schema.py`. The workbook header row (tab **Members**)
**must** match the column order below exactly. If you change a column, update
**both** this file and `schema.py`.

One row = one community member, keyed by **Telegram ID** (column 1, stable).

## Column order (STABLE — do not reorder)

| # | Column              | Owner | Required | Type / notes |
|---|---------------------|-------|----------|--------------|
| 1 | Telegram ID         | bot   | yes      | Integer, unique key. Stable identity. |
| 2 | Telegram username   | bot   | no       | Public `@handle`; may be empty if the user has none. |
| 3 | Tag                 | bot   | yes      | Enum — see **Tags** below. |
| 4 | Optional phone      | bot   | no       | **PII.** May be empty. Never logged. |
| 5 | Optional plate      | bot   | no       | **PII.** Vehicle plate. May be empty. Never logged. |
| 6 | Consent timestamp   | bot   | yes      | ISO-8601 UTC; when PDPA consent was captured. |
| 7 | Entry source        | bot   | yes      | Enum — see **Entry sources** below. |
| 8 | Joined timestamp    | bot   | yes      | ISO-8601 UTC; when the member joined the community. |
| 9 | Notes               | admin | no       | Free-text admin notes. |
| 10| Status              | admin | no       | Admin-managed lifecycle label (e.g. `active`, `left`). |
| 11| Deletion requested  | admin | no       | Admin marks deletion / retention requests here. |
| 12| Last reconciled     | admin | no       | Timestamp of last admin reconciliation pass. |

## Tags (column 3 — allowed values)

- `BOX Owner`
- `007 Owner`
- `VIGO Owner`
- `Prospect`

## Entry sources (column 7 — allowed values)

- `salesperson`
- `showroom QR`
- `roadshow QR`
- `Linktree`
- `event QR`
- `website placeholder`

## Bot-owned vs admin-owned split (concurrent-write race avoidance)

- **Bot-owned: columns 1–8** (`BOT_COLUMNS`). Written **only** by the bot via
  the Google service account. Admins should treat these as read-only.
- **Admin-owned: columns 9–12** (`ADMIN_COLUMNS`). Edited **only** by humans
  (named Level 1+ admins). The bot never writes to them.

Because the two owners write disjoint column ranges, a bot append/update of a
member row and a concurrent admin edit never target the same cell. The bot's
`update_member_row()` writes only the bot-owned cells of an existing row and
leaves admin columns untouched, so an in-flight admin note is never clobbered.

## Retention

Member rows are retained **until the member leaves the community or requests
deletion**. When that happens, an admin records it via the admin-owned
`Deletion requested` / `Status` columns and the row is removed/anonymised per
the PDPA process (wording approval tracked separately in VOL-199).

## Source of truth

`src/dfeng_bot/services/schema.py` exports:

- `MEMBER_COLUMNS` — full ordered header (bot columns then admin columns)
- `BOT_COLUMNS` / `ADMIN_COLUMNS` — the ownership split
- `TAGS` — allowed `Tag` values
- `ENTRY_SOURCES` — allowed `Entry source` values
- `KEY_COLUMN`, `PII_COLUMNS` — the lookup key and the columns kept out of logs
