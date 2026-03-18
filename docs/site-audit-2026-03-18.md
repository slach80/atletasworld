# Site Audit — March 18, 2026

Performed via Playwright full-site crawl across all portals.

## 🔴 Broken Pages (500 errors)

| Page | Error |
|------|-------|
| `/owner-portal/field-rental/` | `FieldError: Cannot resolve keyword 'booked_at'` — field renamed, query not updated. Use `requested_at`. |
| `/owner-portal/teams/` | `AttributeError: property 'player_count' of 'Team' object has no setter` — ORM `annotate()` conflicts with `@property` on Team model. |

## 🟡 Functional Issues

| Page | Issue |
|------|-------|
| `/portal/field-rental/` | Silently redirects to dashboard — client facility rental page not routed |
| `/owner-portal/notifications/` | Broken nav — only shows Dashboard/Notifications/Backend/Logout; wrong base template |
| Login page | Duplicate "Remember me" + "Forgot password?" fields rendered (allauth + custom template conflict) |

## 🟠 Missing Assets

| Asset | Issue |
|-------|-------|
| `/media/APC-logo.jpg` | 404 on every page — file missing from media directory |
| 2× Facebook CDN image URLs | Expired URLs on public homepage (coach photos) |

## ✅ Pages Verified Working

### Public
- Homepage (all sections)
- `/coach/mirko/`
- `/coach/roger/`
- Login, Signup pages

### Owner Portal
- Dashboard, Bookings, Clients, Coaches, Packages, Sessions, Finances, Services, Notify

### Coach Portal (tested as Mirko)
- Dashboard, Schedule, My Players, Assessments, Notify Parents

### Client Portal (tested as John Smith / test@test.com)
- Dashboard, My Bookings, Assessments, Notifications, Packages
- Book Session (calendar view — working correctly)

## Open Todos (task IDs in session)
- #2 Fix `/owner-portal/field-rental/` FieldError
- #3 Fix `/owner-portal/teams/` AttributeError
- #4 Add client facility rental page at `/portal/field-rental/`
- #5 Fix owner notifications nav (wrong base template)
- #6 Fix duplicate Remember Me / Forgot Password on login
- #7 Add missing `APC-logo.jpg` to media folder
