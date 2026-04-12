# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Dev Environment

```bash
# Activate venv and run local server (always port 8001)
cd /Users/DT87019/Projects/atletasworld
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

## Production (EC2)

- **Server**: `3.135.174.227` — Ubuntu 24.04, us-east-2c
- **Domain**: `atletasperformancecenter.com` (DNS pending)
- **App dir**: `/var/www/atletasworld/`
- **SSH**: `ssh -i ~/Documents/certs/atletasworld-prod.pem ubuntu@3.135.174.227`
- **Deploy key**: `~/Documents/certs/atletasworld-deploy-key` (used by GitHub Actions)
- **Env file**: `/var/www/atletasworld/.env` (not in git)
- **Services**: Gunicorn + Celery via Supervisor, Nginx reverse proxy, Redis

Push to `main` → GitHub Actions runs tests (GitHub-hosted) → deploys via self-hosted runner on EC2.

Restart services manually:
```bash
sudo supervisorctl restart atletasworld atletasworld-celery
```

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

**Next up**: SSL cert once `atletasperformancecenter.com` DNS propagates → then Google OAuth setup.
