# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Dev Environment

```bash
# Activate venv and run local server (always port 8001)
cd /home/slach/Projects/atletasworld
source venv/bin/activate
cd src && python manage.py runserver 0.0.0.0:8001

# Run all tests
cd src && python manage.py test

# Run tests with pytest
pytest                          # from repo root
pytest src/clients/tests.py     # single file
pytest -m unit                  # by marker (unit, integration, slow)
pytest -k "test_booking"        # by name pattern

# Migrations
python manage.py makemigrations
python manage.py migrate

# Django system check (run before closing sessions)
python manage.py check          # must report 0 issues

# Load demo data
python manage.py load_demo_data
python manage.py load_team_demo_data
```

## CT315 Dev Server (Proxmox — atletasworld-dev)

- **Host**: CT315 on pve-05 — `192.168.1.235`
- **Access**: `ssh root@192.168.1.105 "pct exec 315 -- bash"`
- **Stopped by default** — start at session open, stop at session close

```bash
# Session open — start CT315
ssh root@192.168.1.105 "pct start 315"

# Run full test suite on CT315 (before every push)
make test-dev

# UI/UX testing — start dev server at http://192.168.1.235:8001
make dev-start
ssh root@192.168.1.105 "pct exec 315 -- /opt/atletasworld/dev-server.sh"

# Session close — stop CT315
make dev-stop
# or: ssh root@192.168.1.105 "pct stop 315"
```

**Session rules:**
- Start CT315 automatically at the beginning of every session
- Run `make test-dev` before every `git push origin main`
- Stop CT315 at session close — always check `pct status 315` before closing

## Production (EC2)

- **Server**: `3.135.174.227` — Ubuntu 24.04, us-east-2c
- **Domain**: `atletasperformancecenter.com` ✅ live
- **App dir**: `/var/www/atletasworld/`
- **SSH**: `ssh ubuntu@3.135.174.227` (password-less ubuntu user)
- **Deploy key**: `~/Documents/certs/atletasworld-deploy-key` (used by GitHub Actions)
- **Env file**: `/var/www/atletasworld/.env` (not in git)
- **DB**: SQLite at `/var/www/atletasworld/src/db.sqlite3`
- **Services**: Gunicorn + Celery via Supervisor, Nginx reverse proxy, Redis
- **Stripe restricted key**: `/home/slach/Projects/api/stripe-apc.api` (live mode, for prod DB fixes)

Push to `main` → GitHub Actions runs 199 tests → if pass, deploys via self-hosted runner on EC2.

Restart services manually:
```bash
sudo supervisorctl restart atletasworld atletasworld-celery
```

### Production DB changes
**Always ask before running** — show the proposed command and wait for explicit confirmation.
Never bulk-update prod DB without user approval. Single-record fixes still require confirmation.

## Project Structure

```
src/
  atletasworld/       # Django project package
    settings.py       # All config via django-environ (.env)
    urls.py           # All URL routing (no app-level urls for owner portal)
    admin_views.py    # All owner portal views (~300 lines)
    adapters.py       # Custom allauth adapter (silences login/logout messages)
    context_processors.py  # pending_field_rentals injected into all templates
  clients/            # Client + Player + Team models, client portal views
  coaches/            # Coach model, schedule, assessments, coach portal views
  bookings/           # Booking + SessionType + FieldRentalSlot + RentalService
  payments/           # Stripe payment records
  analytics/          # Analytics models
  reviews/            # Review model
templates/
  base.html           # Public site base (Bootstrap 5 + CDN)
  owner/base.html     # Owner portal base (Tailwind CDN)
  clients/            # Client portal templates (Bootstrap + Tailwind mix)
  coaches/            # Coach portal templates
  emails/             # Email templates
  account/            # django-allauth auth templates
static/gymlife/       # Static assets (CSS/JS/images)
scripts/
  server-setup.sh     # One-time EC2 bootstrap
  deploy.sh           # Called by CI after git pull
```

## Architecture

**Three portals, one Django project:**

| Portal | URL prefix | Auth check | Base template |
|--------|-----------|------------|---------------|
| Owner | `/owner-portal/` | `@user_passes_test(is_owner)` | `owner/base.html` |
| Coach | `/coach-portal/` | `@login_required` + Coach group | `coaches/` templates |
| Client | `/portal/` | `@login_required` | `clients/` templates |

**Login redirect** (`/login-redirect/`) routes users to their portal based on group membership: Owner → `/owner-portal/`, Coach → `/coach-portal/`, Client → `/portal/`.

**Owner portal views** all live in `src/atletasworld/admin_views.py` with URL names registered directly in `src/atletasworld/urls.py` (not via `include()`).

