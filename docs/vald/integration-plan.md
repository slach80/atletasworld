# VALD Performance API Integration — Plan

Integration of VALD's external APIs to sync weekly force-plate (ForceDecks) and
field-drill (SmartSpeed) assessment data into atletasworld, surfaced in the
client portal so parents/players can track stats and progress over time.

**VALD API facts** are taken verbatim from VALD's official knowledge base
("How to integrate with VALD APIs"). The OAuth client_credentials flow
described there (auth.prd.vald.com/oauth/token, audience=vald-api-external) is
the current one following the March 2026 auth changes.

---

## Goal

Build a new `performance` Django app that authenticates to VALD's external
APIs, syncs athlete profiles + ForceDecks + SmartSpeed results on a weekly
Celery schedule, stores them idempotently, and exposes a parent-facing
progress view in the client portal — without growing the `admin_views.py`
monolith or the `analytics` app.

---

## Plan

### 1. New app: `performance`
Name `performance` (not `vald`) — the domain concept is "athlete performance
metrics"; VALD is one source among future providers. Decouples vendor from
domain.

Layout mirrors `payments/`:
```
src/performance/
  __init__.py
  apps.py
  models.py            # ValdProfile, ValdTestResult, ValdSyncRun
  vald_client.py       # thin API client (mirrors payments/stripe_utils.py)
  tasks.py             # Celery sync jobs
  urls.py
  views.py             # client-portal + owner-portal views
  admin.py
  tests/
    test_vald_client.py
    test_models.py
    test_sync_tasks.py
    fixtures/          # recorded VALD API responses
  management/commands/
    vald_backfill.py   # one-off historical pull
    vald_sync_profiles.py
```
Add `'performance'` to `INSTALLED_APPS`. Register URLs in `atletasworld/urls.py`:
```python
path('portal/performance/', include('performance.urls')),
path('owner-portal/performance/', include('performance.urls.owner')),  # see §7
```
To keep owner routes out of `admin_views.py`, the owner endpoints live in
`performance/views.py` under a separate URL module (`performance/urls_owner.py`)
included at `/owner-portal/performance/`.

### 2. Data model (`performance/models.py`)

**`ValdProfile`** — links a `Player` to a VALD athlete profile.
```python
class ValdProfile(models.Model):
    player = models.OneToOneField('clients.Player', on_delete=models.CASCADE,
                                  related_name='vald_profile')
    vald_profile_id = models.CharField(max_length=64, unique=True)
    vald_tenant_id = models.CharField(max_length=64, db_index=True)
    matched_at = models.DateTimeField(auto_now=True)
    match_method = models.CharField(max_length=20, default='manual',
        help_text="manual | auto_name_dob | vald_invite")
    is_active = models.BooleanField(default=True)
```
**Match key:** store `vald_profile_id` on `ValdProfile` (OneToOne→Player), NOT
on the `Player` model itself — keeps vendor data in the vendor app. Auto-match
by `first_name + last_name + birth_year` (Player has all three); surface
unmatched profiles in owner UI for manual linking. Avoid DOB-day precision
(Player only has `birth_year`) to reduce false negatives.

**`ValdTestResult`** — system-agnostic, one row per VALD test.
```python
class ValdTestResult(models.Model):
    SYSTEM_CHOICES = [
        ('forcedecks', 'ForceDecks'),
        ('smartspeed', 'SmartSpeed'),
        ('dynamo', 'DynaMo'), ('forceframe', 'ForceFrame'),
        ('humantrak', 'HumanTrak'), ('nordbord', 'NordBord'),
    ]
    vald_test_id = models.CharField(max_length=64, unique=True)  # idempotency key
    profile = models.ForeignKey(ValdProfile, on_delete=models.CASCADE,
                                related_name='results')
    system = models.CharField(max_length=20, choices=SYSTEM_CHOICES, db_index=True)
    test_type = models.CharField(max_length=80)   # e.g. "CMJ", "Sprint_10m"
    test_date = models.DateTimeField(db_index=True)
    raw_payload = models.JSONField()              # full VALD response, for re-derivation
    # Flattened, queryable metric columns (denormalized from raw_payload):
    metrics = models.JSONField(default=dict)      # {"<resultId>": value, ...}
    week_key = models.CharField(max_length=10, db_index=True)  # "2026-W29"
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['profile', 'test_date']),
            models.Index(fields=['system', 'test_type', 'test_date']),
            models.UniqueConstraint(fields=['vald_test_id'], name='uniq_vald_test'),
        ]
```
`metrics` is keyed by VALD `resultId` (not a hardcoded slug) so the UI can
join to `ValdResultDefinition` for the human label, unit, and trend direction.

