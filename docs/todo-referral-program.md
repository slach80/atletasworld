# Referral Program — Feature TODO

**Date added:** 2026-04-27
**Status:** Scoping / pending client details

---

## Open Questions (need client answers)

- [ ] Who can refer? Clients only, or coaches too?
- [ ] Reward type: store credit, cash payout (Stripe), discount code, or tracking only?
- [ ] Reward amount: fixed $X, % of first purchase, or tiered?
- [ ] Activation trigger: account signup, first purchase, or X sessions/events attended?
- [ ] Multi-level referrals (referred person can also refer), or 1 level only?
- [ ] Does unused credit expire? If so, after how long?
- [ ] Referral window: must referred person convert within X days?

---

## Estimate

| Scenario | Hours | @ $150/hr |
|----------|-------|-----------|
| Low — signup trigger, store credit, basic tracking | 5–8 hrs | $750–$1,200 |
| High — custom trigger (X sessions), full dashboard, tiered rewards | 15–20 hrs | $2,250–$3,000 |

**Recommended quote:** $1,500–$2,000 mid-tier (unique codes, first-purchase activation, store credit, basic dashboard)

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

1. `Referral` model — link referrer → referred client, track status + activation
2. Unique referral code per client (auto-generate on account creation or on demand)
3. Referral code capture at signup (optional "referred by" field)
4. Activation trigger logic (configurable: signup / first purchase / X sessions)
5. Auto-grant `ClientCredit(credit_type='referral')` when trigger fires
6. Client-facing referral page: share link, list referrals, credit earned
7. Owner referral overview: all referrals, pending/confirmed, total credits issued

---

## Implementation Plan (draft)

### Phase 1 — Core (low estimate)
- [ ] `Referral` model in `clients/models.py`
- [ ] Migration
- [ ] Auto-generate referral code on `Client` save (post_save signal)
- [ ] Capture referrer at signup (allauth adapter hook)
- [ ] Activate + grant credit on first purchase (hook into payment confirmed flow)
- [ ] Owner: view all referrals at `/owner-portal/referrals/`

### Phase 2 — Client Dashboard (bumps to mid estimate)
- [ ] Client referral page at `/portal/referrals/`
- [ ] Share link + copy button
- [ ] Table: referred people, status (pending/confirmed), credit earned
- [ ] Credit balance display (reuse existing credit UI)

### Phase 3 — Advanced (high estimate)
- [ ] Custom activation trigger (X sessions attended)
- [ ] Tiered rewards config (owner sets tiers)
- [ ] Referral analytics on owner finance dashboard