**Key model relationships:**
- `Client` (OneToOne → User) — parent/guardian account
- `Player` (FK → Client, FK → Team) — the athlete
- `Coach` (OneToOne → User) — coach profile with availability
- `Booking` (FK → Client, Player, Coach, ScheduleBlock, ClientPackage, FieldRentalSlot)
- `FieldRentalSlot` (FK → RentalService) — facility rental with owner approval workflow
- `RentalService` — service catalog (full field, partial field, room, gym)

**Context processor** `pending_field_rentals` injects `pending_field_count` into every owner template for the nav badge.

## Auth & Groups

Three Django auth groups: `Owner`, `Coach`, `Client`. Created automatically by migration `clients/0007_create_user_groups.py`.

- Owner: staff/superuser OR in Owner group (`is_owner()` helper in `admin_views.py`)
- Allauth handles login/signup; social auth configured but buttons hidden until HTTPS + credentials set up
- Custom adapter in `atletasworld/adapters.py` suppresses sign-in/sign-out flash messages

## Environment Variables

All config in `.env` (gitignored). See `.env.example` for full list. Key vars:

```
SECRET_KEY, DEBUG, ALLOWED_HOSTS, DATABASE_URL
TAX_RATE                    # 0.0–1.0, finance dashboard
CELERY_ENABLED              # requires Redis
SMS_ENABLED                 # Twilio, paid
PUSH_NOTIFICATIONS_ENABLED  # VAPID web push, free
PRODUCTION_EMAIL_ENABLED    # SendGrid/Mailgun
GOOGLE_CLIENT_ID/SECRET     # OAuth, needs HTTPS first
```

## Styling Conventions

- **Owner portal**: Tailwind CSS (CDN), indigo accent (`#6366f1` = `owner` color)
- **Client portal**: Bootstrap 5 (CDN) + some Tailwind
- **Public site** (`home.html`, etc.): Tailwind CSS (CDN), green `#2ecc71` / red `#e74c3c`
- **Emails**: Inline styles in `templates/emails/base_email.html`
- Django template `{% if %}` for active nav states — never use `{% with var=expr %}` for Python expressions (`in`, `or`, etc.) as Django's `with` tag doesn't support them

## Known Issues / Pending

See `docs/site-audit-2026-03-18.md` for full audit. Open items:
1. ~~`owner_teams` view — `AttributeError: player_count no setter`~~ ✅ fixed (view uses `active_player_count` annotation)
2. ~~Client facility rental page not properly routed at `/portal/field-rental/`~~ ✅ fixed (added nav links to dashboard dropdown + mobile menu)
3. ~~`owner_field_slots` — `FieldError: booked_at`~~ ✅ fixed (use `date__month`)
4. ~~Client dashboard "Session today" banner triggered on Sunday for Monday sessions~~ ✅ fixed (check `scheduled_date == today` before datetime math)

**Google OAuth** ✅ live — `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` added to EC2 `.env`, social login buttons enabled.

## APC Select Subscription — Key Facts

- **Package**: `Package pk=9`, `package_type='select'`, `stripe_price_id='price_1TvoTd3YFeMHn83GTjLB27fz'`
- **Invite gate**: `Client.select_invited` — toggle in Owner Portal → client detail page
- **Billing anchor**: `start_date + 1 month` from oldest expired package → if past, charge immediately; if future, trial until then
- **Stripe restricted key**: `rk_live_...` stored at `/home/slach/Projects/api/stripe-apc.api`
- **Webhook secret**: in `/var/www/atletasworld/.env` as `STRIPE_WEBHOOK_SECRET`
- **Check subscriptions**: `stripe.Subscription.list(limit=20)` using the restricted key

### Fix missing ClientPackage (paid Stripe sub, no DB record)
```python
# On prod shell: ssh ubuntu@3.135.174.227 then manage.py shell
from clients.models import Client, ClientPackage, Package
from django.utils import timezone; from datetime import timedelta
c = Client.objects.get(user__email='EMAIL')
pkg = Package.objects.get(pk=9)
ClientPackage.objects.create(
    client=c, package=pkg, status='active',
    start_date=timezone.localdate(),
    expiry_date=timezone.localdate() + timedelta(weeks=4),
    sessions_remaining=pkg.sessions_included,
    stripe_subscription_id='sub_xxx',
    stripe_payment_id='sub_activated_manual',
)
```

## Session Close Checklist

Run these checks before closing a development session:

