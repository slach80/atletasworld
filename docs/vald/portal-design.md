# VALD Performance Portal — Design

Visual/UX design for the client-facing VALD metrics views. This doc complements
`docs/vald/integration-plan.md` (which covers data model, sync, API client).
**We are not reinventing the dashboard** — the performance pages extend the
existing client-portal design system already used by `player_assessments.html`.

> **Status: awaiting design assets.** The owner will provide VALD's current
> client-facing dashboard screenshots for review. Sections marked 🔻 ASSET
> REVIEW below will be finalized once those arrive. This document specifies
> the structural/functional design now so implementation can proceed; visual
> refinements (typography emphasis, color accents, chart styling) may shift
> after the asset review.

---

## 1. Design system (existing — do not change)

All performance pages inherit from `templates/clients/base.html`:

| Concern | Existing convention |
|---------|--------------------|
| Base template | `clients/base.html` (extends → `content`, `extra_scripts`, `extra_styles` blocks) |
| CSS | Tailwind via `/static/css/tailwind.min.css` |
| Fonts | `Archivo Condensed` (body), `Bilgen` (headings) — loaded in base |
| Color tokens | `primary` (dark slate), `secondary` / `accent` (lime `#D7FF00` / `#b8e000`), semantic red/green/blue/amber |
| Dark mode | `html.dark` class; toggled by `localStorage["apc-dark"]="1"` — base template handles automatically. All components must use the `html.dark .*` overrides already in base, not hardcoded colors. |
| Nav | `{% include "includes/client_nav.html" %}` — portal top nav |
| Charts | Chart.js (already used in `player_assessments.html`: radar + line charts via `<canvas>` + `new Chart(...)`) |
| Cards | `bg-white rounded-xl shadow-md p-6` (dark: auto via base overrides) |
| Page header | gradient `from-gray-700 to-primary rounded-2xl p-6 text-white` with player photo/initials + stat counters |
| Breadcrumb | `Dashboard > Players > [Name]'s …` chevron-separated, top of page |
| Responsive | Tailwind `sm:` / `lg:` breakpoints; mobile is first-class (existing `test_mobile_dark_mode.py`) |

**Rule:** no new CSS framework, no new font, no new chart library. Performance
pages must be visually indistinguishable from `player_assessments.html` to a
parent navigating between them.

---

## 2. Navigation entry point

The client dashboard (`templates/clients/dashboard.html`) currently shows a
player list where each row links to `clients:player_assessments` (coach
assessments). VALD metrics are a sibling concept — add a "Performance" link
beside the existing "Assessments" link on each player card, not a new top-level
nav item.

```
Dashboard → Players list → [Player card]
                              ├─ Assessments  (existing — coach ratings)
                              └─ Performance  (NEW — VALD force plate / field drills)
```

- URL: `/portal/performance/player/<player_id>/` (the detail page IS the main
  view; no separate index page needed for MVP — one player, one page).
- If a family has multiple players, the dashboard player list already handles
  the chooser; each player gets their own Performance link.
- Add a "Performance" quick-action tile to the dashboard top action row (the
  row with Book / Packages / Players / Bookings / Field Rental) only if Phase
  2 uptake warrants it. MVP: link from the player card only.

🔻 **ASSET REVIEW:** confirm whether VALD's dashboard uses a single-athlete
overview or a multi-athlete comparison view. If multi, we may add a
`/portal/performance/` index that lists all the family's players with latest
metrics side-by-side.

---

## 3. Page layout — `performance/detail.html`

Extends `clients/base.html`. Mirrors the `player_assessments.html` structure
exactly so the two pages feel like siblings.

### 3.1 Breadcrumb
```
Dashboard > Players > [Name]'s Performance
```
Same chevron markup as `player_assessments.html` line ~8.

### 3.2 Player header (reuse existing pattern)
Gradient `from-gray-700 to-primary` card with:
- Player photo (or initials fallback) — same `w-20 h-20 rounded-full` styling
- Name, age group, skill level, soccer club
- Right-side stat block — counters for:
  - **Total Assessments** (count of `ValdTestResult` rows)
  - **Last Assessed** (most recent `test_date`, formatted "M d, Y")
  - **Next Eligible** (derived from package/select-team eligibility — see
    integration plan §2)

