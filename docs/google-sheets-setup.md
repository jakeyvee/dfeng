# Google Sheets member workbook + service account — operator runbook

**Ticket:** VOL-198 · **Project:** Dongfeng Experience Community

This runbook provisions the Google Sheets workbook that stores community members
and the Google service account the bot uses to write to it. Follow it top to
bottom; the acceptance checklist at the end confirms "done".

> You need a Google account with permission to create a Google Cloud project and
> a Google Sheet owned by the Dongfeng Experience / designated **Level 3
> Management** account. Do this work signed in as (or delegated by) that account.

---

## 1. Create the workbook and Members tab

1. Sign in to Google Drive as the **Dongfeng Experience / Level 3 Management**
   account. The workbook must be **owned by this account** (not a personal one).
2. Create a new Google Sheet. Name it e.g. `Dongfeng Experience — Members`.
3. Rename the first tab to exactly **`Members`** (matches `DFENG_SHEETS_TAB_NAME`).
4. In row 1, enter the header **exactly** in this order (one column each):

   ```
   Telegram ID | Telegram username | Tag | Optional phone | Optional plate | Consent timestamp | Entry source | Joined timestamp | Notes | Status | Deletion requested | Last reconciled
   ```

   This order is the canonical schema (`config/sheets-schema.md` /
   `src/dfeng_bot/services/schema.py`) and is **load-bearing** — the bot maps
   rows positionally. Do not reorder or rename columns.

5. (Optional) Add data validation:
   - **Tag** (col 3): `BOX Owner`, `007 Owner`, `VIGO Owner`, `Prospect`.
   - **Entry source** (col 7): `salesperson`, `showroom QR`, `roadshow QR`,
     `Linktree`, `event QR`, `website placeholder`.

6. Copy the **workbook id** from the URL — the segment between `/d/` and `/edit`:
   `https://docs.google.com/spreadsheets/d/`**`<WORKBOOK_ID>`**`/edit`.
   You will put this in `DFENG_SHEETS_WORKBOOK_ID`.

### Column ownership (why it matters here)

- **Bot-owned, columns 1–8:** written only by the service account / bot. Admins
  treat them as read-only.
- **Admin-owned, columns 9–12** (`Notes`, `Status`, `Deletion requested`,
  `Last reconciled`): edited by humans only. The bot never writes them.

The bot and admins write disjoint column ranges, so a member write and an admin
edit never collide on the same cell (concurrent-write race avoidance).

---

## 2. Create a GCP project and enable APIs

1. Go to <https://console.cloud.google.com/> as the same (or an authorised)
   account.
2. Create a new project, e.g. `dfeng-community-bot`.
3. Enable the required APIs (APIs & Services → Library):
   - **Google Sheets API** (required).
   - **Google Drive API** (required — gspread opens the workbook by key via
     Drive).

---

## 3. Create a service account + JSON key

1. APIs & Services → **Credentials** → **Create credentials** → **Service
   account**.
2. Name it e.g. `dfeng-sheets-writer`. No project-level IAM roles are needed —
   access is granted by **sharing the specific workbook** (step 4), which scopes
   the account to ONLY this sheet.
3. Open the new service account → **Keys** → **Add key** → **Create new key** →
   **JSON**. A JSON key file downloads. Treat it as a secret.
4. Note the service account **email** (looks like
   `dfeng-sheets-writer@<project>.iam.gserviceaccount.com`). You need it in
   step 4.

---

## 4. Share the workbook (named accounts only)

Back in the **Members** Google Sheet → **Share**:

1. **Service account — Editor:** add the service account email from step 3 with
   the **Editor** role. This is what lets the bot write rows. Because access is
   granted per-sheet, the account can touch **only this workbook**.
2. **Named Level 1+ admins — read/edit:** add each admin by their **named Google
   account** with the appropriate role (Editor for those who manage member
   data).
3. **Do NOT** use "Anyone with the link". Sharing must be **named accounts
   only**. Leave General access at **Restricted**.
4. Ownership stays with the **Dongfeng Experience / Level 3 Management** account.

---

## 5. Install the credentials + workbook id in the bot environment

The bot reads these via `src/dfeng_bot/config.py` (`SheetsConfig`). Set them in
`.env` for local dev, or via your host's secret manager in production.

| Env var                          | Value |
|----------------------------------|-------|
| `DFENG_FEATURE_SHEETS`           | `1` to enable the real Sheets client |
| `DFENG_SHEETS_WORKBOOK_ID`       | the workbook id from step 1.6 |
| `DFENG_SHEETS_TAB_NAME`          | `Members` |
| `GOOGLE_APPLICATION_CREDENTIALS` | path to the JSON key file (e.g. `./service-account.json`) |

- The JSON key is **gitignored** (`*.json`, `service-account*.json`) and must
  **NEVER** be committed. In production, mount it at runtime (e.g. a secret
  volume / systemd `EnvironmentFile` + file with `0600` perms) or inject the raw
  JSON as the value of `GOOGLE_APPLICATION_CREDENTIALS` (the client accepts a
  path OR raw JSON).
- Confirm `*.json` is ignored: `git check-ignore service-account.json`.

---

## 6. Smoke test (once the bot ticket lands)

The persistence ticket (VOL-205) calls `build_sheets_service(config)`:

- With `DFENG_FEATURE_SHEETS=0` or missing config → a no-op `NullSheetsService`
  (the bot still runs).
- With the flag on and config present → `GoogleSheetsService`, which on first use
  authenticates and calls `ensure_header()` to verify row 1 matches the canonical
  schema (it raises if the header drifted).

---

## Retention

Member rows are retained **until the member leaves the community or requests
deletion**. On leave/deletion, an admin records it in the admin-owned `Status` /
`Deletion requested` columns and the row is removed/anonymised per the PDPA
process (wording approval tracked in VOL-199).

---

## Acceptance criteria checklist

- [ ] Workbook created and **owned by the Dongfeng Experience / Level 3
      Management** account.
- [ ] Tab named exactly `Members`.
- [ ] Row 1 header matches the canonical 12-column order exactly.
- [ ] (Optional) Data validation set for `Tag` and `Entry source`.
- [ ] GCP project created; **Google Sheets API** and **Google Drive API**
      enabled.
- [ ] Service account created; **JSON key** generated and stored as a secret
      (never committed).
- [ ] Workbook **shared with the service account email as Editor**.
- [ ] Named Level 1+ admins granted access by **named account** (no "anyone with
      link"); General access = Restricted.
- [ ] `DFENG_SHEETS_WORKBOOK_ID`, `DFENG_SHEETS_TAB_NAME`,
      `GOOGLE_APPLICATION_CREDENTIALS`, `DFENG_FEATURE_SHEETS` set in the bot
      environment.
- [ ] `git check-ignore` confirms the JSON key is gitignored.
- [ ] Bot-owned (1–8) vs admin-owned (9–12) split understood and documented to
      admins.
- [ ] Retention policy (until leave / deletion request) communicated.
