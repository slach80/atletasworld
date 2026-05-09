# Hustle Template Sync Guide

This guide explains how atletasworld changes are automatically synced to the hustle template repository.

## Overview

**Hustle** (`/home/slach/Projects/hustle`) is a generic Django booking system template extracted from atletasworld. When you close a Claude Code session in atletasworld, the system automatically:

1. Detects changes in reusable booking logic
2. Creates sync reports with code snippets
3. Writes actionable notes to `hustle/UPDATES_PENDING.md`

## Automatic Detection

The sync hook (`.claude/auto-port-to-hustle.sh`) monitors these files:

| File | Hustle Destination | What to Port |
|------|-------------------|--------------|
| `src/bookings/models.py` | `hustle/modules/booking_models.py` | Model methods, properties, business logic |
| `src/bookings/api.py` | `hustle/modules/booking_api.py` | ViewSet methods, serializers, endpoints |
| `src/clients/models.py` | `hustle/models.py` | ClientPackage, Player model changes |
| `src/coaches/models.py` | `hustle/models.py` | Coach, ScheduleBlock changes |

## What to Port vs. Skip

### ✅ Port to Hustle (Generic)

- **Booking logic**: Package selection, player assignment, validation
- **API endpoints**: RESTful booking CRUD operations
- **Model methods**: `can_cancel()`, `reschedule()`, `use_package()`
- **Utilities**: Date helpers, conflict detection, pricing logic

### ❌ Skip (Atletasworld-Specific)

- **Templates**: Any `.html` files (use different branding)
- **Business rules**: Team-specific logic, APC membership tiers
- **Admin views**: Owner portal code (hustle has generic dashboards)
- **Integrations**: Stripe webhook handlers with atletasworld keys

## Manual Port Workflow

After session close, if changes are detected:

```bash
# 1. Review sync report
cd /home/slach/Projects/hustle
cat UPDATES_PENDING.md

# 2. Port model changes
# - Open hustle/models.py
# - Add new fields/methods from sync report
# - Replace ForeignKeys with placeholders (Coach → Provider, Player → Participant)

# 3. Port API changes
# - Open hustle/modules/booking_api.py
# - Add new endpoints/methods
# - Remove atletasworld-specific logic (notifications, payments)

# 4. Update CHANGELOG.md
cat >> CHANGELOG.md << EOF

## $(date +%Y-%m-%d) - Sync from atletasworld

- [Feature name from commit]
- [API change description]

EOF

# 5. Commit and push
git add -A
git commit -m "sync: port player-specific package logic from atletasworld"
git push

# 6. Clean up
rm UPDATES_PENDING.md  # or archive it
```

## Example: Today's Changes (2026-05-09)

### What Was Changed in Atletasworld

```
✅ src/bookings/api.py (lines 442-480)
   - Auto-select player-specific packages in BookingViewSet.create()
   - Fallback logic: player package → unassigned package

✅ src/clients/models.py
   - ClientPackage.player ForeignKey already existed
   - No model schema changes

✅ src/clients/views.py (lines 873-987)
   - booking_page: fetch all packages, build player_packages map
   - reserve_session: player-aware package selection
   - confirm_booking: per-player package validation

❌ templates/owner/client_detail.html
   - Skip (owner portal is atletasworld-specific)

❌ templates/clients/dashboard.html
   - Skip (uses atletasworld branding)
```

### What Should Be Ported to Hustle

```bash
cd /home/slach/Projects/hustle

# 1. Update models.py (if ClientPackage.player doesn't exist)
# Add:
class ClientPackage(models.Model):
    client = models.ForeignKey('Client', ...)  # placeholder
    player = models.ForeignKey('Player', null=True, blank=True,
                               help_text="Assign package to specific player")
    # ... rest of fields

# 2. Update booking_api.py
# Add auto-selection logic from BookingViewSet.create():
    # Auto-select package if not provided: prefer player-specific
    if player_id:
        package = client.packages.filter(
            status='active',
            expiry_date__gte=timezone.localdate(),
            player_id=player_id
        ).first()
        # Fallback to unassigned...

# 3. Update CHANGELOG.md
echo "## 2026-05-09 - Player-Specific Package Booking" >> CHANGELOG.md
echo "- Packages can be assigned to specific players" >> CHANGELOG.md
echo "- Booking API auto-selects correct package per player" >> CHANGELOG.md
```

## Configuration

The sync hook is configured in `.claude/settings.json`:

```json
{
  "hooks": {
    "onSessionEnd": {
      "command": "bash .claude/auto-port-to-hustle.sh",
      "description": "Auto-detect and port reusable changes to hustle template"
    }
  }
}
```

To disable: remove the `onSessionEnd` hook from settings.json.

## Troubleshooting

**Q: Script didn't detect my changes**  
A: The script only looks at last 5 commits. If your change is older, run manually:
```bash
bash .claude/auto-port-to-hustle.sh
```

**Q: UPDATES_PENDING.md wasn't created**  
A: Changes may be in files not monitored (e.g., templates). Check script output.

**Q: How do I test hustle after porting?**  
A: Hustle uses placeholder models. To test:
1. Create a test Django project
2. Replace placeholders with real models
3. Run migrations and manual tests

## Best Practices

1. **Review before pushing**: Sync reports may include atletasworld-specific code
2. **Genericize logic**: Remove hard-coded values (coach names, prices)
3. **Update tests**: Hustle should have unit tests for ported logic
4. **Version bumps**: Update `hustle/__version__.py` on breaking changes
5. **Keep docs in sync**: Update hustle README.md with new features

## See Also

- Hustle README: `/home/slach/Projects/hustle/README.md`
- Hustle CLAUDE.md: `/home/slach/Projects/hustle/CLAUDE.md`
- Atletas CLAUDE.md: `/home/slach/Projects/atletasworld/CLAUDE.md`