**`ValdResultDefinition`** — metric metadata, pulled once from
`/resultdefinitions` (VALD: "do not change frequently"). Drives UI labels AND
the progress-chart polarity (no hardcoded "lower = better").
```python
class ValdResultDefinition(models.Model):
    result_id = models.CharField(max_length=64, primary_key=True)  # VALD resultId
    system = models.CharField(max_length=20, db_index=True)        # 'forcedecks' | 'smartspeed' | ...
    name = models.CharField(max_length=200)          # human-readable metric name
    unit = models.CharField(max_length=40, blank=True)  # "cm", "s", "N/kg", ...
    trend_direction = models.CharField(max_length=10, blank=True)  # 'increasing' | 'decreasing' | ''
    # trend_direction: 'increasing' => higher is better; 'decreasing' => lower is better
    display_order = models.IntegerField(default=0)   # owner-curated chart order
    show_in_client_portal = models.BooleanField(default=False)  # gated per metric
    raw_payload = models.JSONField(default=dict)
    refreshed_at = models.DateTimeField(auto_now=True)
```
Refresh strategy (per VALD docs): pull `/resultdefinitions` once at setup; pull
the single `/resultdefinition/{resultId}` on-demand only when a test arrives
with an unfamiliar `resultId` not in this table.

**Generic-vs-specific trade-off:** chose ONE generic `ValdTestResult` with a
`system` discriminator + `raw_payload` JSON + flattened `metrics` JSON. Rationale:
- VALD has 8 systems; a table per system = 8 models, 8 sync paths, 8 displays.
- Metric names differ wildly per system (jump height vs sprint time) — a fixed
  columnar schema per system is brittle when VALD adds metrics.
- `raw_payload` preserves everything; `metrics` flattens the handful we chart.
- If a system later needs SQL-indexable columns (e.g. for leaderboard ranking),
  add a small system-specific table keyed off `ValdTestResult` then — don't
  pre-build it.

**`ValdSyncRun`** — incremental-pull cursor + audit.
```python
class ValdSyncRun(models.Model):
    STATUS_CHOICES = [('running','Running'),('ok','OK'),('error','Error')]
    system = models.CharField(max_length=20)      # 'profiles' | 'forcedecks' | ...
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, default='running')
    records_synced = models.IntegerField(default=0)
    last_synced_at = models.DateTimeField(null=True, blank=True)  # cursor for incremental pulls
    error = models.TextField(blank=True)
    class Meta: ordering = ['-started_at']
```
The incremental-pull cursor = `last_synced_at` on the latest successful
`ValdSyncRun` for each system. Query VALD with "updated since" param against
this timestamp. No separate cursor table needed.

**Weekly assessment eligibility** is derived, not stored: a Player is eligible
for week W if they have an active `ClientPackage` with sessions remaining OR
are on a `select_teams` roster (existing model fields). Compute in the view.
The `week_key` on `ValdTestResult` ties a result to a week for the progress chart.

### 3. API client layer (`performance/vald_client.py`)

Mirror `payments/stripe_utils.py` — a thin, stateless module of functions
(not a heavy SDK). Uses `requests` (already a dependency).

