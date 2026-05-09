# Referral Program — Feature TODO

**Date added:** 2026-04-27
**Answers collected:** 2026-04-27/28
**Status:** Scoping complete — ready to estimate

---

## Decisions (from Mirko, 2026-04-27/28)

| # | Question | Answer |
|---|----------|--------|
| 1 | Who can refer? | Both clients **and** coaches |
| 2 | Reward type | Store credit (clients); cash/credit (coaches) |
| 3 | Reward amount | Clients: **10%** of referral's first package; Coaches: **20%** |
| 4 | Activation trigger | **First purchase** by the referred person |
| 5 | Applies to | All packages, pick-up sessions, and camps/clinics |
| 6 | Multi-level? | **1 level only** (Alice refers Bob → Alice earns; Bob refers Carol → Bob earns, Alice gets nothing) |
| 7 | Credit expiry | **2 months** from issuance |
| 8 | Referral window | Referred person must make first purchase within **2 months** of signup |

---

## Estimate

| Scenario | Hours | @ $150/hr |
|----------|-------|-----------|
| Low — signup trigger, store credit, basic tracking | 5–8 hrs | $750–$1,200 |
| High — custom trigger (X sessions), full dashboard, tiered rewards | 15–20 hrs | $2,250–$3,000 |

**Recommended quote:** $1,500–$2,000 mid-tier (unique codes, first-purchase activation, store credit, basic dashboard)

> Coach reward is a cash/credit payout (20%) vs. client credit (10%) — the coach payout mechanism may need a separate model or manual review step; clarify before build.

---

## What Already Exists (reduces scope)

- `ClientCredit` model — already has `credit_type='referral'` field ready
- `DiscountCode` + `DiscountCodeUse` — full code validation + redemption tracking
- Sibling auto-discount — pattern for auto-applying credits at checkout
- Owner discount codes dashboard — extendable for referral management
- Notification system — email + in-app on events
- Celery tasks — async reward processing

---

## New Work Required

1. `Referral` model — link referrer (Client or Coach) → referred client, track status + activation
2. Unique referral code per client/coach (auto-generate on account creation or on demand)
3. Referral code capture at signup (optional "referred by" field)
4. Activation trigger: fire on first purchase within 2-month window
5. Auto-grant `ClientCredit(credit_type='referral')` (10%) when trigger fires for clients
6. Coach reward: 20% credit or payout record — owner review step TBD
7. Expiry: credit records stamped with `expires_at = issued_at + 60 days`
8. Client-facing referral page: share link, list referrals, credit earned
9. Owner referral overview: all referrals, pending/confirmed, total credits issued

---

## Implementation Plan (draft)

### Phase 1 — Core (low estimate)
- [ ] `Referral` model in `clients/models.py`
- [ ] Migration
- [ ] Auto-generate referral code on `Client` / `Coach` save (post_save signal)
- [ ] Capture referrer at signup (allauth adapter hook)
- [ ] Activate + grant credit on first purchase (hook into payment confirmed flow)
- [ ] Enforce 2-month referral window (check `referred_at + 60 days >= purchase_date`)
- [ ] Set `expires_at` on issued `ClientCredit` records
- [ ] Owner: view all referrals at `/owner-portal/referrals/`

### Phase 2 — Client Dashboard (bumps to mid estimate)
- [ ] Client referral page at `/portal/referrals/`
- [ ] Share link + copy button
- [ ] Table: referred people, status (pending/confirmed), credit earned
- [ ] Credit balance display (reuse existing credit UI)

### Phase 3 — Coach Payout (add-on)
- [ ] Decide coach reward mechanism: `ClientCredit` on coach account vs. manual payout record
- [ ] Coach referral page at `/coach-portal/referrals/`
- [ ] Owner review/approve coach payouts

### Phase 4 — Advanced (high estimate)
- [ ] Tiered rewards config (owner sets tiers)
- [ ] Referral analytics on owner finance dashboard