### 3.3 Eligibility banner
Below the header, a single-line banner (existing `bg-green-50` / `bg-yellow-50`
alert pattern):
- ✓ "Eligible this week — assessment included with your Select membership"
- ✓ "Eligible this week — N sessions remaining on your package"
- ⚠ "No active package — contact us to book an assessment"

Logic lives in the view (`performance/views.py`), not the template.

### 3.4 Tab/section switcher (ForceDecks | SmartSpeed)
Two tabs or a segmented control at the top of the metrics area. Default:
ForceDecks (the primary use case per the owner). Each tab loads its own set of
metric cards + charts. No page reload — simple JS `data-tab` toggle that
shows/hides two `<section>` blocks (same pattern as existing portal tabs if
any; otherwise a minimal vanilla-JS toggle).

🔻 **ASSET REVIEW:** VALD may group metrics differently (by test session vs by
metric type). If their dashboard groups by session date with all metrics for
that date together, switch to a date-grouped accordion instead of metric-type
tabs. Decide after seeing their screenshots.

### 3.5 Metric card grid
Each metric = one card in a responsive grid (`grid-cols-1 md:grid-cols-2
lg:grid-cols-3 gap-6`). Card contents:
```
┌─────────────────────────────────┐
│ Jump Height                  cm │  ← name + unit from ValdResultDefinition
│                                 │
│        32.1                     │  ← latest value (large)
│   ↑ 2.3  vs last week           │  ← delta badge (green if trend_direction matched)
│                                 │
│  [tiny sparkline / line chart]  │  ← Chart.js mini, test_date on x
│                                 │
│  12 weeks • best 34.0           │  ← count + personal best
└─────────────────────────────────┘
```
- Only metrics with `ValdResultDefinition.show_in_client_portal=True` appear.
- Order by `display_order`.
- Delta polarity from `trend_direction`: `increasing` → green ↑ / red ↓;
  `decreasing` → green ↓ / red ↑ (sprint time: lower is better).
- Personal best = `MAX`/`MIN` of all values depending on `trend_direction`.

### 3.6 Full progress chart (per metric, on click)
Clicking a metric card expands (or links to an anchor) a full-width line chart:
- Chart.js `type: 'line'`, `test_date` on x-axis, value on y
- Tooltip shows date + value + week_key
- Optional: horizontal line at personal best
- Same dark-mode-aware colors as the existing `progressChart` in
  `player_assessments.html` (line ~365) — reuse the config.

---

## 4. Chart component spec

One reusable JS function, defined once in `performance/detail.html` (or a small
`static/gymlife/js/performance.js` if it grows). Mirror the existing
`progressChart` initialization pattern.

```javascript
/**
 * Render a metric progress chart.
 * @param {string} canvasId  - <canvas> element id
 * @param {Array<{date: string, value: number, week: string}>} data  - ascending by date
 * @param {string} unit      - e.g. "cm", "s", "N/kg"
 * @param {'increasing'|'decreasing'} trendDirection  - polarity
 */
function renderMetricChart(canvasId, data, unit, trendDirection) { ... }
```
- Single data point → render a dot, not a line (Chart.js handles; add a
  "First assessment — more data needed for trend" caption).