### Required
- [ ] **Stop CT315**: `make dev-stop` or `ssh root@192.168.1.105 "pct stop 315"`
- [ ] **Django check passes**: `cd src && python manage.py check` → must report 0 issues
- [ ] **All changes committed**: `git status` → working tree clean
- [ ] **Tests passing**: `make test-dev` or CI build green
- [ ] **Pushed to main**: `git push origin main` → triggers auto-deploy

### Optional (if applicable)
- [ ] **Update hustle modules**: If you implemented a reusable feature (auth, payments, referrals, etc.), update the corresponding template in `/home/slach/Projects/hustle/modules/`. Sync new features, edge cases, and production checklist items.
- [ ] **Migration check**: If models changed, verify migration created: `python manage.py makemigrations --check --dry-run`
- [ ] **Documentation**: Update README or docs/ if architecture changed
- [ ] **Memory updated**: If user gave important feedback or context, save to `~/.claude/projects/-home-slach-Projects-atletasworld/memory/`

### Hustle Module Sync Workflow
When a feature maps to a hustle module:
1. Identify the module: `/home/slach/Projects/hustle/modules/<feature>.md`
2. Add sections for any new capabilities (retroactive flows, admin views, edge cases)
3. Update the Production Checklist with optional features
4. Commit locally: `cd /home/slach/Projects/hustle && git add modules/<feature>.md && git commit -m "docs: sync <feature> module with atletasworld implementation"`

**Current hustle modules:**
- `referral_program.md` ✅ (synced 2026-05-09)
- `stripe_integration.md`
- Others as created...

## Backlog

- ~~**Task #13 — Email players on Select game publish**~~ ✅ complete (2026-07-26) — `fanout_select_game_rsvps` now emails each new RSVP recipient (guarded by `PRODUCTION_EMAIL_ENABLED`); `select_game_published.html` template added; 4 tests.
- ~~**Task #12 — APC Select Membership recurring billing**~~ ✅ complete (2026-07-22) — Stripe webhooks live, subscription confirmed working in production.
- **Task #11 — Enable Venmo in Stripe Dashboard**: No code changes needed, pure Stripe config.
- ~~**Task #7 — Google OAuth login**~~ ✅ complete (2026-07-26)

## Code Review Backlog (from docs/code-review-2026-07-22.md)

- ~~**#1 — Split `admin_views.py`**~~ ✅ complete (2026-07-30) — 70 views split into `owner_views/` package (22 domain modules); shim keeps `urls.py`/`tasks.py` unchanged.
- **#2 — Split remaining god-objects**:
  1. ~~`clients/views.py`~~ ✅ complete (2026-07-30) → `clients/views/` package (9 modules)
  2. ~~`clients/models.py`~~ ✅ complete (2026-07-30) → `clients/models/` package (5 modules); `makemigrations --check` confirmed 0 new migrations
  3. ~~`payments/views.py`~~ ✅ complete (2026-07-30) → webhook handlers extracted to `payments/webhook_handlers.py`
  4. ~~`coaches/views.py`~~ ✅ complete (2026-07-30) → `coaches/views/` package (11 modules)
  5. ~~`clients/tasks.py`~~ ✅ complete (2026-07-30) → `clients/tasks/` package (5 modules); Celery task names verified
  6. ~~**`bookings/api.py`**~~ ✅ complete (2026-07-30) — `BookingViewSet.create` (506L) extracted to `bookings/booking_service.py`; `BookingError` exception class; ViewSet is now a ~20-line dispatcher
- ~~**#3 — Refund amount `Decimal`**~~ ✅ complete (2026-07-30)
- ~~**#4 — Log swallowed exceptions**~~ ✅ complete (2026-07-30) — 4 bare `pass` blocks in `clients/services.py` now log at debug level
- ~~**#5 — AI assist leaks exception text**~~ ✅ complete (2026-07-30) — logs server-side, returns generic message to client
- ~~**#6 — `owner_blog_ai_assist` missing `@require_POST`**~~ ✅ complete (2026-07-30) — all 3 AI assist views now use `@require_POST`
- ~~**#7 — Remove `.env.dev.bak` from git**~~ ✅ complete (2026-07-30)
- ~~**#8 — Clean repo root**~~ ✅ complete (2026-07-30) — 18 playwright scripts → `scripts/playwright/`, PNGs → `.screenshots/`
- ~~**#9 — Hardcoded Ollama fallback IP**~~ ✅ complete (2026-07-30) — bails with 503 when `OLLAMA_BASE_URL` unset
- ~~**#10 — Owner portal test coverage**~~ ✅ complete (2026-07-30) — 90 tests in `src/atletasworld/tests_owner_views.py`; 14 classes covering auth walls, CRUD lifecycle, JSON endpoints, Stripe mock, AI assist; 308 total tests passing
