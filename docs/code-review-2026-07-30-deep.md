# Deep Code Review & Architecture Assessment — July 30, 2026

Follow-up to `docs/code-review-2026-07-22.md` (which focused on god-object
maintainability — all items now resolved). This pass is a **6-dimension deep
review**: data model & concurrency, query performance, security, architecture,
test quality, and infrastructure/ops. Method: parallel static inspection of
`src/`, config, CI, and git history.

**Overall verdict:** the application layer is in good health — money is modeled
correctly (all `DecimalField`), auth walls are uniform, Stripe signatures are
verified, and the recent refactor was real. The serious risk is **not in the
code the review was expected to find bugs in** — it's two systemic gaps:
**(1) no transaction/locking on booking & package mutations**, and
**(2) a live payments product on unbacked single-instance SQLite.**

---

## 🔴 Critical — fix first

### C1. No backup of the production database. Single EC2 + SQLite.
Prod runs SQLite at `/var/www/atletasworld/src/db.sqlite3`. There is **no backup
automation anywhere in the repo** — no cron, no S3 sync, no EBS-snapshot script,
no Litestream. If the instance or its EBS volume fails, **100% of customer,
booking, and payment-reconciliation data is permanently lost** — including the
`ClientPackage.stripe_subscription_id` rows that map live Stripe subscriptions to
accounts.

- **Today (1 hr):** cron on EC2 → `sqlite3 db.sqlite3 ".backup /tmp/db-$(date +%F-%H).sqlite3"` → `aws s3 cp` to a versioned bucket, every 15–60 min. Turns "total loss" into "≤1h RPO." Enable AWS Backup/DLM EBS snapshots as a second layer.
- **This month:** migrate to Postgres — `psycopg2-binary` is already in requirements and settings already branch on `postgresql`. RDS single-AZ (~$15–25/mo) or on-instance PG with `pg_dump` cron. Resolves C1 + the single-writer lock risk + the CI/prod engine mismatch (H-infra) in one move.

### C2. Deploy migrates the live DB with no pre-migrate backup and no rollback.
`deploy.yml` does `git reset --hard origin/main` → `migrate --noinput` straight
against prod, no backup step, no maintenance window. On SQLite, a migration that
fails partway (limited transactional DDL) can leave the schema half-applied and
unrecoverable. Combined with C1 this is the highest-probability path to an actual
outage.
- **Fix:** add a "backup DB → S3" step *before* migrate in `deploy.yml`. Cheap, immediate. Longer term: a documented rollback runbook.

### C3. Stripe webhooks are not idempotent → double package activation / double credits.
`payments/webhook_handlers.py` — no dedup on Stripe `event.id`. `_activate_package`
(line 238) unconditionally `ClientPackage.objects.create(...)`. Stripe retries on
any timeout/500, and `views.py:672-675` returns 500 whenever a downstream
(email/notification) step throws *after* the package is created — guaranteeing a
retry that re-creates it.
- Scenario: `payment_intent.succeeded` delivered twice → two `ClientPackage` rows → client gets double sessions; credits/Select grants re-applied.
- **Fix:** `StripeEvent` table with unique `event_id`; `get_or_create` at the top of `payments_webhook`, return 200 if seen. Additionally make `ClientPackage.stripe_payment_id` unique + `get_or_create` in `_activate_package`. Wrap each handler body in `transaction.atomic()`.

---

## 🟠 High — correctness (concurrency)

