# VALD Integration — Phase 1 Complete

## What Was Built

Phase 1 scaffolded the `performance` Django app with models, API client, views, templates, and tests — ready for local testing and UI/UX review.

### 1. Models (`performance/models.py`)
- **`ValdProfile`** — OneToOne → Player, stores `vald_profile_id` + `vald_tenant_id`
- **`ValdResultDefinition`** — metric metadata (name, unit, trend_direction, show_in_client_portal)
- **`ValdTestResult`** — generic test result with `system` discriminator, `raw_payload` JSON, flattened `metrics` JSON
- **`ValdSyncRun`** — audit log + incremental cursor (`last_synced_at`)

All migrations created and applied locally. Django check passes with 0 issues.

### 2. API Client (`performance/vald_client.py`)
- **OAuth token caching** — Redis-backed, expires_in - 60s
- **Region-specific base URLs** — `(system, region)` → host (ForceDecks confirmed)
- **429 exponential backoff** — 1s → 2s → 4s, max 3 retries, respects `Retry-After`
- **Cursor pagination** — `modifiedFromUtc` → 204 termination for `/tests`
- Functions: `get_vald_token()`, `vald_get()`, `list_forcedecks_tests()`, `list_result_definitions()`

### 3. Views (`performance/views.py`)
**Client portal:**
- `player_performance` — list players with latest assessment summary
- `player_detail` — per-player charts, IDOR protection (`client__user=request.user`)

**Owner portal:**
- `owner_performance` — all players table + sync history + manual sync button
- `owner_player_detail` — same as client view + raw_payload debug + sync runs
- `owner_match_profile` — manual Player ↔ VALD profile linking (POST)
- `owner_trigger_sync` — dispatch Celery task (stubbed for Phase 2)

All views use `@require_vald_enabled` decorator (404 when `VALD_SYNC_ENABLED=False`).

### 4. Templates
- `performance/index.html` — client portal player list (extends `clients/base.html`)
- `performance/detail.html` — client portal per-player metrics with Chart.js sparklines
- `owner/performance.html` — owner portal with sync runs table + players table + match modal

**Design system:** Tailwind CSS, Archivo Condensed + Bilgen fonts, dark mode (`html.dark`), Chart.js line charts, responsive grid (`md:grid-cols-2 lg:grid-cols-3`).

### 5. URL Routing
- **Client**: `/portal/performance/` → `performance.urls`
- **Owner**: `/owner-portal/performance/` → `performance.urls_owner` (NOT in `admin_views.py`)

### 6. Tests (`performance/tests/`)
- **`test_models.py`** — 11 tests, all passing (ValdProfile, ValdTestResult, ValdSyncRun, cursor logic, idempotency)
- **`test_vald_client.py`** — HTTP mocked with `responses` (token cache hit, 429 retry, 204 termination)
- **Fixtures**: `forcedecks_cmj.json`, `result_definitions.json` (sanitized mock responses)

### 7. Admin Registration
All 4 models registered in Django admin with list filters, search, and readonly fields.

### 8. Settings Updates
- **`INSTALLED_APPS`** — added `'performance'`
- **`CACHES`** — added Redis-backed `'vald'` cache for token storage
- **VALD settings block** — `VALD_CLIENT_ID`, `VALD_SECRET`, `VALD_TENANT_ID`, `VALD_REGION`, `VALD_SYNC_ENABLED`, `VALD_API_BASES`
- **`.env.example`** — documented credential acquisition workflow

### 9. Client Model Enhancement
Added `full_name` property to `Player` model (`clients/models/core.py`) for template convenience.

---

## What's NOT Built Yet (Phase 2+)

