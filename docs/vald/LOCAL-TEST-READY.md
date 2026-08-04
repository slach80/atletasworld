# VALD Performance - Local Test Environment Ready

## Status: ✅ Ready for Browser Testing

All Phase 1 components are built, migrated, and running locally. Test data is seeded and verified.

---

## Quick Start

### 1. Dev Server Running
```bash
# Server is already running at:
http://192.168.1.92:8001

# To check status:
ps aux | grep "manage.py runserver"

# To view logs:
tail -f /tmp/atletasworld_dev.log

# To stop:
kill $(cat /tmp/atletasworld_dev.pid)
```

### 2. Test Credentials
- **Email**: `test_parent@example.com`
- **Password**: `testpass123`
- **Role**: Superuser (can access both client and owner portals)

### 3. Test Data
- **Player**: Emma Johnson (12 years old, U12)
- **VALD Profile**: `vald-test-emma-001`
- **Assessments**: 8 ForceDecks CMJ tests over 8 weeks (June 7 - July 26, 2026)
- **Metrics**: 4 visible metrics with trend data
  - Jump Height: 28.5 → 32.5 cm (↑ +4.0 cm improvement)
  - Peak Force: 1650 → 1880 N (↑ +230 N improvement)
  - Reactive Strength Index: 1.05 → 1.35 (↑ +0.30 improvement)
  - Concentric/Eccentric Ratio: 0.85 → 0.98 (↑ +0.13 improvement)

---

## Test URLs

### Client Portal
1. **Login**: http://192.168.1.92:8001/accounts/login/
2. **Performance Index**: http://192.168.1.92:8001/portal/performance/
3. **Player Detail**: http://192.168.1.92:8001/portal/performance/player/9/

### Owner Portal
4. **Performance Dashboard**: http://192.168.1.92:8001/owner-portal/performance/

---

## Browser Test Checklist

### ✅ Functional Tests

#### 1. Login & Navigation
- [ ] Login page loads at `/accounts/login/`
- [ ] Can log in with test credentials
- [ ] Redirects to client dashboard after login
- [ ] Can navigate to `/portal/performance/` (no 404/500)

#### 2. Client Portal - Performance Index
- [ ] Page title: "Performance Assessments"
- [ ] Breadcrumb: Dashboard › Performance
- [ ] Player card shows "Emma Johnson"
- [ ] Stats display: "8 Total Assessments"
- [ ] "Last Assessed" date shown (July 26, 2026)
- [ ] "View Performance" button visible and clickable

#### 3. Client Portal - Player Detail
- [ ] Page loads at `/portal/performance/player/9/`
- [ ] Breadcrumb: Dashboard › Performance › Emma Johnson
- [ ] Player header with initials "EJ" in colored circle
- [ ] Header stats: "8 Total Assessments"
- [ ] Eligibility banner visible (yellow/warning state)
- [ ] **4 metric cards displayed in grid**:
  - Jump Height (cm)
  - Peak Force (N)
  - Reactive Strength Index
  - Concentric/Eccentric Ratio
- [ ] Each card shows:
  - Metric name and unit
  - Latest value (e.g., "32.5")
  - Delta badge (green ↑ with "+0.4 vs last")
  - Mini sparkline chart (8 data points)
  - Count: "8 assessments"
- [ ] **Charts render without errors** (check browser console F12)
- [ ] Chart.js loaded (check Network tab for `chart.js`)

#### 4. Owner Portal
- [ ] Page loads at `/owner-portal/performance/`
- [ ] Page title: "VALD Performance"
- [ ] "Sync Now" button visible (top right)
- [ ] "Recent Sync Runs" table exists (empty initially)
- [ ] "Player Assessment Data" table shows:
  - Emma Johnson row
  - VALD Profile ID: `vald-test-emma-001`
  - Latest test date
  - Assessment count: 8
  - Status dot (green)
  - "View" action link
- [ ] "View" link navigates to owner player detail

### ✅ UI/UX Tests

#### 5. Dark Mode
- [ ] Toggle button exists (typically in nav bar)
- [ ] Clicking toggle switches to dark mode
- [ ] Background becomes dark (gray-800/900)
- [ ] Text remains readable (white/gray-100)
- [ ] Cards have dark background
- [ ] Charts remain visible (colors adapt or stay legible)
- [ ] No white flashes or contrast issues
- [ ] Toggle back to light mode works

#### 6. Responsive Design
**Desktop (1920px)**:
- [ ] Metric cards display in 3-column grid (`lg:grid-cols-3`)
- [ ] All content visible without horizontal scroll

**Tablet (768px)**:
- [ ] Metric cards display in 2-column grid (`md:grid-cols-2`)

**Mobile (375px)**:
- [ ] Metric cards stack to 1 column
- [ ] Player header stats stack vertically
- [ ] Charts scale to fit mobile width
- [ ] Navigation collapses to hamburger menu
- [ ] All buttons remain clickable (no overlap)
- [ ] No horizontal scroll

#### 7. Empty States
To test empty state, create a new player without VALD profile:
- [ ] Player card shows "No assessment data available yet"
- [ ] Detail page shows empty state card with icon
- [ ] Message: "No Assessment Data Yet" or similar
- [ ] No JavaScript errors on empty data

### ✅ Security Tests

#### 8. Authentication Wall
**Logout and test unauthenticated access**:
- [ ] `/portal/performance/` redirects to login (not 404/500)
- [ ] `/portal/performance/player/9/` redirects to login
- [ ] After login, redirects back to intended page

#### 9. IDOR Protection
Create a second test user and try to access Emma's player detail:
- [ ] User B cannot access `/portal/performance/player/9/` (404 or permission denied)