Four agents independently converged here: **booking creation and counter
mutations are read-modify-write with no `transaction.atomic` / `select_for_update`.**
`grep` confirms zero locking in `booking_service.py` and `api.py`. (Notably,
`DiscountCode` redemption and `FieldRentalSlot` booking *do* lock correctly — the
pattern exists in the codebase, it's just not applied to the core booking paths.)

### H1. `ClientPackage.sessions_remaining` decrement race → negative balance / free sessions.
`bookings/models.py:532` (`use_package`), `clients/models/packages.py:125`
(`use_session`), `clients/views/bookings.py:657,840`. Check `<= 0` then
`-= 1; save()` on a stale value. Two concurrent bookings against a 1-session
package both pass and both decrement → `-1`, two confirmed bookings for one paid
session. Plain `IntegerField`, no check constraint, so negatives persist.
- **Fix:** conditional `F()` update — `ClientPackage.objects.filter(pk=..., sessions_remaining__gt=0).update(sessions_remaining=F('sessions_remaining')-1)`, treat 0-rows-updated as "none left." Add `CheckConstraint(sessions_remaining__gte=0)`.

### H2. Block/slot participant counters race → oversell.
`booking_service.py:139-155,876`, `bookings/models.py:407,442,463,532`. Read
`is_available`, later `current_participants += 1; save()`. Two clients booking the
last spot both succeed → `current = max+1`. `unique_together` protects the slot
*definition*, nothing for counts.
- **Fix:** `select_for_update()` the block/slot inside `atomic()`, increment via `F()+1`, re-check capacity after locking.

### H3. Aborted `schedule_block` bookings leave `current_participants` permanently inflated.
`booking_service.py:152-155` increments the counter **before** the
`requires_package` (`:308`), linked-package (`:329`), and special-event (`:399`)
gates that `booking.delete()` and raise. Only the Select path rolls back. Once the
phantom count hits `max_participants`, the block flips to `status='booked'` and
becomes **unbookable by everyone** — a repeatable denial-of-booking.
- **Fix:** increment only after all validation passes (or roll back on every abort path, as the Select branch does).

### H4. `_activate_package` and multi-package activation not transactional.
`webhook_handlers.py:238-319`. Package create → discount finalize → credits →
6 Select credits → referral activation, all un-wrapped. Any throw → 500 → Stripe
retry re-runs everything (compounds C3). **Fix:** wrap in `atomic()` + the C3 idempotency key.

---

## 🟠 High — security (coach portal IDOR)

### S1. Coach can message ANY player's parent.
`coaches/views/notifications.py:46` — `Player.objects.filter(id__in=player_ids)`
with no coach scope. Any coach can POST arbitrary player IDs and email/SMS/push
those parents. Horizontal-privilege + spam/impersonation vector.
- **Fix:** `Player.objects.filter(id__in=player_ids, bookings__coach=coach).distinct()` — the sibling `my_players` view already does exactly this.

### S2. Coach can view/publish/add-guests to ANY Select game.
`coaches/views/select_games.py:83` — `get_object_or_404(SelectGame, pk=game_id)`,
no ownership check. A coach can `publish` any draft (triggers fan-out RSVP emails
to Select members), `add_guest` with any client, and read every team's roster
(`all_clients` lists all clients).
- **Fix:** scope by `select_team__coach=coach`; gate `publish` behind ownership.

*(Client-portal IDOR, owner auth walls, webhook signatures, uploads, mass
assignment, secrets — all verified clean.)*

---

## 🟡 Medium

### Performance
- **P1. Unbounded N+1 on the client bookings list.** `clients/views/bookings.py:43` calls `_booking_location(b)` per booking → one `ScheduleBlock.objects.get()` each, no page limit. A client with 200 past bookings = ~200 extra queries. **Fix:** batch-load blocks into a dict keyed by `(coach_id, date, time)`; paginate `past_bookings`.
- **P2. `owner_players` export: per-player package query on an unbounded export.** `players.py:53` calls `.filter()` inside the loop, ignoring the prefetch. **Fix:** `Prefetch(..., to_attr='active_pkgs')`.
- **P3. `owner_coaches` writes on a GET** — `ReferralService.get_or_create_code` per coach creates rows during a list render. **Fix:** bulk-fetch codes; create lazily elsewhere.
- **P4. Missing pagination** on `owner_field_slots`, `owner_contacts`, `owner_notifications`, `owner_credits`, and Select client-picker dropdowns (`Client.objects.all()` into a widget). Fine at ~18 subs, degrades with growth. `owner_bookings`/`owner_clients` are correctly paginated.
- **P5. SQLite write-lock hazards:** `cancel_block` issues Stripe refunds (network I/O) *inside* a save loop holding the write path → `database is locked` under concurrency. Several loops use per-row `.save()` instead of `bulk_update`. Set `OPTIONS={'timeout':20,'init_command':'PRAGMA journal_mode=WAL;'}`; move refunds out of the write loop / into Celery.
- **P6. Context processors hit the DB every request** — `pending_field_rentals` runs 2 queries per owner request, `user_roles` 1 per authed request. Cache with short TTL.

### Money / data
- **M1. `calculate_upgrade_cost` uses `float()` on money** (`packages.py:179`) — the one place money leaves `Decimal`. Feeds upgrade pricing shown/charged to clients. **Fix:** stay in `Decimal`, `.quantize`.
- **M2. Split-charge integer division drops cents** (`webhook_handlers.py:75,802`) — `amount // len(ids)`; $100/3 stores $99.99 total. Breaks reconciliation. **Fix:** distribute remainder, or store true per-booking price from metadata.
- **M3. Refunds not tracked as amounts** — `_handle_refund` only flips status to `'refunded'`; partial == full, no `amount_refunded` stored, multiple partials untracked. **Fix:** store `amount_refunded` Decimal; distinguish partial/full.
- **M4. Missing indexes on Stripe lookup columns** — `ClientPackage.stripe_subscription_id`/`stripe_payment_id` have no `db_index`; every renewal/cancel webhook full-scans on SQLite. **Fix:** `db_index=True`.

### Architecture
- **A1. Booking-creation logic lives in 3 places** — `booking_service.create_booking`, `clients/views/bookings.py::create_booking_direct` (~210L, separate rules), and inline in `owner_views/bookings.py`. Package selection, rule enforcement, discounts, and notifications are re-implemented with subtly different logic. **This is the core architectural debt** — pricing bugs must be fixed 2–3×. Make `booking_service` the single home; have the other paths call shared functions. (This is also the natural place to add the H1–H3 transaction boundary.)
- **A2. `create_booking` is a 480-line procedure** with ~7 early-return dicts duplicating a 9-key response shape. Extract `_resolve_amount_due`, `_apply_sibling_discount`, `_apply_promo`, `_booking_response`.
- **A3. Notification system bypassed at ~half the call sites** — `queue_grouped_notification` is the intended single entry point, but 9 files build emails directly and `send_booking_reminders` reconstructs the whole email, bypassing `NotificationService.send_email` which owns **suppression-list + unsubscribe injection**. Bypassing it risks emailing opted-out users (compliance). Funnel all sends through it; delete the dead per-event `send_*` methods.
- **A4. `bookings ↔ clients` circular dependency** held together by load-bearing lazy imports inside functions; `payments → clients` 56×. Define thin service interfaces instead of deep model imports.

### Infra
- **I1. No error tracking (Sentry) / log aggregation.** Logs are local files, lost with the instance. `/metrics` claims nginx IP-restriction but the *versioned* nginx config has none — either drift or public exposure. Add Sentry (env-flagged), version the `/metrics` allow/deny, point homelab Prometheus (CT301) at it.
- **I2. CI tests on Postgres, prod on SQLite** — engine mismatch; lock contention is never exercised by tests. Resolved by the Postgres migration (C1).
- **I3. Self-hosted runner on prod with passwordless sudo** — repo/Action compromise = RCE as `ubuntu` on the box holding the live DB + Stripe key. `EC2_SSH_KEY`/`EC2_HOST` secrets are documented but unused. Prefer SSH-push from a hosted runner + branch protection + SHA-pinned actions.
- **I4. No post-deploy smoke test** — deploy reports success even if every request 500s. Add `curl -fsS https://atletasperformancecenter.com/` as the last step.

### Tests
- **T1. Concurrency paths have no tests** (and no protection — see H1–H3). Add `TransactionTestCase` firing two concurrent create-direct posts at a 1-spot block / 1-session package; assert exactly one booking. *Write after the locking fix.*
- **T2. Webhook idempotency untested** (and unimplemented — C3). POST the same `multi_package` intent twice, assert one `ClientPackage`. Will fail today → confirms the bug.
- **T3. Coach portal view layer (11 modules) has zero view tests** — assessments, attendance, schedule CRUD, select-game publish, coach refund flow. Mirror the owner-portal test structure (auth wall + one behavioral assert each).
- **T4. Refund amount not asserted** — `test_issue_refund_success` only checks Stripe was called, not the cents. Assert `call_args` amount for a partial `$X.XX`.
- **T5. `booking_service.create` (523L) not directly tested** — only transitively. Add unit tests for Select branches + rollback path.
- **T6. Marker inconsistency** — `test_booking_validation.py` and `tests_select.py` have no unit/integration markers, so `pytest -m unit` silently skips them; `slow` is declared but never applied.

---

## 🟢 Low / cleanup
- Root-level git-tracked cruft: `check_groups.py`, `reset_owner.py`, `show_dashboard.py`, `show_mobile_dashboard.py`, `deep-*-snapshot.md`, `programs-snapshot.md` — `git rm` them. Gitignore `graphify-out-before/`. Delete stale root `db.sqlite3` (dated May 16).
- `OLLAMA_BASE_URL` default is a hardcoded LAN IP (`settings.py:344`) — change default to `''`.
- Empty DRF stubs `analytics/urls.py`, `reviews/urls.py` wired into `/api/` — dead routes; delete.
- `Booking.clean()` double-booking guard is dead logic (`models.py:559`, always-false condition, and `clean()` is never called).
- No login brute-force protection — add allauth `ACCOUNT_RATE_LIMITS = {'login_failed': '5/5m'}`.
- Reschedule POST doesn't re-validate session-type match (`clients/views/bookings.py:110`); package reschedule appears to net +1 session (accounting leak — verify).
- `security-scan.yml` steps all use `|| true` — informational only, never fail the build. Consider failing on high-severity.

---

## Recommended sequencing

**This week (mostly hours, highest leverage):**
1. C1 — SQLite→S3 backup cron + EBS snapshots
2. C2 — backup step before migrate in `deploy.yml`
3. C3/H4 — webhook idempotency (`StripeEvent` table) + wrap activations in `atomic()`
4. S1, S2 — coach IDOR queryset scoping (one line each)
5. I4 — post-deploy smoke test; I1 — add Sentry

**This month:**
6. H1–H3 — transaction + `select_for_update`/`F()` on booking & session paths, with tests (T1)
7. A1 — unify booking creation into `booking_service` (do the transaction work here)
8. Migrate prod SQLite → Postgres (resolves C1 single-writer, I2 engine mismatch)
9. A3 — funnel all email through `NotificationService` (opt-out compliance)
10. P1–P4 — N+1 fixes + pagination; T2–T5 — fill test gaps

**Biggest single risk:** C1 — a live payments product on unbacked single-instance
SQLite. The backup cron is a one-hour task and the highest-leverage change available.