**Token caching** — Django cache backed by Redis. Add a cache backend in
`settings.py` (project currently has none — only `CELERY_BROKER_URL`):
```python
CACHES = {
    'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'},
    'vald': {'BACKEND': 'django.core.cache.backends.redis.RedisCache',
             'LOCATION': env('REDIS_URL', default='redis://localhost:6379/0')},
}
```
Token stored under key `vald:access_token` with timeout = `expires_in - 60s`.
```python
def get_vald_token():
    cache_key = 'vald:access_token'
    token = caches['vald'].get(cache_key)
    if token:
        return token
    resp = requests.post(
        f'{settings.VALD_AUTH_URL}/oauth/token',
        data={'grant_type': 'client_credentials',
              'client_id': settings.VALD_CLIENT_ID,
              'client_secret': settings.VALD_CLIENT_SECRET,
              'audience': 'vald-api-external'},
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    caches['vald'].set(cache_key, data['access_token'],
                       timeout=data['expires_in'] - 60)
    return data['access_token']
```
Redis (not module-level global) because Celery workers are separate processes —
module-level cache would re-auth per worker and hit the auth rate limit.

**Base URLs — per-system-per-region.** Each VALD system has its own host,
region-embedded. ForceDecks (confirmed by VALD's External ForceDecks API guide):
| Region | Base |
|--------|------|
| US East | `https://prd-use-api-extforcedecks.valdperformance.com` |
| AUS East | `https://prd-aue-api-extforcedecks.valdperformance.com` |
| EU West | `https://prd-euw-api-extforcedecks.valdperformance.com` |
SmartSpeed/Profiles/Tenants follow the same `prd-<region>-api-<system>.valdperformance.com`
shape. Store a dict in settings keyed by `(system, region)` rather than a
single `VALD_API_BASE`; expose `vald_base_url(system)`:
```python
VALD_REGION = env('VALD_REGION', default='use')   # 'use' | 'aue' | 'euw'
VALD_API_BASES = {
    ('forcedecks', 'use'): 'https://prd-use-api-extforcedecks.valdperformance.com',
    ('forcedecks', 'aue'): 'https://prd-aue-api-extforcedecks.valdperformance.com',
    ('forcedecks', 'euw'): 'https://prd-euw-api-extforcedecks.valdperformance.com',
    # smartspeed / profiles / tenants added in Phase 1/3 once Swagger-confirmed
}
```

**ForceDecks endpoints (confirmed):**
- `GET /tests?tenantId={}&modifiedFromUtc={YYYY-MM-DDThh:mm:ss.fffZ}&profileId={?}`
  — collection of tests. `tenantId` and `modifiedFromUtc` are **required**.
  Response ordered by `modifiedDateUtc`.
- `GET /v2019q3/teams/{teamId}/tests/{testId}/trials` — reps/trials per test
  (versioned path segment `v2019q3`; `/tests` itself is unversioned).
- `GET /v2019q3/teams/{teamId}/tests/{testId}/recording?includeSampleData=`
  — raw force curve. **Requires separate permission from support@vald.com.**
  Out of MVP scope (we chart results, not raw curves).
- `GET /resultdefinitions` — all metric definitions (pull once, cache).
- `GET /resultdefinition/{resultId}` — single definition (on-demand refresh).

`tenantId` (query param on `/tests`) and `teamId` (path param on `/trials`,
`/recording`) are the same tenant identifier from the Tenants API.

**Client functions:**
```python
def vald_get(system, path, params=None): ...     # resolves base URL, injects Bearer
def list_tenants(): ...                          # External Tenants API
def list_profiles(since=None): ...               # External Profiles API
def list_forcedecks_tests(tenant_id, modified_from_utc, profile_id=None): ...
def list_forcedecks_trials(team_id, test_id): ...
def list_result_definitions(system='forcedecks'): ...
def get_result_definition(result_id, system='forcedecks'): ...
```
- **Pagination (ForceDecks `/tests`):** cursor-based, NOT offset/skip. Feed
  the last test's `modifiedDateUtc` back as the next request's `modifiedFromUtc`;
  a **`204 No Content` response signals the end** (not an empty array). Loop
  until 204. This same mechanism serves both backfill (start from a far-past
  date, e.g. `2000-01-01T00:00:00.000Z`) and incremental sync (start from
  `ValdSyncRun.cursor('forcedecks')`). `modifiedFromUtc` is mandatory even on
  the first request.
- **429 backoff:** exponential backoff (1s, 2s, 4s, max 3 retries) on
  `429 Too Many Requests`; respect `Retry-After` header if present. Log every
  retry at WARNING.
- **Errors:** never bare `except: pass` (per code review #4). Catch
  `requests.RequestException`, `logger.exception(...)`, write `error` to
  `ValdSyncRun`, mark status='error', re-raise so Celery records the failure.

### 4. Sync strategy (`performance/tasks.py`)

**Bootstrap (one-off):** `manage.py vald_backfill --system=profiles|forcedecks|smartspeed [--since=YYYY-MM-DD]`
 — management command, not a beat task. Pulls historical data, upserts by
`vald_test_id`. Run once at go-live.

**Weekly incremental (beat):** add to `atletasworld/celery.py`:
```python
'vald-weekly-sync': {
    'task': 'performance.tasks.sync_all_vald',
    'schedule': crontab(hour=6, minute=0, day_of_week=2),  # Tuesdays 6 AM
    'options': {'queue': 'maintenance'},
},
```
Tuesday 6 AM because assessments happen during the week; Monday is the
existing reminder batch (don't pile on). Queue `maintenance` (new — add to
Supervisor config on EC2) to isolate from notification tasks.

`sync_all_vald` chains: profiles → forcedecks → smartspeed, each in its own
`@shared_task` so a failure in one doesn't block the others:
```python
@shared_task
def sync_all_vald():
    chain(sync_profiles.s(), sync_forcedecks.s(), sync_smartspeed.s()).apply_async()

@shared_task(bind=True)
def sync_forcedecks(self):
    run = ValdSyncRun.objects.create(system='forcedecks')
    try:
        since = ValdSyncRun.cursor('forcedecks')
        results = vald_client.list_forcedecks_tests(settings.VALD_TENANT_ID,
                                                    modified_from_utc=since)
        upserted = _upsert_results(results, system='forcedecks')
        run.finish_ok(upserted)
    except Exception as e:
        logger.exception('ForceDecks sync failed')
        run.finish_error(str(e))
        raise
```
**Idempotency:** `_upsert_results` uses `update_or_create(vald_test_id=...)`.
Re-running the backfill or a duplicate weekly pull produces no duplicates.
**Order:** profiles FIRST (tests FK to `ValdProfile`); a test for an unmatched
profile is logged and skipped (not failed) so the bulk pull completes.

### 5. Client portal UI

**Routes** (`performance/urls.py`):
```python
path('', views.player_performance, name='performance'),
path('player/<int:player_id>/', views.player_detail, name='performance_detail'),
```
**Views** (`performance/views.py`):
```python
@login_required
def player_performance(request):
    # list player's children with latest test summary + sparkline
    players = Player.objects.filter(client__user=request.user, is_active=True)

@login_required
def player_detail(request, player_id):
    player = get_object_or_404(Player, pk=player_id, client__user=request.user)
    # permission: only the player's own parent (client__user=request.user)
    results = player.vald_profile.results.all().order_by('test_date')
```
Permission is the existing pattern — `client__user=request.user` filter
(guarantees a parent only sees their own children; no IDOR).

**Templates** (`templates/performance/`):
- `performance/index.html` — player cards with latest assessment date + 3
  headline metrics.
- `performance/detail.html` — per-player progress charts (Chart.js, already
  in the Bootstrap stack) with:
  - **ForceDecks:** CMJ jump height, reactive strength index, peak force
    (N/kg), eccentric/concentric ratio. Labels + units pulled from
    `ValdResultDefinition` (e.g. "Jump Height / cm"), not hardcoded.
  - **SmartSpeed:** 10m / 20m / 30m sprint time, 505 agility, max velocity.
    Same definition-driven labels.
  - Each metric: line chart over `test_date`, with `week_key` on x-axis and a
    "latest vs previous" delta badge. **Polarity comes from
    `ValdResultDefinition.trend_direction`** — `increasing` ⇒ higher is better
    (green ↑), `decreasing` ⇒ lower is better (green ↓). No per-metric
    hardcoded polarity. Owner curates which definitions appear in the client
    portal via `show_in_client_portal` + `display_order`.
  - "Last assessed: <date>" and "Next eligible: week of <Mon>".

**Eligibility banner:** compute from existing `ClientPackage.sessions_remaining`
or `select_teams` membership — "✓ Eligible this week" / "Assessment included
with your Select membership".

### 6. Settings & env additions

`atletasworld/settings.py` (after the TWILIO block ~L289):
```python
# ── VALD Performance API ──
VALD_CLIENT_ID = env('VALD_CLIENT_ID', default='')
VALD_CLIENT_SECRET = env('VALD_CLIENT_SECRET', default='')
VALD_TENANT_ID = env('VALD_TENANT_ID', default='')
VALD_REGION = env('VALD_REGION', default='use')   # 'use' | 'aue' | 'euw'
VALD_AUTH_URL = env('VALD_AUTH_URL', default='https://auth.prd.vald.com')
VALD_API_BASES = {
    # (system, region) → host; region-locked per VALD docs.
    ('forcedecks', 'use'): 'https://prd-use-api-extforcedecks.valdperformance.com',
    ('forcedecks', 'aue'): 'https://prd-aue-api-extforcedecks.valdperformance.com',
    ('forcedecks', 'euw'): 'https://prd-euw-api-extforcedecks.valdperformance.com',
    # smartspeed / profiles / tenants hosts added in Phase 1/3 once Swagger-confirmed
}
VALD_SYNC_ENABLED = env.bool('VALD_SYNC_ENABLED', default=False)
```
`VALD_SYNC_ENABLED` gates the beat task (mirrors `CELERY_ENABLED` /
`SMS_ENABLED` pattern) so staging doesn't hit VALD.

Update repo-root `.env.example` with the same keys + a comment block noting
the credential-acquisition workflow (email support@vald.com, 7-day link expiry,
sign API License Agreement if third party).

### 7. Owner-portal visibility

Owner sees all players' metrics. Per code review #1, do **NOT** add views to
`admin_views.py`. Put them in `performance/views.py` with the same
`@user_passes_test(is_owner)` guard (import `is_owner` from
`atletasworld.admin_views`), routed via a separate
`performance/urls_owner.py` included at `/owner-portal/performance/`:
```python
# performance/urls_owner.py
path('', views.owner_performance, name='owner_performance'),
path('player/<int:player_id>/', views.owner_player_detail, name='owner_performance_detail'),
path('sync/', views.owner_trigger_sync, name='owner_vald_sync'),  # POST, manual re-sync
path('match/', views.owner_match_profile, name='owner_vald_match'),  # manual VALD↔Player link
```
Owner UI: table of players → latest metrics + a "Match VALD profile" action
for unmatched athletes + a "Sync now" button (dispatches `sync_all_vald`).

### 8. Testing strategy

All tests mock VALD HTTP — never hit the real API. Use `responses` or
`requests_mock` (add one to requirements; `responses` pairs with `requests`).
- `test_vald_client.py` — token fetch + cache hit (second call no HTTP), 429
  retry/backoff, pagination loop, region URL.
- `test_models.py` — `ValdTestResult` upsert idempotency (same `vald_test_id`
  updates, doesn't duplicate); `ValdSyncRun.cursor()` returns latest OK
  timestamp; `week_key` derivation.
- `test_sync_tasks.py` — `_upsert_results` with a recorded fixture; a test
  result for an unmatched profile is skipped not failed; `sync_forcedecks`
  marks `ValdSyncRun` error on exception and re-raises.
- `test_views.py` — parent sees only their own player (404 on someone else's
  `player_id`); owner sees all; sync endpoint owner-only + POST-only.
- **Fixtures:** record real Swagger responses during Phase 0 and commit as
  JSON (sanitize any PII) — `performance/tests/fixtures/forcedecks_cmj.json`
  etc. These double as living schema docs until the Swagger schema is stable.
- Mark VALD tests `@pytest.mark.integration` per the existing `pytest.ini`
  marker convention so `pytest -m unit` stays fast.

### 9. Phased rollout

| Phase | Scope | Exit criteria |
|-------|-------|---------------|
| **0 — Bootstrap** | Email support@vald.com with org ID; receive creds; identify region via Swagger; `GET /tenants` → confirm `VALD_TENANT_ID`; record fixtures. | `.env` populated; `list_tenants()` returns our tenant; fixtures committed. |
| **1 — Profiles** | App scaffold + models + `vald_client` + `sync_profiles` + owner match UI. | `ValdProfile` rows for all active players; manual match screen works. |
| **2 — ForceDecks** | Pull `/resultdefinitions` → seed `ValdResultDefinition`; `sync_forcedecks` (cursor pagination on `modifiedFromUtc`, stop on 204); backfill cmd; owner curates `show_in_client_portal`; client portal `detail.html` charts. | Parent sees jump metrics with ≥1 historical point; labels/units/polarity from definitions. |
| **3 — SmartSpeed** | `sync_smartspeed` + sprint/agility charts. | Parent sees sprint metrics alongside ForceDecks. |
| **4 — Automation** | Beat schedule live + `VALD_SYNC_ENABLED=True` on EC2 + `maintenance` queue in Supervisor + monitoring (Prometheus counters on sync runs/errors). | Weekly sync runs unattended; alerting on failed runs. |

Phase 0 is the long pole — credential approval is human-mediated (support
email + possible License Agreement). Start it immediately, parallel to Phase 1
scaffolding (models/client can be built with fixtures before creds arrive).

### 10. Risks & open questions

- **Credential lead time.** VALD approval is email-based, link expires in 7
  days, third parties must sign an API License Agreement. APC is the org owner
  (not third party) so no agreement, but the 7-day expiry means creds must be
  captured into `.env` promptly. **Action:** file the support request in Phase 0.
- **Region unknown.** Tenant data is region-locked; we don't know our region
  until VALD confirms. `VALD_REGION` + `VALD_API_BASES` make the host a config
  value, so no code change when the region is confirmed — but a wrong region
  yields empty results with no error. Confirm via Swagger before Phase 1.
- **Athlete matching ambiguity.** `first_name + last_name + birth_year` can
  collide (two "Alex Smith, born 2012"). Mitigation: auto-match only when
  unique; ambiguous matches flagged for owner manual resolution. No destructive
  auto-link.
- **Rate-limit volume unknown.** VALD publishes no numbers; we learn them from
  the Swagger schema / 429s. Design assumes conservative polling (weekly, not
  real-time). If backfill hits limits, throttle the backfill command with
  `--sleep` between pages.
- **March 2026 auth changes.** The OAuth flow in this plan is the *current*
  one per the KB article. If VALD rotates again, only `get_vald_token()`
  changes — the client surface is insulated.
- **PII / minor athlete health data.** Force-plate metrics on minors are
  sensitive. Mitigations: `raw_payload` is admin-only (never sent to client
  templates); client view shows derived labels only; add a privacy note to the
  performance page; ensure the EC2 DB backup scope includes this data under the
  existing retention posture; do not log `raw_payload` contents.
- **`admin_views.py` discipline.** This plan adds zero lines to it. Enforce in
  review: any owner-side VALD view goes in `performance/views.py`.
- **New Celery queue.** `maintenance` queue needs a Supervisor worker on EC2
  or the beat task silently queues with no consumer. Add to the deploy
  checklist (CLAUDE.md "Services" section).
- **No webhook from VALD.** Unlike Stripe, VALD is pull-only (no inbound
  webhook) — sync is purely scheduled. No `csrf_exempt` endpoint needed.

---

## Files to Modify

- `src/atletasworld/settings.py` — add `VALD_*` env vars, `CACHES['vald']`
  Redis backend, `'performance'` to `INSTALLED_APPS`.
- `src/atletasworld/celery.py` — add `vald-weekly-sync` beat entry +
  `task_routes` entry for `performance.tasks.*` → `maintenance` queue.
- `src/atletasworld/urls.py` — add `include('performance.urls')` at
  `/portal/performance/` and `include('performance.urls_owner')` at
  `/owner-portal/performance/`.
- `.env.example` — add `VALD_*` block with credential-workflow comment.
- `.env` (EC2, not in git) — populate real creds in Phase 0.
- `CLAUDE.md` — note `maintenance` Celery queue in the Services section;
  add `performance` app to the Project Structure table.
- `requirements.txt` — add `responses` (test-time HTTP mocking).
- `scripts/server-setup.sh` — add `maintenance` Celery worker to Supervisor.

## New Files

- `src/performance/__init__.py`, `apps.py`, `admin.py`
- `src/performance/models.py` — `ValdProfile`, `ValdTestResult`, `ValdResultDefinition`, `ValdSyncRun`
- `src/performance/vald_client.py` — token cache + `list_forcedecks_tests` (cursor pagination, 204 termination), `list_forcedecks_trials`, `list_result_definitions`, `get_result_definition`
- `src/performance/tasks.py` — `sync_profiles`, `sync_forcedecks`,
  `sync_smartspeed`, `sync_all_vald` (chain)
- `src/performance/views.py` — `player_performance`, `player_detail`,
  `owner_performance`, `owner_player_detail`, `owner_trigger_sync`,
  `owner_match_profile`
- `src/performance/urls.py`, `src/performance/urls_owner.py`
- `src/performance/management/commands/vald_backfill.py`,
  `vald_sync_profiles.py`
- `src/performance/migrations/0001_initial.py` (+ profile-link + index
  migrations as the schema stabilizes)
- `src/performance/tests/test_vald_client.py`, `test_models.py`,
  `test_sync_tasks.py`, `test_views.py`
- `src/performance/tests/fixtures/*.json` — recorded VALD responses incl. `/tests`, `/resultdefinitions`
- `templates/performance/index.html`, `detail.html`,
  `owner/performance.html` (owner base is `owner/base.html`)
- `docs/vald-integration-plan.md` — this document

## Risks
See §10 above. The critical-path risk is Phase 0 credential acquisition
(human-mediated, 7-day expiry); start it before any code beyond scaffolding.

---

### Sources
- VALD Knowledge Base — *How to integrate with VALD APIs* (auth flow, region
  URLs, rate limits, bootstrap sequence, best practices).
- VALD Knowledge Base — *A guide to using the External ForceDecks API*
  (`/tests` required params, `modifiedFromUtc` cursor pagination, 204 termination,
  `/v2019q3/.../trials` + `/recording` versioned paths, `/resultdefinitions`,
  region base URLs: `prd-{use|aue|euw}-api-extforcedecks.valdperformance.com`).
- SmartSpeed / Profiles / Tenants endpoint shapes inferred from the parent
  integration guide; confirm against each system's Swagger page in Phase 0/1.
- Internal: `docs/code-review-2026-07-22.md` (code-quality guardrails).
- Upcoming VALD maintenance window: 14 Aug 2026 11:00 UTC — avoid go-live cutover
  on that date.
