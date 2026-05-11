# Notification Recipients Verification

**Date**: 2026-05-10  
**Purpose**: Verify all notification recipient groups have correct counts and matching email resolution logic

## Recipient Groups

| Group | Count Variable | Count Logic | Email Resolution Logic | Match? |
|-------|---------------|-------------|------------------------|--------|
| **All Clients** | `all_clients_count` | `Client.objects.filter(user__email__isnull=False).exclude(user__email='').count()` | Same query → `values_list('user__email', flat=True)` | ✅ |
| **All Coaches** | `all_coaches_count` | `Coach.objects.filter(is_active=True, user__email__isnull=False).exclude(user__email='').count()` | Same query → `values_list('user__email', flat=True)` | ✅ |
| **Everyone** | `all_users_count` | `User.objects.filter(is_active=True, email__isnull=False).exclude(email='').count()` | Same query → `values_list('email', flat=True)` | ✅ |
| **Active Clients** | `active_clients_count` | `Booking.objects.filter(scheduled_date__gte=today-30d).values_list('client_id', flat=True).distinct()` → `Client.objects.filter(id__in=...)` | Same query logic | ✅ |
| **This Week** | `clients_with_bookings_this_week_count` | `Booking.objects.filter(scheduled_date__gte=today, scheduled_date__lte=today+7d).values_list('client_id', flat=True).distinct()` → `Client.objects.filter(id__in=...)` | Same query logic | ✅ |
| **Packaged Clients** | `packaged_clients_count` | `ClientPackage.objects.filter(status='active', expiry_date__gte=today).values_list('client_id', flat=True).distinct()` → `Client.objects.filter(id__in=...)` | Same query logic | ✅ |
| **By Package** | Per-package count in dropdown | `ClientPackage.objects.filter(package=pkg, status='active', expiry_date__gte=today).values('client_id').distinct().count()` | Same filter with `package_id=` param | ✅ |
| **All Contacts** | `all_contacts_count` | `ContactParent.objects.exclude(email='').count()` | Same query → `values_list('email', flat=True)` | ✅ |
| **Unregistered Contacts** | `unregistered_contacts_count` | `ContactParent.objects.filter(client__isnull=True).exclude(email='').count()` | Same query → `values_list('email', flat=True)` | ✅ |
| **Contacts by Source** | Per-source count (not shown in UI) | `ContactParent.objects.filter(source=val).exclude(email='').count()` | Same filter with `contact_source=` param | ✅ |
| **Individual Select** | Dynamic (no fixed count) | N/A — user manually selects | `recipients.update(individual_emails)` from form | ✅ |

## Info Bubble Descriptions

| Group | Tooltip Text |
|-------|-------------|
| All Clients | "All registered client accounts with email addresses" |
| All Coaches | "All active coach accounts (inactive coaches excluded)" |
| Everyone | "All active users (clients + coaches combined)" |
| Active Clients | "Clients with at least one booking in the last 30 days" |
| This Week | "Clients with upcoming bookings in the next 7 days" |
| Packaged Clients | "Clients with at least one active package (not expired)" |
| By Package | "Target clients holding a specific active package (select from dropdown)" |
| All Contacts | "All contacts from CSV imports + new signups (includes registered & unregistered)" |
| Unregistered Contacts | "Contacts who haven't created an account yet (from imports only)" |
| Contacts by Source | "Filter contacts by their source (event or program they came from)" |
| Individual Select | "Manually select specific individuals from checkboxes below" |

## Edge Cases & Notes

### 1. Duplicate Prevention
- All recipient resolution uses `set()` for automatic deduplication
- Individual Select can have duplicates if same email checked in multiple lists → handled by set
- Form submission protection prevents accidental double-sends

### 2. ContactParent vs Client
- **ContactParent**: Includes CSV imports + auto-created on signup (source='signup')
- **Client**: Only registered users with accounts
- Overlap: If someone from CSV imports later registers → appears in BOTH tables (linked via `client` FK)

### 3. Active vs Packaged
- **Active Clients** = had booking in last 30 days (regardless of package status)
- **Packaged Clients** = currently holds active package (may not have recent bookings)
- These groups can overlap or be completely different

### 4. Time Windows
- "Last 30 days" = `scheduled_date >= today - 30 days`
- "Next 7 days" = `scheduled_date >= today AND scheduled_date <= today + 7 days`
- Both use `timezone.localdate()` for consistent date comparison

## Testing Checklist

- [x] Count logic matches email resolution logic for all groups
- [x] Info bubbles added to all recipient options
- [x] Tooltips explain each group clearly
- [x] Duplicate prevention confirmed (set-based deduplication)
- [x] Form double-submit protection added
- [x] ContactParent auto-creation on signup implemented
- [ ] Manual verification on production after deploy (check actual counts match)

## Known Issues (Fixed)

1. ~~ContactParent count stuck at 394~~ → Fixed: Now auto-creates on signup
2. ~~Duplicate emails~~ → Fixed: Added UI warning + form submit protection
