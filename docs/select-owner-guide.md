# APC Select — Owner & Coach Operations Guide

## Overview

The Select program now runs entirely inside the portal. This guide covers every step Mirko and the coaches need to operate it: activating billing, managing teams, scheduling practices and games, and tracking attendance.

---

## Part 1 — One-Time Setup (Mirko only)

### 1.1 Create Stripe recurring prices

Before auto-renewal works, each billing tier needs a matching recurring Price in Stripe.

1. Go to **Stripe Dashboard → Products → Create product**
2. Name it `APC Select Membership`
3. Add a **recurring price** for each tier you want to offer:

| Tier | Billing interval | Recommended price |
|---|---|---|
| Monthly | Every 1 month | $100 |
| Thirds | Every 4 months | TBD |
| Half | Every 3 months | TBD |
| Full Year | Every 12 months | TBD |

4. Copy the `price_xxx` ID for each price you create.

### 1.2 Configure packages in the Owner Portal

1. Go to **Owner Portal → Packages**
2. Find (or create) a package for each billing tier you want to offer
3. For each one, click **Edit** and fill in:
   - **Package Type** → `APC Select Membership`
   - **Billing Tier** → match the tier (Monthly / Thirds / Half / Full Year)
   - **Stripe Price ID** → paste the `price_xxx` from Step 1.1
   - **Price** → the amount per payment
   - **Validity weeks** → how long one payment period covers (Monthly = 4, Thirds = 16, Half = 12, Full = 52)
   - Check **Active** and **Purchasable**
4. Save. Repeat for each tier.

Once Stripe Price IDs are saved, the **Join APC Select** button on the client Packages page will route through Stripe Subscriptions and auto-renew will be live.

### 1.3 Enable subscription webhook events in Stripe

The webhook endpoint is already registered at `https://atletasperformancecenter.com/payments/webhook/` and handles one-time payment events. For subscriptions to work you need to add four more events:

1. Go to **Stripe Dashboard → Developers → Webhooks**
2. Click the existing `atletasperformancecenter.com` endpoint
3. Click **Add events** and enable:

| Event | What it triggers |
|---|---|
| `invoice.payment_succeeded` | Extends membership on each successful renewal charge |
| `invoice.payment_failed` | Alerts the member to update their card (first attempt only) |
| `invoice.upcoming` | Sends a 7-day advance notice before the next charge |
| `customer.subscription.deleted` | Marks the package inactive when a subscription is cancelled in Stripe |

4. Save. No code changes needed — the handlers are already wired in.

### 1.4 Mark existing teams as Select teams

This should already be done automatically for the 2014, 2015, and 2016 teams. To verify or add a new team:

1. Go to **Owner Portal → Teams**
2. Edit the team → confirm **Is Select Team** is checked
3. For any future year group, create the team and check **Is Select Team**

### 1.5 Reassign old "APC select game" schedule blocks

Old workaround game blocks in the coach schedule need to be cleaned up:

1. Go to **Coach Portal → Schedule**
2. Select all blocks named "APC Select Game" (the old ones)
3. Use **Bulk Edit** → reassign their session type to **APC Select Practice**
4. Going forward, use the new **Select Games** section for actual games

---

## Part 2 — Day-to-Day: Practices

Practices are created through the normal **Coach Portal → Schedule** flow — nothing changes there. The only difference is the session type.

### Creating a Select practice block

1. Go to **Coach Portal → Schedule → Add Block** (or Bulk Add)
2. Set **Session Type** → `APC Select Practice`
3. Set **Select Team** → pick the specific team (2014, 2015, 2016) if this practice is team-specific. Leave blank for an all-teams open session.
4. Set date, time, max participants, coach — save.

**What happens automatically:**
- Only Select members on that team see the block in their booking calendar
- All-team blocks (no Select Team set) are visible to all active Select members
- Non-Select clients never see these blocks
- The first 2 bookings per player per month auto-confirm at $0
- A 3rd booking in the same month falls through to normal checkout (client uses a $40 credit or program package)

---

## Part 3 — Day-to-Day: Games

Games live in their own section, separate from the booking calendar.

### 3.1 Creating a game

**Owner Portal → Select Games → + New Game**
**Coach Portal → Select Games → + New Game**

Fill in:

| Field | Notes |
|---|---|
| **Team** | Which team is playing (2014, 2015, or 2016) |
| **Date** | Game date |
| **Start / End Time** | End time is optional |
| **Location** | Full address or venue name |
| **Coach** | Assign a coach (optional) |
| **Notes** | Opponent name, field number, warm-up instructions, etc. |