- Zero data points → card hidden by the view (don't render empty cards).
- Colors: line `#f97316` (orange, matches existing `progressChart`
  `pointBackgroundColor`) or `#6366f1` (indigo) — 🔻 pick after asset review.
- Dark mode: Chart.js `scales.x.ticks.color` / `grid.color` must read from
  `getComputedStyle(document.documentElement)` or re-render on dark-mode
  toggle. The existing `player_assessments.html` charts already survive dark
  mode — check how and match it.

---

## 5. States

| State | Trigger | Display |
|-------|---------|---------|
| **Empty — no results** | Player has `ValdProfile` but zero `ValdTestResult` | Header + banner + a centered "No assessments yet" card with copy explaining the weekly schedule and a link to packages if ineligible. |
| **Empty — not linked** | No `ValdProfile` for this player | Same "No assessments yet" card; owner sees a "Match VALD profile" action (owner view only). Client never sees the linking concept. |
| **Loading — first sync** | `ValdSyncRun` exists with `status='running'` and no prior results | "We're pulling your first assessment data — check back shortly." (Seen only during Phase 2 backfill; rare thereafter.) |
| **Single data point** | Exactly 1 result | Chart renders as a dot; caption "First assessment — trends appear after your next session." |
| **Sync error** | Latest `ValdSyncRun.status='error'` | No client-facing error (stale data is still shown). Owner-only: a red dot in the owner performance view. Client page never surfaces sync failures. |
| **Sync disabled** | `settings.VALD_SYNC_ENABLED=False` | Page 404s (URL not registered) — feature is simply absent until enabled. |

---

## 6. Responsive behavior

- Metric card grid: `1 col` (mobile) → `2 cols` (md) → `3 cols` (lg). Matches
  the existing `grid-cols-1 md:grid-cols-2 lg:grid-cols-3` pattern in
  `player_assessments.html` average-stats grid.
- Player header: `flex-col` on mobile (photo above name), `flex-row` on sm+
  — same as existing.
- Tab switcher: full-width segmented control on mobile, auto-width on desktop.
- Charts: Chart.js `responsive: true, maintainAspectRatio: false` inside a
  fixed-height container (`style="height: 280px;"` — the existing pattern).
- Test: add a mobile-render case to the existing Playwright mobile suite (the
  repo already has `test_mobile_dark_mode.py` — extend, don't create a new
  harness).

---

## 7. Owner portal UI — `owner/performance.html`

Lives in `performance/views.py`, routed at `/owner-portal/performance/`
(separate `urls_owner.py` — see integration plan §7). NOT in `admin_views.py`.

### 7.1 Owner performance index
Table of all players with:
- Player name, team, latest assessment date, # results, sync status dot
- Actions: "View" (owner_player_detail) · "Match VALD profile" (if unmatched)
- Top-right: "Sync now" button (POST → dispatches `sync_all_vald` task)

### 7.2 Owner player detail
Same as the client `detail.html` but:
- No eligibility banner (owner doesn't need it)
- Shows the "Match VALD profile" panel if no `ValdProfile` linked
- Shows raw `ValdTestResult.raw_payload` in a collapsible `<details>` for
  debugging (never present on the client view)
- Shows `ValdSyncRun` history (last 5 runs with status/timestamp/record count)

### 7.3 Owner match panel
A small form: dropdown of unmatched VALD profiles (from the latest
`list_profiles` sync) → select one → "Link" button. Manual resolution for
ambiguous name/birth-year matches (integration plan §10).

---

## 8. Template file map

| File | Purpose |
|------|---------|
| `templates/performance/detail.html` | Client-facing player performance page (extends `clients/base.html`) |
| `templates/owner/performance.html` | Owner index — all players, sync status, "Sync now" (extends `owner/base.html`) |
| `templates/owner/performance_detail.html` | Owner per-player view + match panel + sync history (extends `owner/base.html`) |
| `static/gymlife/js/performance.js` *(optional)* | `renderMetricChart()` helper if the inline script in `detail.html` grows beyond ~100 lines |

No new CSS file — all styling via existing Tailwind classes + base dark-mode
overrides.

---

## 9. Open visual questions (🔻 resolve after asset review)

1. **Metric grouping** — by type (ForceDecks/SmartSpeed tabs) or by session
   date (accordion)? VALD's dashboard likely groups by session; confirm.
2. **Chart styling** — line color, whether to show trend line / regression,
   whether to show peer-average (would require aggregating across players —
   out of MVP scope but maybe a Phase 5 "compare to team average" feature).
3. **Metric card density** — big-number + sparkline (compact, 3-up) vs
   full-chart-in-card (spacious, 2-up). Depends on how many metrics the
   owner curates into the portal.
4. **Personal best vs target line** — show PB only, or also an age-group
   benchmark line? (Benchmark data would need to come from VALD or be
   owner-defined — likely Phase 5+.)
5. **Tab vs no-tab** — if VALD's UI doesn't separate force plate from field
   drills, we may drop the tabs and show all curated metrics in one grid
   sorted by `display_order`.
6. **Units display** — inline with the big number ("32.1 cm") or as a
   muted label above ("Jump Height / cm")? Match whatever VALD uses.

These are visual/UX decisions, not structural ones — the data model and view
contracts in the integration plan don't change either way. Implementation can
proceed against this doc and be visually adjusted after the asset review
without rework.
