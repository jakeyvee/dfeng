# Apply branding & pinned messages runbook — VOL-201

Operator runbook to **apply** the approved branding and pinned copy into the
already-provisioned **Dongfeng Experience Community** supergroup, then record the
resulting pinned message IDs for the bot/admins.

> **Who runs this:** an admin who can post in every topic and pin messages — i.e.
> any L1/L2/L3 admin per `docs/telegram-setup.md` §9 (all tiers hold *Pin
> Messages* + *Manage Topics*). The group **Owner (L3)** or the **bot** is needed
> for the avatar step (*Change Group Info*). Steps reference the **mobile app**
> UI; the Desktop/macOS app has the same options under slightly different menus
> (noted where they differ).
>
> **Prerequisites (do NOT redo here):**
> - VOL-196 is complete: the supergroup exists, forum mode is ON, the six topics
>   exist with exact names/order, and **Announcements & Events is a CLOSED
>   topic**. `config/group-setup.yaml` is filled in (group_id + six thread_ids).
> - VOL-200 is complete: `content/pinned-messages.md` holds the final, approved
>   pinned copy (six fenced blocks) and `docs/branding-assets.md` holds the
>   avatar spec.
>
> **Outcome:** group avatar set (or interim noted), each of the six topics has
> the approved pinned message posted and pinned (Announcements pinned **as
> admin** without reopening posting), topic descriptions set where supported, and
> `config/pinned-message-ids.yaml` filled with the resulting message IDs.
>
> Work top-to-bottom. The **acceptance checklist** at the end mirrors every
> requirement — tick it off as you go.

---

## 0. Before you start

- Open `config/pinned-message-ids.example.yaml` alongside this runbook — you will
  copy it to `config/pinned-message-ids.yaml` (gitignored) and fill it in as you
  complete each step.
- Open `content/pinned-messages.md` — **this is the only source of the pinned
  copy.** Do **not** re-type or re-draft the text from memory; copy-paste it
  **verbatim** from the matching fenced block. Each step below names the exact
  source heading.
- Have the **avatar asset** ready if supplied (see step 1 / the dependency note).
- Confirm you can see the five created topics plus the built-in **General**:
  1. `Announcements & Events`  2. `BOX Owners Lounge`  3. `007 Owners Club`
  4. `VIGO Owners Circle`  5. `Support & Assistance`  + the built-in **General**
  topic (used as **General Community Chat**, `thread_id 1`).

> **Golden rule on copy fidelity:** every pinned block must match
> `content/pinned-messages.md` **character-for-character**, including the 🧡
> emoji, 👍, line breaks, and the blank line between paragraphs. Telegram sends
> the message as typed — paste, then eyeball it against the source block before
> pinning.

---

## 1. Apply the group avatar

**Dependency — asset is stakeholder-supplied.** Per `docs/branding-assets.md`
(Risk 1), the real avatar is **NOT** in this repo; it must be provided by
stakeholders / the Dongfeng SG brand team to the spec there: **square,
512 × 512 px, PNG/JPG**, primary palette Dark Blue / Red / White with orange/🧡
as accent, logo centred for the circular crop.

1. Confirm the asset matches the spec in `docs/branding-assets.md` → *Group
   avatar spec* (square 512×512, PNG/JPG, centred mark). If it does not, request
   a corrected asset — do not upscale a smaller image (Telegram makes it soft).
2. Group → tap the title → **Edit** (pencil) → tap the **photo/camera icon** →
   **Set Photo / Choose from gallery** (Desktop: *Edit → set profile photo*).
   Select the asset. Adjust the crop so the mark sits inside the circle, then
   confirm.
3. **If the final asset is not yet supplied:** either (a) leave the avatar unset
   and treat it as an open launch risk, or (b) apply an **interim mark** in the
   primary palette and swap in the final asset post-launch (per the Risk 1
   mitigation). Record which you did in the setup note.

> **Requires the *Change Group Info* right** — only the Owner/L3 (or the bot, if
> granted that right; note VOL-196 leaves *Change Group Info* OFF for the bot, so
> in practice an L3/Owner does this) can set the group photo.

> Record in `config/pinned-message-ids.yaml`:
> `avatar.applied`, `avatar.asset_supplied`, and `avatar.notes` (final vs interim).

---

## 2. How pinning works here (read once before steps 3–8)

For **each** topic you will: (a) optionally set the topic **description**, then
(b) **post** the approved pinned message **inside that topic's thread**, then
(c) **pin** it.

