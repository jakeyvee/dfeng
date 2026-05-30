"""Single source of truth for PDPA consent and member data-handling policy.

VOL-199 locks the consent wording and data-handling rules for v1. Downstream
code tickets (VOL-205 PDPA-gated capture/persistence, VOL-198 Sheets) MUST
import the constants below instead of re-typing the consent text, so the
notice shown to members stays byte-for-byte identical to the locked policy in
``docs/pdpa-policy.md``.

Pure Python, stdlib only. No side effects on import.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Consent notice — FINAL for v1. Do NOT alter the wording.
# This string is the canonical copy. ``docs/pdpa-policy.md`` quotes the same
# text; both must remain byte-for-byte identical.
# ---------------------------------------------------------------------------
PDPA_CONSENT_NOTICE = (
    "By providing your information, you consent to Dongfeng Singapore storing "
    "and using the information solely for community management, support and "
    "engagement purposes in accordance with applicable PDPA requirements."
)

# ---------------------------------------------------------------------------
# Data inventory
# ---------------------------------------------------------------------------
# Mandatory fields: collected for community operation; necessary for the
# service. No separate consent prompt is required to collect these (they are
# inherent to joining and operating the invite-only community).
MANDATORY_FIELDS: tuple[str, ...] = (
    "telegram_id",
    "telegram_username",
    "owner_or_prospect_status",
    "model_tag",
)

# Optional fields: collected ONLY after the consent notice is shown and the
# member chooses to provide them. Declining must NOT block onboarding/entry.
OPTIONAL_FIELDS: tuple[str, ...] = (
    "phone_number",
    "vehicle_plate",
)

# Consent timestamp is recorded ONLY when at least one optional field is
# actually provided after the notice has been shown. If the member declines
# all optional fields, no consent timestamp is stored.
CONSENT_TIMESTAMP_FIELD: str = "consent_timestamp"

# Admin-managed column marking a member's deletion/removal request. Set by an
# admin when a member asks to be removed; the row is then cleared/redacted.
DELETION_REQUESTED_FIELD: str = "deletion_requested"

# Policy version this module encodes.
POLICY_VERSION: str = "v1"

__all__ = [
    "PDPA_CONSENT_NOTICE",
    "MANDATORY_FIELDS",
    "OPTIONAL_FIELDS",
    "CONSENT_TIMESTAMP_FIELD",
    "DELETION_REQUESTED_FIELD",
    "POLICY_VERSION",
]
