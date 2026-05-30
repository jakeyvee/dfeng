# Launch seeding plan — owner-led model lounge activity

**Linear ticket:** VOL-216
**Companion deliverable:** `content/seed-content-calendar.md` (the concrete first-week posts)

This is the plan behind the calendar: *why* we seed, *who* owns each space, *how*
we handle prospects, and the tone guardrails. The ready-to-paste day-by-day copy
lives in the calendar — read the two together.

---

## 1. Why we seed (the cold-start problem)

The first 10–20 active people decide whether the lounges feel **alive or empty**.

- A brand-new private community looks like an empty room. New members peek in,
  see no conversation, and go quiet — that silence compounds.
- Our model is **owner-led**: the value is real owners answering real questions.
  But owners won't start talking into a void either. Someone has to break the ice
  *first*, authentically, so the room feels worth joining.
- So for the first week we **seed**: a small, named group of owners and admins
  post genuine prompts and answer early questions, modelling the kind of honest,
  helpful conversation we want the community to run on by itself.

**What seeding is NOT:** scripted marketing, drip campaigns, or bots. Every seed
post is a real person sharing a real experience or a real question. If a prompt
reads like an ad, it's wrong — rewrite it (see tone reminders, §5).

**Hard rule — no transactions in Telegram.** We never ask for a sale, a booking,
a test drive slot, a deposit, or a payment inside the community. Seeding sparks
conversation; it does not sell. Commercial intent (someone wanting to buy/book)
is handled warmly out-of-band — see §4.

---

## 2. Roles & ownership — who seeds and answers each space

Known admins (from the role register, `config/group-setup.yaml` → `admins:`):

- **Lucia — Community Lead (L1, Community Management).** Owns overall first-week
  activity: posts in General + Announcements, kicks off lounges where an owner
  seed isn't yet assigned, keeps an eye on every topic, and makes sure no
  prospect question sits unanswered.
- **Travis — Dongfeng Support (L2).** Owns anything that drifts into service,
  charging, warranty, or technical territory — answers it or routes it to
  **Support & Assistance**. Not the lounge conversation-starter; the safety net
  for "real ownership detail" questions across all three lounges.

We still need **1–3 more seed owners** — ideally one genuine, enthusiastic owner
per model who'll post and reply in their lounge. These gaps are launch risks
(§6). Until they're named, **Lucia seeds the unassigned lounge(s)** as an owner-
voiced host and Travis backs up the technical answers, but that's a stopgap: an
all-admin "owner" voice is thinner than a real owner's.

| Space | Primary seeder (starts convos) | Backup / answers detail | Status |
|-------|-------------------------------|-------------------------|--------|
| **BOX Owners Lounge** | BOX owner — **TBC** | Travis (L2) for service/charging detail; Lucia hosts | ⚠️ Risk — no BOX owner named |
| **007 Owners Club** | 007 owner — **TBC** | Travis (L2) for tech/warranty detail; Lucia hosts | ⚠️ Risk — no 007 owner named |
| **VIGO Owners Circle** | VIGO owner — **TBC** | Travis (L2) for service/charging/family-fit detail; Lucia hosts | ⚠️ Risk — no VIGO owner named |
| **General Community Chat** | **Lucia (L1)** | Any seed owner; Travis for support spillover | ✅ Covered |
| **Announcements & Events** | **Lucia (L1)** (admin-only topic) | L3 Management for sign-off on launch/event notes | ✅ Covered (sign-off TBC) |
| **Support & Assistance** | n/a — not seeded (reactive) | **Travis (L2)** answers as issues arrive | ✅ Covered |

Notes:
- **Support & Assistance is deliberately not seeded.** It's a reactive help desk,
  not a conversation lounge — seeding it with fake "issues" would be noise. Travis
  staffs it and picks up anything routed there.
- **Announcements & Events is admin-only** (closed topic — see
  `docs/telegram-setup.md` §8). Members react, they don't post. Only the two
  Announcements posts in the calendar go here, and ideally an **L3** signs off
  the launch note and any event before it's posted (sign-off owner TBC — §6).
- **Coverage target for week one:** at least one named human awake to answer in
  every lounge within a few hours during waking hours. With only Lucia + Travis
  confirmed, that's thin — hence the push to name owner seeders before launch.

---

## 3. Daily rhythm for the first week

Keep it light — this is a community, not a content machine.

- **~1 seed post per lounge per day** for the three model lounges (some days a
  fresh prompt, some days a follow-up that keeps yesterday's thread going).
- **1 General post most days** — the connective tissue that makes the whole
  place feel busy even on a quiet lounge day.
- **Announcements: 2 posts total in week one** — the launch/welcome note (Day 1)
  and a first event teaser (mid-week). Not more; Announcements stays clean.
- **Reply fast, reply real.** A seed prompt that gets no owner reply for a day
  looks worse than no prompt. Whoever posts a prompt watches it and replies to
  the first responders the same day.
- **Stagger, don't dump.** Spread posts through the day; don't fire all three
  lounge prompts in the same minute. It should feel like people, not a schedule.

---

## 4. Prospect-question handling (lightweight)

The lounge pins already welcome prospects: *"If you're exploring the BOX, feel
free to ask questions."* So prospects **will** ask. How we pick those up sets the
tone of the whole community.

**The approach — pick up promptly and warmly:**

1. **Acknowledge fast.** A prospect question answered within a few hours feels
   like a community; one left overnight feels dead. Whoever's on (seed owner,
   Lucia, or Travis) gives at least a quick, warm acknowledgement — even
   "Great question — let me grab the real numbers and come back 🧡" — so they
   know they've been heard.