#### 10. Feature Flag
**Set `VALD_SYNC_ENABLED=False` in `.env`, restart server**:
- [ ] `/portal/performance/` returns 404
- [ ] Error message: "VALD integration is not enabled"
- [ ] Re-enable and restart to restore access

### ✅ Technical Tests

#### 11. Browser Console (F12 → Console)
- [ ] No JavaScript errors on page load
- [ ] No errors when charts render
- [ ] No 404s for static assets (CSS, fonts, images)
- [ ] Chart.js logs show initialization (if verbose logging enabled)

#### 12. Network Tab (F12 → Network)
- [ ] All requests return 200 (except intentional redirects)
- [ ] No failed CSS/JS requests
- [ ] `/static/` assets load correctly
- [ ] Page load time < 3 seconds

#### 13. Server Logs
```bash
tail -f /tmp/atletasworld_dev.log
```
- [ ] No Python exceptions on page load
- [ ] No template rendering errors
- [ ] No database query errors

---

## Known Limitations (Phase 1)

These are **expected** and will be addressed in Phase 2+:

1. **No live sync** — "Sync Now" button shows stub message (Celery tasks not built yet)
2. **Manual test data** — used Django shell to seed; no backfill command yet
3. **Mock credentials** — using placeholder VALD API credentials (Phase 0 pending)
4. **ForceDecks only** — SmartSpeed integration is Phase 3
5. **No real API calls** — API client is built but not tested against real VALD APIs yet
6. **Eligibility logic simplified** — always shows "Not currently eligible" banner

---

## Screenshot Targets

Capture these for documentation:

1. **Client Index** (light mode) - player list
2. **Player Detail** (light mode) - 4 metric cards with charts
3. **Player Detail** (dark mode) - same view in dark theme
4. **Owner Dashboard** - sync runs + player table
5. **Mobile View** - player detail at 375px width
6. **Empty State** - player with no VALD profile

---

## If Something Doesn't Work

### Page returns 404
- Check `VALD_SYNC_ENABLED=True` in `.env`
- Restart dev server: `kill $(cat /tmp/atletasworld_dev.pid) && cd src && python manage.py runserver 0.0.0.0:8001 &`

### Charts don't render
- Open browser console (F12)
- Check for JavaScript errors
- Verify Chart.js loaded: check Network tab for `chart.js`
- Verify data: inspect HTML for `window.chartData1 = [...]` script blocks

### Metrics show "0" or blank
- Verify test data: `cd src && python manage.py shell`
  ```python
  from performance.models import ValdTestResult
  print(ValdTestResult.objects.count())  # Should be 8
  ```

### Login fails
- Verify user exists:
  ```bash
  cd src && python manage.py shell
  from django.contrib.auth.models import User
  user = User.objects.get(username='test_parent@example.com')
  print(user.check_password('testpass123'))  # Should be True
  ```

### Server not responding
- Check if running: `ps aux | grep "manage.py runserver"`
- Check logs: `tail -50 /tmp/atletasworld_dev.log`
- Restart: see "Page returns 404" above

---

## Next Steps After Browser Testing

1. **Document UI/UX findings** — note any visual issues, layout bugs, contrast problems
2. **Test all checklist items** — mark each as pass/fail
3. **Capture screenshots** — for design review and documentation
4. **Review metrics display** — ensure delta colors are correct (green for improvement)
5. **Test error states** — logout, feature flag off, empty data
6. **Check mobile** — resize browser to 375px, verify all elements visible
7. **Check dark mode** — toggle multiple times, look for flash/contrast issues

Once browser testing is complete, we can:
- Fix any UI bugs found
- Proceed to Phase 0 (VALD credential acquisition)
- Build Phase 2 (Celery sync tasks)

---

## Test Data Details

### User
- ID: 14
- Username: `test_parent@example.com`
- Superuser: Yes
- Staff: Yes

### Player
- ID: 9
- Name: Emma Johnson
- Birth Year: 2014
- Age: 12
- Age Group: U12

### VALD Profile
- VALD Profile ID: `vald-test-emma-001`
- Tenant ID: `tenant-apc-test`
- Match Method: manual
- Active: Yes

### Test Results (8 assessments)
| Week | Date | Jump Height | Peak Force | RSI | Ratio |
|------|------|-------------|------------|-----|-------|
| 2026-W23 | Jun 7 | 28.5 cm | 1650 N | 1.05 | 0.85 |
| 2026-W24 | Jun 14 | 29.2 cm | 1680 N | 1.12 | 0.88 |
| 2026-W25 | Jun 21 | 30.1 cm | 1720 N | 1.18 | 0.90 |
| 2026-W26 | Jun 28 | 29.8 cm | 1700 N | 1.15 | 0.89 |
| 2026-W27 | Jul 5 | 31.2 cm | 1780 N | 1.25 | 0.93 |
| 2026-W28 | Jul 12 | 31.8 cm | 1820 N | 1.30 | 0.95 |
| 2026-W29 | Jul 19 | 32.1 cm | 1850 N | 1.32 | 0.96 |
| 2026-W30 | Jul 26 | 32.5 cm | 1880 N | 1.35 | 0.98 |

**Overall Progress**: +14% jump height, +14% peak force, +29% RSI, +15% power ratio

---

## Contact

For questions or issues during testing, refer to:
- **Integration Plan**: `/docs/vald/integration-plan.md`
- **Design Spec**: `/docs/vald/portal-design.md`
- **Phase 1 Summary**: `/docs/vald/phase-1-summary.md`
- **Dev Server Logs**: `/tmp/atletasworld_dev.log`