Save as **Draft** if you're not ready to notify players yet. The game is invisible to members until you publish.

### 3.2 Adding guest players

Before or after publishing, you can invite individual non-Select clients (e.g. a guest player Mirko wants to include):

1. Open the game detail page
2. Scroll to **Add Guest Invitee**
3. Search by client name → **Add**
4. If the game is already published, the guest receives an RSVP notification immediately

### 3.3 Publishing a game

When everything is set, click **Publish & Notify Team** on the game detail page.

**What happens automatically:**
- Every active Select member on that team gets an in-app notification: "APC Select game on [date] at [location] — RSVP on your dashboard"
- An `SelectGameRSVP` record is created for each member (status: No Response)
- Members see the game on their dashboard with **Going / Can't Go** buttons
- The game is safe to re-save or edit — publishing is idempotent, no duplicate notifications

### 3.4 Monitoring attendance

Open the game detail page at any time to see the live roster:

- **✅ Coming** — players who confirmed
- **❌ Not Coming** — players who declined  
- **⏳ No Response** — players who haven't responded yet

### 3.5 Game day digest

The morning before each published game (8 AM), the owner and assigning coach receive an email with the full attendance summary: confirmed list, not-coming list, and no-response count. No action needed — this fires automatically.

---

## Part 4 — Select Membership Management

### Viewing active members and credits

**Owner Portal → Credits**

The Credits page shows all active Select members, their credit balance, and when credits expire. From here you can:

- **Grant a manual credit** — select a client, enter amount and reason
- **Cancel a credit** — removes an available credit that hasn't been applied

### Managing player team assignments

By default, players are matched to their Select team by birth year. To manually reassign or add a guest callup:

- **Owner Portal → Clients → [client name] → Players**
- Edit the player and set or change their **Team** field to the appropriate Select team
- For cross-team callups, use the **Select Teams** multi-select to add them as a guest on additional teams without changing their primary team

### Adjusting session counts

If a player's monthly practice count needs a correction (e.g. a no-show that was marked confirmed):

**Owner Portal → Bookings** → find the booking → cancel it. The system handles the counter correctly — no manual adjustment needed.

---

## Part 5 — Billing & Renewals

### How auto-renewal works

Once Stripe Price IDs are configured (Part 1):
1. Client purchases a Select tier on the Packages page via Stripe subscription checkout
2. Stripe charges the card automatically each billing period
3. On successful charge: membership expiry extends by the correct interval, client gets an in-app confirmation
4. 7 days before renewal: client gets an advance notice notification
5. If payment fails: client gets an alert to update their card; Stripe retries automatically (3 attempts over ~4 days)
6. If cancelled: membership stays active until period end, then expires

### Manual-pay members (no Stripe subscription)

Members who paid via one-time checkout (or were manually activated) get:
- **30-day reminder** before expiry
- **7-day reminder** before expiry

Both prompt them to renew via the Packages page.

### Cancellation

Clients can cancel auto-renewal themselves: **Portal → Packages → Cancel auto-renewal**. This sets `cancel_at_period_end` in Stripe — they keep access until the end of the current period.

As the owner, you can also cancel or adjust packages directly from **Owner Portal → Clients → [client] → Packages**.

---

## Part 6 — Quick Reference

### Owner Portal navigation

| Section | URL | Purpose |
|---|---|---|
| Select Games | `/owner-portal/select/games/` | Create, publish, view roster |
| Credits | `/owner-portal/credits/` | Grant credits, view Select member balances |
| Packages | `/owner-portal/packages/` | Configure billing tiers and Stripe Price IDs |
| Clients | `/owner-portal/clients/` | Manage player team assignments |
| Bookings | `/owner-portal/bookings/` | View and cancel any booking |

### Coach Portal navigation

| Section | URL | Purpose |
|---|---|---|
| Select Games | `/coach-portal/select/games/` | Create and publish team games |
| Schedule | `/coach-portal/schedule/` | Add Select practice blocks |

### Checklist for each new Select member

- [ ] Player's birth year matches their team (auto-assigned on signup)
- [ ] Verify team shows on their dashboard after first login
- [ ] Confirm 6 × $40 credits were seeded (visible in Owner Portal → Credits)
- [ ] If using auto-renewal, confirm `stripe_subscription_id` is set on their package

### Checklist for each new season / year group

- [ ] Create team in Owner Portal → Teams with **Is Select Team** checked
- [ ] Create a billing tier Package with correct `stripe_price_id` and `billing_tier`
- [ ] Brief coaches: use `APC Select Practice` session type with the new team's **Select Team** field set