- **Post in-thread:** open the topic first, then send — the message must land in
  that topic, not General. The pinned message's numeric **message_id** is what
  you record (capture it from the bot logs if the bot posts it, from
  `@RawDataBot`, or from the message link
  `t.me/c/<internal_group_id>/<thread_id>/<message_id>`).
- **Pin:** long-press the message → **Pin** (Desktop: right-click → **Pin
  Message**). When Telegram asks, pin **within this topic**. You do not need to
  notify all members; a silent pin is fine — the pin is still visible to everyone.
- **Topic descriptions:** Telegram forum topics have a **name** and an **icon**,
  but the per-topic free-text "description" surface is limited/▶ not consistently
  exposed across clients. Where your client exposes a topic description/about
  field (topic header → **Edit**), set it from the **"Topic description
  (optional)"** block of the matching source section. Where it is **not**
  supported, **skip it** — the pinned message carries the welcome copy regardless.
  Note "description unsupported on this client" in the setup note if you skip.

> **Order matters:** do the topics in the numbered order below (1→6). This keeps
> the recorded ids aligned with `config/group-setup.example.yaml` and the
> template's topic list.

---

## 3. Topic 1 — Announcements & Events  ⚠️ CLOSED TOPIC

> **Source copy:** `content/pinned-messages.md` → **"## 1. Announcements &
> Events"** → the fenced **Pinned message** block (starts `Welcome to
> Announcements & Events 🧡`). Optional description: the **Topic description**
> block (`Official community news & event invites. Admins post, members react 🧡`).

**This topic is CLOSED (admin-only posting) from VOL-196 §8. Do NOT reopen it.**

1. Open the **Announcements & Events** topic.
2. (Optional) Set the topic description from the source **Topic description**
   block, where your client supports it (step 2 caveat).
3. **Post as an admin.** Because the topic is closed, only admins can post —
   that is exactly what you want. Paste the approved **Pinned message** block
   verbatim and send. **Do NOT toggle "Close Topic" OFF / "Reopen" to post** —
   you already have post rights as an admin; reopening would unlock member
   posting and break the closed-topic guarantee.
4. **Pin** the message (long-press → **Pin**) within this topic.
5. **Verify the topic is still CLOSED:** the topic still shows its lock; a
   non-admin test account still **cannot post** but **can react**. If you
   accidentally reopened it, re-close it (topic header → **⋯ / Edit** →
   **Close Topic** ON) per VOL-196 §8.

> Record: `topics[0].pinned_message_id`, confirm `topic_remains_closed: true`.

---

## 4. Topic 2 — BOX Owners Lounge

> **Source copy:** `content/pinned-messages.md` → **"## 2. BOX Owners Lounge"** →
> the fenced **Pinned message** block (starts `Welcome to the BOX Owners Lounge
> 🧡`). Optional description: that section's **Topic description** block.

This is a model-lounge pin. The approved copy already contains the **required
pattern** verbatim — confirm it reads:
`This space is led by BOX owners sharing real experiences! If you're exploring the BOX, feel free to ask questions.`
(Do not edit it — it is correct as drafted in VOL-200.)

1. Open the **BOX Owners Lounge** topic.
2. (Optional) Set the topic description from the source **Topic description** block.
3. Paste the approved **Pinned message** block verbatim and send (open topic —
   posting as admin is fine).
4. **Pin** it within this topic.

> Record: `topics[1].pinned_message_id`.

---

## 5. Topic 3 — 007 Owners Club

> **Source copy:** `content/pinned-messages.md` → **"## 3. 007 Owners Club"** →
> the fenced **Pinned message** block (starts `Welcome to the 007 Owners Club
> 🧡`). Optional description: that section's **Topic description** block.

Model-lounge pin. Confirm the required pattern reads, verbatim:
`This space is led by 007 owners sharing real experiences! If you're exploring the 007, feel free to ask questions.`

1. Open the **007 Owners Club** topic.
2. (Optional) Set the topic description from the source **Topic description** block.
3. Paste the approved **Pinned message** block verbatim and send.
4. **Pin** it within this topic.

> Record: `topics[2].pinned_message_id`.

---

## 6. Topic 4 — VIGO Owners Circle

> **Source copy:** `content/pinned-messages.md` → **"## 4. VIGO Owners Circle"** →
> the fenced **Pinned message** block (starts `Welcome to the VIGO Owners Circle
> 🧡`). Optional description: that section's **Topic description** block.

Model-lounge pin. Confirm the required pattern reads, verbatim:
`This space is led by VIGO owners sharing real experiences! If you're exploring the VIGO, feel free to ask questions.`

1. Open the **VIGO Owners Circle** topic.
2. (Optional) Set the topic description from the source **Topic description** block.
3. Paste the approved **Pinned message** block verbatim and send.
4. **Pin** it within this topic.

