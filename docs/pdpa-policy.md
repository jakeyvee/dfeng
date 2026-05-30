# PDPA Consent & Member Data Handling Policy — v1 (LOCKED)

**Project:** Dongfeng Experience Community (Dongfeng Singapore invite-only Telegram community)
**Ticket:** VOL-199
**Status:** v1 LOCKED. The consent wording in this document is **FINAL for v1**.
**Authoritative code constant:** [`src/dfeng_bot/policy.py`](../src/dfeng_bot/policy.py) (`PDPA_CONSENT_NOTICE`).

> This document and `src/dfeng_bot/policy.py` are the single source of truth for
> PDPA consent and member data handling. Downstream code tickets — **VOL-205**
> (PDPA-gated capture/persistence) and **VOL-198** (Sheets) — MUST follow these
> rules and MUST import the consent text from `policy.py` rather than re-typing it.
> The notice text must be **byte-for-byte identical** wherever it appears.

---

## 1. Purpose of collection

Dongfeng Singapore operates an invite-only Telegram community for owners and
prospects. Member data is collected **solely** to run that community:
community management, member support, and engagement — and for nothing else.
This purpose is reflected verbatim in the consent notice below.

---

## 2. Data inventory (mandatory vs optional)

### Mandatory — necessary for the service

Collected for community operation; inherent to joining and running the
invite-only community. No separate consent prompt is required for these.

| Field | Code key (`MANDATORY_FIELDS`) | Why it is necessary |
|-------|-------------------------------|---------------------|
| Telegram ID | `telegram_id` | Stable identifier for the member; used to find/manage their row. |
| Telegram username | `telegram_username` | Public handle; member identification and admin contact. |
| Owner / prospect status | `owner_or_prospect_status` | Core community segmentation. |
| Model tag | `model_tag` | Core community segmentation / engagement. |

### Optional — consent-gated

Collected **only after** the consent notice is shown and the member chooses to
provide them.

| Field | Code key (`OPTIONAL_FIELDS`) |
|-------|------------------------------|
| Phone number | `phone_number` |
| Vehicle plate | `vehicle_plate` |

**Rule — onboarding is never blocked:** the onboarding/qualification flow MUST
continue if the member declines to provide phone and/or vehicle plate. Declining
optional data must never block entry or onboarding.

---

## 3. Consent notice (FINAL for v1 — copy verbatim)

The bot MUST display the following notice **before** collecting any optional
phone number or vehicle plate. Code MUST import this from
`src/dfeng_bot/policy.py` (`PDPA_CONSENT_NOTICE`) — do not re-type it.

> By providing your information, you consent to Dongfeng Singapore storing and using the information solely for community management, support and engagement purposes in accordance with applicable PDPA requirements.

This wording is **locked for v1**. Any change requires a new policy version and
a corresponding update to `PDPA_CONSENT_NOTICE`.

---

## 4. Consent-timestamp rule

A consent timestamp (`consent_timestamp` / `CONSENT_TIMESTAMP_FIELD`) is stored
**only when** optional personal data (phone and/or vehicle plate) is **actually
provided** by the member **after** the notice has been shown.

- If the member declines all optional fields, **no** consent timestamp is stored.
- The timestamp records when the member affirmatively provided optional data
  following the displayed notice — it is the evidence that consent was obtained.

---

## 5. Retention rule

Member data is retained **until** either:

1. the member **leaves** the community, or
2. the member **requests removal** (deletion request).

When either condition is met, the member's data is removed/redacted per the
admin deletion path in §6.

---

## 6. Deletion / removal path (admin)

Deletion requests are handled by an admin directly in the member workbook. There
is no automated self-service deletion in v1.

### The "Deletion requested" admin column

The workbook has an admin-managed column, `deletion_requested`
(`DELETION_REQUESTED_FIELD`). An admin sets it (e.g. to the request date) to mark
that a member asked to be removed, so the request is tracked even before the row
is cleared. It is admin-facing only and is never shown to members.

### How to handle a deletion request (admin-facing, step by step)

1. **Locate the member row.** Open the member workbook and find the row whose
   `telegram_id` matches the requester's Telegram ID. (Telegram ID is the stable
   key — match on it, not on username, which can change.)
2. **Mark the request.** Enter the request date in the `deletion_requested`
   column for that row, so the action is auditable.
3. **Clear / redact the row.** Remove the member's personal data:
   - Delete the entire row, **or**
   - Clear/redact the personal fields — `telegram_username`, `phone_number`,
     `vehicle_plate`, and the mandatory identifiers — and clear
     `consent_timestamp`.
   Either approach must leave no recoverable personal data for that member.
4. **Confirm back to the user.** Reply to the member confirming their data has
   been removed from the community workbook and that they have been (or will be)
   removed from the community as requested.

A member **leaving** the community is treated the same way: the admin clears/
redacts that member's row per steps 1, 3 (no user confirmation is required for a
voluntary leave).

---

## 7. Credential / access security rule

- The Google **service-account credentials** (JSON) and **workbook access** must
  **not** be public and must **not** be committed to source control. Credential
  files (`*.json`) and `.env` are gitignored; only placeholder examples are
  committed. Real secrets are injected via environment at runtime.
- Workbook sharing is restricted to the service account and authorized admins
  only — never "anyone with the link" or public.
- Logs must never contain member PII (phone, plate) or secrets; log IDs, public
  usernames, actions, and outcomes only.

---

## 8. Open compliance questions / launch risks

The following are **unresolved** and should be settled before launch:

1. **Final stakeholder sign-off owner.** Who is the named owner that formally
   approves this v1 policy (Dongfeng Singapore side)? Sign-off owner is TBD.
2. **Privacy-policy link / PDPA officer contact.** Should the consent notice be
   accompanied by a link to a full privacy policy and/or a PDPA / Data Protection
   Officer contact? PDPA practice generally expects an identifiable contact. Not
   included in the v1 notice — decision pending. (Adding either would NOT change
   the locked notice wording; it would be presented alongside it.)
3. **Data-breach handling.** No breach-notification / incident-response process
   is defined yet (who is notified, within what timeframe, member notification).
   Needs an owner and a documented procedure before launch.
4. **Retention beyond leave/removal.** Confirm no backups or exports retain
   member data after a row is cleared (e.g. Google Sheets version history, manual
   exports). The deletion path must account for these.
5. **Withdrawal of consent for optional data only.** v1 treats removal as full
   deletion. Whether a member can withdraw consent for optional data (phone/plate)
   while remaining in the community is not yet specified.

---

## 9. Acceptance-criteria checklist (VOL-199)

- [x] Consent wording final (locked for v1; in `policy.py` and quoted verbatim above)
- [x] Data-handling rules documented (inventory, consent-timestamp, retention, security)
- [x] Admin deletion path defined (locate by Telegram ID, `deletion_requested` column, clear/redact, confirm to user)
- [x] Unresolved compliance questions identified (§8)