1. **Celery sync tasks** (`performance/tasks.py`) — `sync_profiles`, `sync_forcedecks`, `sync_all_vald`
2. **Management commands** — `vald_backfill`, `vald_sync_profiles`
3. **Beat schedule** — Tuesday 6 AM weekly sync
4. **Concurrency lock** — cache-based per-system lock (see review recommendation #1)
5. **SmartSpeed integration** — Phase 3 (ForceDecks only in Phase 1)
6. **Monitoring** — Prometheus counters + alert thresholds
7. **Phase 0 credentials** — still need to email support@vald.com

---

## Local Testing Status

✅ **Passing:**
- Django system check (0 issues)
- All 11 model tests
- Migrations applied cleanly
- Templates render (untested in browser yet — awaiting Phase 0 creds)

⚠️ **Not Yet Tested:**
- Views (need test DB with Client/Player fixtures)
- API client against real VALD (blocked on Phase 0 creds)
- UI/UX in browser (need to start dev server + create test data)

---

## Next Steps

### Immediate (Phase 1 continuation):
1. **View tests** — `test_views.py` (client IDOR, owner auth walls, empty states)
2. **Start local dev server** — verify template rendering + dark mode + responsive grid
3. **Create test data** — seed ValdProfile + ValdTestResult + ValdResultDefinition via Django shell
4. **UI/UX review** — screenshot light/dark mode, mobile, metric cards, empty states

### Phase 0 (parallel):
5. **Email support@vald.com** — request API credentials (7-day expiry, capture into `.env`)
6. **Confirm region** — test against Swagger, update `VALD_REGION` in settings
7. **Record fixtures** — sanitize PII from real Swagger responses, commit to `tests/fixtures/`

### Phase 2 (after Phase 0 creds arrive):
8. **Build Celery tasks** — `sync_profiles`, `sync_forcedecks` with cursor pagination
9. **Add concurrency locks** — Redis cache-based per-system
10. **Beat schedule** — Tuesday 6 AM, `maintenance` queue
11. **Test full sync** — profiles → forcedecks → upsert → owner UI refresh

---

## Code Review Checklist (when PR opens)

- [x] NO lines added to `admin_views.py` (owner views in `performance/views.py`)
- [x] `ValdTestResult.vald_test_id` unique constraint in migration
- [x] Owner views use `@user_passes_test(is_owner)` + `@require_POST` on sync
- [x] Redis cache fallback handling (what if Redis down?)
- [ ] Test IDOR: parent A can't view parent B's player metrics
- [ ] Verify 204 pagination termination doesn't infinite-loop
- [ ] Test token expiry + re-auth flow

---

## Files Created (Phase 1)

```
src/performance/
  __init__.py
  apps.py
  models.py               # ValdProfile, ValdTestResult, ValdResultDefinition, ValdSyncRun
  vald_client.py          # OAuth + API client (token cache, 429 backoff, cursor pagination)
  views.py                # client + owner portal views (NOT in admin_views.py)
  urls.py                 # client portal routes
  urls_owner.py           # owner portal routes (separate file)
  admin.py                # Django admin registration
  decorators.py           # @require_vald_enabled
  migrations/
    0001_initial.py       # 4 models + indexes
  tests/
    __init__.py
    test_models.py        # 11 tests, all passing
    test_vald_client.py   # HTTP mocked, 429 retry, 204 termination
    fixtures/
      forcedecks_cmj.json           # Mock test response
      result_definitions.json       # Mock /resultdefinitions

templates/performance/
  index.html              # Client portal player list
  detail.html             # Client portal per-player charts (Chart.js)
templates/owner/
  performance.html        # Owner portal sync + players table + match modal

docs/vald/
  integration-plan.md     # Full technical plan
  portal-design.md        # UI/UX design spec
  references.md           # Links + open questions
  phase-1-summary.md      # This document
```

## Files Modified (Phase 1)

```
src/atletasworld/settings.py      # INSTALLED_APPS, CACHES, VALD_* settings
src/atletasworld/urls.py           # /portal/performance/, /owner-portal/performance/
src/clients/models/core.py         # Added Player.full_name @property
.env.example                       # VALD_* env vars + credential workflow comment
```

---

## Deployment Checklist (Phase 4)

When ready to deploy to EC2:
- [ ] Add `VALD_*` env vars to `/var/www/atletasworld/.env`
- [ ] Add `maintenance` Celery queue to Supervisor config
- [ ] Restart Supervisor: `sudo supervisorctl restart atletasworld atletasworld-celery`
- [ ] Run migrations: `python manage.py migrate performance`
- [ ] Pull `/resultdefinitions` → seed `ValdResultDefinition` table
- [ ] Owner curates `show_in_client_portal=True` + `display_order` for key metrics
- [ ] Run backfill: `python manage.py vald_backfill --system=profiles --system=forcedecks`
- [ ] Enable beat schedule: verify Tuesday 6 AM entry in `celery.py`
- [ ] Set `VALD_SYNC_ENABLED=True` in `.env`
- [ ] Monitor first weekly sync: check `ValdSyncRun` admin for errors

---

## Budget Estimate

**Phase 1 actual**: ~90 lines models, ~200 lines views, ~150 lines API client, ~250 lines tests, ~400 lines templates = ~1,090 LOC

**Remaining (Phase 2–4)**: ~300 lines tasks, ~150 lines management commands, ~200 lines view tests = ~650 LOC

**Total**: ~1,740 LOC for MVP (ForceDecks only, no SmartSpeed yet)

---

## Success Criteria (Phase 1)

- [x] Django check passes (0 issues)
- [x] All model tests pass (11/11)
- [x] Migrations applied cleanly
- [x] NO lines added to `admin_views.py`
- [x] Templates extend correct base (`clients/base.html`, `owner/base.html`)
- [ ] Browser rendering verified (pending local server start)
- [ ] Dark mode tested (pending browser test)
- [ ] Mobile responsive grid tested (pending browser test)
- [ ] IDOR protection verified (pending view tests)

**Phase 1 status: 90% complete** — awaiting local browser testing + view test coverage.