> Record: `topics[3].pinned_message_id`.

---

## 7. General Community Chat — the built-in **General** topic

> **This deployment uses Telegram's built-in General topic as General Community
> Chat** (`thread_id 1`, `DFENG_TOPIC_GENERAL=1`). There is no separate topic to
> create — pin the General Community Chat copy in the built-in **General** topic.
>
> **Source copy:** `content/pinned-messages.md` → **"## 5. General Community
> Chat"** → the fenced **Pinned message** block (starts `Welcome to General
> Community Chat 🧡`). Optional description: that section's **Topic description**
> block.

1. Open the built-in **General** topic (always shown first in the topic list).
2. (Optional) Set the topic description from the source **Topic description** block.
3. Paste the approved **Pinned message** block verbatim and send.
4. **Pin** it within the General topic.

> Record: `topics[4].pinned_message_id` (this is the built-in General, `thread_id 1`).

---

## 8. Topic 6 — Support & Assistance

> **Source copy:** `content/pinned-messages.md` → **"## 6. Support &
> Assistance"** → the fenced **Pinned message** block (starts `Welcome to Support
> & Assistance 🧡`). Optional description: that section's **Topic description**
> block.

1. Open the **Support & Assistance** topic.
2. (Optional) Set the topic description from the source **Topic description** block.
3. Paste the approved **Pinned message** block verbatim and send.
4. **Pin** it within this topic.

> Record: `topics[5].pinned_message_id`.

---

## 9. Record the resulting message IDs

1. Copy the template:
   `cp config/pinned-message-ids.example.yaml config/pinned-message-ids.yaml`
   (the `.yaml` copy is **gitignored** — it references real ids).
2. Fill in:
   - `group.group_id` (same value as `config/group-setup.yaml`),
   - each topic's `thread_id` (from `config/group-setup.yaml`) and the
     `pinned_message_id` you captured when you pinned,
   - the `avatar` block (`applied`, `asset_supplied`, `notes`),
   - the `applied_checklist` flags as you verify each below.
3. Leave each `source_block` pointer as-is — it documents which approved block
   was pinned. The copy itself stays in `content/pinned-messages.md`; **do not**
   paste the message text into the YAML.
4. Keep the filled file out of git (it is matched by `.gitignore`). Confirm with
   `git status` that `config/pinned-message-ids.yaml` is **not** listed.

---

## Acceptance criteria checklist

Tick each before closing VOL-201:

- [ ] **Avatar applied** to the spec in `docs/branding-assets.md` (or interim
      mark applied and the final-asset dependency noted). `avatar.applied`
      recorded.
- [ ] **All six topics pinned** with the **approved copy** pasted **verbatim**
      from `content/pinned-messages.md` (one pinned message per topic, in order).
- [ ] **Three model lounges** (BOX / 007 / VIGO) each contain the required
      sentence `This space is led by [MODEL] owners sharing real experiences! If
      you're exploring the [MODEL], feel free to ask questions.` — verbatim, as
      already approved (not re-drafted).
- [ ] **Topic descriptions** set where the client supports them (skipped + noted
      where unsupported).
- [ ] **Pins visible** to both new and existing members in every topic (open a
      non-admin test account; the pin banner shows at the top of each topic).
- [ ] **Announcements & Events posting still LOCKED:** the topic is still
      **closed**; a non-admin still **cannot post** but **can react**; the pin was
      done **as admin without reopening** the topic.
- [ ] **Message IDs recorded** in `config/pinned-message-ids.yaml` (all six
      `pinned_message_id`s + avatar flag), and that file is **gitignored** (not
      shown by `git status`).

---

## Honest limitations / notes

1. **Avatar asset dependency.** The real avatar is stakeholder-supplied and not
   in this repo (Risk 1, `docs/branding-assets.md`). This runbook applies it; it
   does not create it. If unavailable at launch, apply an interim mark and swap
   later.
2. **Topic descriptions are client-dependent.** Telegram does not expose a
   free-text per-topic description consistently across clients. Where absent, the
   pinned welcome message carries the same intent — skip the description and note
   it; this is not a blocker.
3. **Pinning never changes posting permissions.** Pinning is independent of the
   closed-topic mechanism. The only way to break the Announcements lock is to
   *reopen* the topic — which this runbook explicitly forbids. Always pin as
   admin in the already-closed topic.
4. **One pin per topic.** If a topic later needs a different pin, unpin the old
   message and update `pinned_message_id` in the setup note so the bot/admins
   reference the current pin.
