# VALD Reference Links

- **VALD Applications** — https://valdperformance.com/applications
  Product/system overview (ForceDecks, SmartSpeed, ForceFrame, HumanTrak,
  NordBord, DynaMo). Useful for understanding what each system measures when
  scoping which metrics to surface in the portal.

## VALD Knowledge Base (API docs)
- How to integrate with VALD APIs — auth flow, region URLs, rate limits
- A guide to using the External ForceDecks API — `/tests`, `/resultdefinitions`, pagination
- (pending) External SmartSpeed API guide
- (pending) External Profiles API guide
- (pending) External Tenants API guide

## Internal
- `integration-plan.md` — data model, API client, sync strategy
- `portal-design.md` — client/owner portal UI spec
- `image.webp` — VALD dashboard screenshot (awaiting review in vision-enabled session)

## Open items (not yet in plan)

### Product / ops
- **Push to VALD, not just pull** — check the "Integrate your PMS/AMS with VALD Hub" KB article. If Profiles API supports POST, we could create athletes from our `Player` rows and skip name+birth_year matching entirely.
- **Assessment booking flow** — how does a player actually get on the force plate? Recurring slot? Coach workflow for "who's due this week"? Connects to the `bookings` app; not covered in plan.
- **Notifications** — "Results ready for [player]" when a sync lands new data. Codebase has email + push + SMS + notification models. Not wired in plan.
- **Commercial** — does APC already own ForceDecks/SmartSpeed hardware and a VALD Hub subscription, or is that a separate purchase ahead of this integration? Plan assumes data exists in VALD.

### Compliance / data lifecycle
- **Parental consent for minors' biometric data** — COPPA (<13). Consent flag/flow before surfacing metrics. Does `ClientWaiver` cover this, or need a new consent scope?
- **Data processing agreement with VALD** — they're a processor of minor athlete health data.
- **Deletion / right-to-forgotten** — player leaves: can we delete `ValdTestResult` rows + request VALD deletion? No cleanup path in plan.
- **Corrections** — coach edits a test in VALD Hub post-sync; does `modifiedFromUtc` re-pull it? Should (modified-keyed), but state explicitly and test it.

### Ops / resilience
- **Concurrency lock** — manual "Sync now" + scheduled Tuesday sync can overlap. Cache-based Celery lock per system, else duplicate `ValdSyncRun` rows and racing upserts.
- **Feature flag for UI** — `VALD_SYNC_ENABLED` gates the beat task; `/portal/performance/` should 404 the same way when off (design doc says 404 — confirm the view checks the flag, not just URL registration).
- **Monitoring thresholds** — plan says Prometheus counters; no alert threshold (e.g. "ValdSyncRun error rate > 50% over 2 weeks" → alert).

### Missing source docs (affects Phase 1/3 accuracy)
- External SmartSpeed API guide — endpoint shape inferred, not confirmed.
- External Profiles API guide — matching/pagination assumptions unverified.
- External Tenants API guide — `tenantId` vs `teamId` equivalence assumed.
