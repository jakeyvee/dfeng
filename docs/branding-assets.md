# Branding assets & launch risks — Dongfeng Experience Community

**Linear ticket:** VOL-200

Specs for the assets the community needs at launch, what's still missing, and the
open ambiguities that must be design-locked before go-live.

---

## Group avatar spec

The Telegram supergroup needs a profile photo (avatar). Telegram crops group
photos to a **circle** in most views, so keep important detail centred.

| Property | Requirement |
|----------|-------------|
| Shape | **Square** (Telegram crops to a circle for display) |
| Recommended size | **512 × 512 px** |
| Minimum | 512 × 512 px (Telegram upscales smaller images and they look soft) |
| Format | **PNG or JPG** (PNG preferred for crisp logos/flat colour) |
| Max file size | Keep under ~5 MB (well within Telegram's limit) |
| Colour | Primary brand frame: **Dark Blue, Red, White**; orange/🧡 as community accent |
| Safe area | Centre the logo/mark; leave breathing room so the circular crop doesn't clip it |

> **Status: NOT supplied.** The actual avatar asset is to be provided by
> stakeholders (see launch risks and checklist below). This document specifies
> the format/size only.

---

## Launch risks

### Risk 1 — Group avatar asset not supplied (asset ownership)

- **What:** The community needs a finalised square avatar (512×512, PNG/JPG) for
  launch. It has not been supplied, and no owner is formally assigned.
- **Impact:** The supergroup launches without branding, or with a placeholder —
  weakens the "official, invite-only community" first impression.
- **Owner:** Stakeholders / Dongfeng SG brand team (to confirm a named owner).
- **Mitigation:** Assign an asset owner now; request the avatar to the spec above
  ahead of the VOL-201 apply step. If not ready by launch, use an interim mark in
  the primary palette and swap in the final asset post-launch.

### Risk 2 — Brand-colour phrasing ambiguous (design-lock)

- **What:** The PRD flagged **Q8** — the brand-colour phrasing — as ambiguous.
  The primary palette is **Dark Blue, Red, White**, with **orange/🧡** as the
  community accent, but the exact relationship (where orange may/may not be used
  in designed assets vs. copy-only) isn't locked.
- **Impact:** Inconsistent use of orange across avatar, banners, and event
  graphics; possible rework after launch.
- **Owner:** Stakeholders / brand/design lead.
- **Mitigation:** Until design-lock, treat **orange/🧡 as a community accent and
  identifier only** (copy, welcomes, signature touches). Keep Dark Blue / Red /
  White as the primary frame for designed assets. Resolve Q8 with stakeholders
  before finalising any visual asset.

---

## Stakeholder supply checklist

Still needed from stakeholders before / at launch:

- [ ] **Group avatar** — square, 512×512 px, PNG/JPG, to the spec above
- [ ] **Named asset owner** for the avatar (resolves Risk 1)
- [ ] **Q8 brand-colour design-lock** — confirm primary-palette vs. orange-accent
      usage rules (resolves Risk 2)
- [ ] (Optional) Event/banner template in the locked palette for Announcements
- [ ] Sign-off that the avatar respects the circular crop (logo centred, not
      clipped)

---

## Acceptance-criteria check (VOL-200)

- Group avatar spec documented (square, 512×512 px, PNG/JPG) ✓
- Asset ownership recorded as a launch risk (avatar not supplied) ✓
- Q8 brand-colour ambiguity recorded as a design-lock launch risk ✓
- Stakeholder supply checklist included ✓
- Final pinned copy for all six topics ✓ → `content/pinned-messages.md`
- Tone guide short/usable ✓ → `docs/tone-guide.md`
