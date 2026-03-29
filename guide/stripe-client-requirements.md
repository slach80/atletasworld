# Stripe Payment Integration — What We Need From You

This document lists everything we need from Atletas Performance Center to connect online payments to the website. Completing this takes about 30–60 minutes and can be done in one sitting.

---

## Step 1 — Create a Stripe Account

If you don't already have one:

1. Go to **https://stripe.com** and click **Start now**
2. Sign up with the business email address you use for Atletas Performance Center
3. Verify your email address

> If you already have a Stripe account for the business, just log in — no need to create a new one.

---

## Step 2 — Activate Your Account (Stripe Onboarding)

Stripe requires identity and banking information before you can receive real payments. This is a one-time setup inside your Stripe account.

Go to **https://dashboard.stripe.com/account/onboarding** and complete the following:

### Business Information
- Legal business name (as registered, e.g. "Atletas Performance Center LLC")
- Business type (sole proprietor, LLC, corporation, etc.)
- Business address
- Business phone number
- Business website: `https://atletasperformancecenter.com`
- Industry/business category: *Sports & Recreation*
- Brief description of what you sell (e.g. "Youth soccer training sessions and facility rentals")

### Owner / Identity Verification
- Owner's legal name
- Date of birth
- Home address
- Last 4 digits of SSN (or full SSN — Stripe uses this to verify identity, not charge you)
- A government-issued ID may be requested (driver's license or passport photo)

### Bank Account for Payouts
- Bank name
- Routing number
- Account number

This is where Stripe deposits your earnings (typically within 2 business days after a payment).

---

## Step 3 — Send Us Your API Keys

Once your account is active:

1. In the Stripe Dashboard, click **Developers** (top right) → **API keys**
2. You will see two keys in **Test mode** to start — that's fine
3. Send us both keys **securely** (not by email — use a password manager share link or a secure message):

| Key | What it looks like |
|---|---|
| Publishable key | `pk_live_...` |
| Secret key | `sk_live_...` |

> **Important:** Never share your Secret key by email or text. Use a secure method — options below.

**Secure ways to share keys:**
- Share via **1Password** or **Bitwarden** (send a secure link)
- Use **https://onetimesecret.com** — paste the key, send us the one-time link
- Share through the Stripe Dashboard itself by adding us as a team member (see Step 4)

---

## Step 4 (Optional) — Add Developer as Team Member

If you prefer not to share keys directly, you can invite us to your Stripe account with limited access:

1. Stripe Dashboard → **Settings** → **Team and security** → **Team members**
2. Click **Invite user**
3. Enter the developer's email address
4. Set role to **Developer**
5. Send the invite

This lets us retrieve the keys ourselves without you needing to copy/paste them.

---

## Step 5 — Decide Your Pricing

Before we go live, confirm the prices for each item clients will be able to pay for online:

### Training Packages
For each package (e.g. "10-Session Pack", "Monthly Unlimited"):
- Package name
- Price in USD
- Is it a one-time purchase or a monthly recurring charge?

### Facility Rentals
- Full field rental price (per hour or flat rate?)
- Partial field rental price
- Room rental price
- Gym rental price

> These should already match what's in the system. We just need final confirmation before connecting payments.

---

## Step 6 — Confirm Tax Handling

- Do you collect sales tax on training sessions? If yes, what percentage?
- Do you collect sales tax on facility rentals?

> Note: Stripe can handle automatic tax calculation if needed — let us know if you'd like that enabled.

---

## Summary Checklist

Send us the following when ready:

- [ ] Stripe account created and activated (onboarding complete)
- [ ] Publishable key (`pk_live_...`)
- [ ] Secret key (`sk_live_...`) — sent securely
- [ ] Bank account connected in Stripe (for payouts)
- [ ] Pricing confirmed for all packages and rentals
- [ ] Tax rate confirmed (or "no tax")

---

## Timeline

Once we have everything above:

- **Test mode setup**: 1–2 days — we wire everything up and test with fake card numbers
- **Go live**: 1 day — swap to live keys, register webhook, final check
- **Total**: approximately 3–5 business days from receiving your keys

---

## Questions?

Contact the developer with any questions about this process. Stripe also has a 24/7 support chat at **https://support.stripe.com** for account-specific questions (identity verification, bank issues, etc.).
