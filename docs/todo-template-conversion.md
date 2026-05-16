# SaaS Template Conversion — TODO

**Date added:** 2026-04-27
**Goal:** Turn atletasworld into a reusable whitelabel template for sports/fitness clients.
**Model:** Separate deployment per client, feature flags per client, owner self-manages settings.

---

## Phase 1 — Branding, Flags, Cleanup (45–65 hrs / $6,750–$9,750)

### 1. SiteConfig Model (branding config-driven)
- [ ] Create `SiteConfig` model in `clients/models.py` (or new `config` app)
  - Fields: `gym_name`, `gym_address`, `contact_email`, `contact_phone`
  - Fields: `primary_color`, `accent_color`, `logo`, `favicon`
  - Fields: `font_heading`, `font_body`
  - Singleton pattern (only one row)
- [ ] Migration
- [ ] Replace hardcoded APC values in templates with `{{ site_config.gym_name }}` etc.
- [ ] Context processor to inject `site_config` into all templates
- [ ] Owner portal: basic edit page at `/owner-portal/site-settings/`

### 2. Feature Flags (`.env` driven)
Add to `settings.py` + `.env.example`:
- [ ] `FEATURE_FIELD_RENTAL` — field rental module
- [ ] `FEATURE_TEAMS` — teams management
- [ ] `FEATURE_MEMBERSHIP` — APC Select / membership packages
- [ ] `FEATURE_TOURNAMENTS` — tournament session format
- [ ] `FEATURE_ASSESSMENTS` — player assessments
- [ ] `FEATURE_DISCOUNT_CODES` — promo/discount codes
- [ ] `FEATURE_SIBLING_DISCOUNT` — auto sibling discount
- [ ] `FEATURE_BULK_EMAIL` — bulk email broadcast
- [ ] `FEATURE_REFERRAL` — referral program (future)

Hide nav links, views, and owner portal sections when flag is off.
Use template tag `{% if feature_enabled "FIELD_RENTAL" %}` or context var.

### 3. Remove APC-Specific Hardcoding
- [ ] Strip APC Select monthly credit logic to flag-gated code path
- [ ] Remove hardcoded tryout schedule / May 2026 dates
- [ ] Remove hardcoded "Indian Woods Middle School" location references
- [ ] Genericize demo data loader (`load_demo_data` / `load_team_demo_data`)
- [ ] Rename Django project package `atletasworld` → `sportshub` (or keep, document rename step)
- [ ] Update `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` to use `.env` only (already done mostly)

---

## Phase 2 — Owner Settings UI + Deploy Automation + Docs (33–45 hrs / $4,950–$6,750)

### 4. Owner Self-Service Settings Page
- [ ] `/owner-portal/site-settings/` — edit `SiteConfig`
  - Logo upload (S3 or local media)
  - Primary/accent color pickers
  - Gym name, address, contact info
  - Tax rate
- [ ] `/owner-portal/site-settings/features/` — toggle feature flags (or keep `.env` only)

### 5. Deploy Automation
- [ ] `scripts/new-client-setup.sh` — EC2 bootstrap for new client
  - Install deps, clone repo, set up venv, Nginx config, Supervisor config, SSL
- [ ] `.env.template` — every variable documented with description + example
- [ ] `docs/new-client-checklist.md` — step-by-step for each new deployment
  - Domain setup, Stripe account, SendGrid/Gmail, GitHub repo fork, EC2 launch

### 6. Documentation
- [ ] `docs/template-overview.md` — what the template is, architecture, portals
- [ ] `docs/feature-flags.md` — every flag, what it controls, default value
- [ ] `docs/customization-guide.md` — branding, colors, logo, fonts
- [ ] `docs/new-client-checklist.md` — deployment checklist

---

## Revenue Model

| Model | Structure | Target |
|-------|-----------|--------|
| One-time build | $3K–$8K per client | Faster to sell |
| Monthly SaaS | $150–$400/mo per client | Passive income |
| **Recommended** | $2K setup + $200/mo | Best of both |

**Break-even:** ~5–8 clients at $200/mo, or 2–3 one-time builds.

---

## Notes
- Keep atletasworld repo as the "reference implementation" — branch `template` for generic version
- Each client gets their own forked private repo + EC2
- Stripe, SendGrid, domain all client-owned (reduces your liability)
- Consider `django-tenants` only if future client wants multi-tenant (different beast)