2. **Owner answers first, admin backs up.** The best answer to "what's it
   actually like to own?" comes from an owner. Let the seed owner take it; admins
   step in only to add detail, correct gently, or fill a gap.
3. **Answer honestly, don't pitch.** Give the straight story — the good and the
   practical trade-offs. Prospects trust honesty far more than a sales line, and
   honesty is what makes them stay (see tone guide, §5).
4. **Route, don't sell.** If it's a service/charging/warranty/technical question,
   point them to **Support & Assistance**. If they signal **buying intent**
   (price, booking a test drive, "how do I order one") — **do not transact in
   Telegram.** Stay warm, keep the community answer, and move the commercial part
   off-channel: *"Love that you're keen 🧡 — the buying side is best handled
   directly off here; I'll have someone reach out / drop me a DM and we'll sort
   it."* No prices, no booking links, no payment talk in the lounges.
5. **Make them feel welcome to stay.** End by inviting them to keep hanging
   around — prospects who feel included become the next active owners.

**One-line reminder for admins:** *Answer the question, route the issue, never
sell in the room.*

---

## 5. Tone reminders (don't re-read the whole guide every time)

Full guidance: **`docs/tone-guide.md`**. The essentials for seeding:

- **Owner-led, not brand-led.** "A lot of owners find…", not "our award-winning
  vehicle…". If a seed post could appear in a brochure, rewrite it.
- **Talk like a person.** Warm, plain English; light Singaporean flavour is fine
  if natural. Share a real number, a real annoyance, a real win.
- **🧡 is our accent, not our wallpaper.** One occasional orange heart as a
  signature touch — not in every line, never stacked with other emoji.
- **Helpful before anything else.** Answer first, route second, never upsell.
- **Be brief and kind.** Especially when correcting someone.
- **Never sell.** No bookings, test-drive slots, prices, or payments in Telegram
  (§4). This is the one line that, if crossed, breaks the whole owner-led promise.

A good seed prompt = a real person, a real detail, an open door for others to
chime in. (See the calendar for model-specific examples.)

---

## 6. Launch risks (seeding-specific)

Recorded in the same spirit as `docs/branding-assets.md`.

### Risk 1 — No named owner seeders for the three lounges
- **What:** Lucia (L1) and Travis (L2) are confirmed, but we have **no named,
  genuine owner** assigned to seed and answer in BOX, 007, or VIGO. The model is
  owner-led; admins-as-owners is a weaker substitute.
- **Impact:** Lounges feel staffed rather than lived-in; prospects sense it.
  Cold-start risk only partly mitigated.
- **Owner:** Community Lead (Lucia) + stakeholders to recruit.
- **Mitigation:** Recruit **1 enthusiastic owner per model** before launch (3
  total ideal, 1 minimum to start). Until then Lucia hosts the unassigned
  lounge(s) in an owner-friendly voice and Travis supplies technical detail —
  treat as a stopgap, not the plan.

### Risk 2 — Thin first-week answer coverage
- **What:** With only two confirmed admins, keeping every lounge answered
  promptly through waking hours (§3) is a stretch.
- **Impact:** Slow replies to early prospect questions read as a dead room.
- **Owner:** Community Lead (Lucia).
- **Mitigation:** Name the extra seed owners (Risk 1); agree a light "who's on
  today" rota among the named people for week one; set a soft target of replying
  to prospect questions within a few hours during the day.

### Risk 3 — Announcements sign-off owner not named
- **What:** Announcements is admin-only and ideally **L3-signed-off** before
  launch/event notes go out. No specific L3 sign-off owner is recorded yet.
- **Impact:** Launch note or event teaser posted without management sign-off.
- **Owner:** L3 Management.
- **Mitigation:** Name the L3 who approves Announcements posts before Day 1.

---

## Acceptance-criteria check (VOL-216)

- Rationale for cold-start seeding ✓ (§1)
- Roles/ownership table — who seeds/answers each lounge + General + Announcements,
  with TBC gaps ✓ (§2), gaps recorded as launch risks ✓ (§6)
- Lightweight prospect-question handling approach ✓ (§4)
- Tone reminders referencing `docs/tone-guide.md` without restating it ✓ (§5)
- No sales/bookings/payments in Telegram, owner-led voice throughout ✓ (§1, §4, §5)
- Concrete first-week calendar ✓ → `content/seed-content-calendar.md`
