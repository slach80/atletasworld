# Notification System - Future Enhancements Implemented

## Overview
All planned notification system enhancements have been implemented for the Atletas World platform.

**IMPORTANT: All paid services are DISABLED by default.** Enable them in `.env` as needed.

---

## Service Cost Summary

| Service | Cost | Default | Enable With |
|---------|------|---------|-------------|
| Email (Console) | FREE | Enabled | - |
| Email (SendGrid) | PAID | Disabled | `PRODUCTION_EMAIL_ENABLED=True` |
| SMS (Twilio) | ~$0.0075/SMS | Disabled | `SMS_ENABLED=True` |
| Push Notifications | FREE | Disabled | `PUSH_NOTIFICATIONS_ENABLED=True` |
| Celery (local Redis) | FREE | Disabled | `CELERY_ENABLED=True` |
| Celery (cloud Redis) | PAID | Disabled | `CELERY_ENABLED=True` |

---

## 1. Celery Beat for Scheduled Notifications

### Configuration
- **Location**: `src/atletasworld/celery.py`
- **Settings**: `src/atletasworld/settings.py`

### Scheduled Tasks
| Task | Schedule | Description |
|------|----------|-------------|
| `send_weekly_reminders` | Monday 9 AM | Remind clients who haven't booked this week |
| `check_inactive_clients` | Daily 10 AM | Re-engage clients inactive 3+ weeks |
| `send_booking_reminders` | Daily 8 AM | Remind about tomorrow's sessions |
| `check_expiring_packages` | Daily 9 AM | Alert packages expiring in 7 and 3 days |
| `send_upcoming_event_reminders` | Daily 8 AM | Promote special events/clinics |
| `cleanup_old_notifications` | Sunday 2 AM | Remove notifications older than 90 days |

### Running Celery
```bash
# Start Redis
redis-server

# Start Celery worker
celery -A atletasworld worker -l info -Q notifications,maintenance

# Start Celery Beat (scheduler)
celery -A atletasworld beat -l info
```

---

## 2. Automated Weekly Reminders

- Identifies clients who haven't booked in the past week
- Respects notification preferences
- Sends personalized emails with booking links
- Template-based messaging via Django admin

---

## 3. Inactive Client Re-engagement Campaigns

- Targets clients inactive for 3+ weeks
- Calculates weeks since last booking
- Avoids duplicate notifications (14-day cooldown)
- Special offers and "we miss you" messaging

---

## 4. Custom Campaign Management

### Admin Features (`src/clients/admin.py`)
- **Send Campaign Now**: Immediately trigger campaign to targeted clients
- **Preview Recipients**: See how many clients match the filters
- **Duplicate Template**: Copy templates for variations
- **Send Test Email**: Test templates before sending

### Targeting Filters (JSON)
```json
{
  "has_active_package": true,
  "inactive_weeks": 3,
  "min_sessions": 5
}
```

---

## 5. Multi-Channel Notifications

### Email
- HTML and plain text versions
- Base template with branding (`templates/emails/base_email.html`)
- Specific templates for each notification type

### SMS (Twilio)
- 160 character limit
- Configurable via environment variables

### Web Push Notifications
- VAPID-based authentication
- Service worker integration ready
- Automatic subscription cleanup

---

## 6. New Models

### PushSubscription
- Stores web push subscription endpoints
- Auto-deactivates expired subscriptions
- Tracks last used timestamp

### NotificationSchedule
- Schedule campaigns for future delivery
- Track send statistics (sent/failed counts)
- Admin actions for cancel/execute

---

## 7. Email Templates

Location: `templates/emails/`

| Template | Purpose |
|----------|---------|
| `base_email.html` | Base wrapper with branding |
| `booking_confirmation.html` | Booking confirmed |
| `booking_reminder.html` | 24-hour reminder |
| `weekly_reminder.html` | Weekly booking nudge |
| `inactive_client.html` | Re-engagement |
| `package_expiring.html` | Package expiry warning |
| `assessment_ready.html` | New assessment available |
| `upcoming_event.html` | Event promotion |

---

## 8. Client Portal Views

### New URLs (`src/clients/urls.py`)
- `/portal/notifications/` - Settings
- `/portal/notifications/history/` - View past notifications
- `/portal/notifications/unread-count/` - Badge count API
- `/portal/api/push/subscribe/` - Register push subscription
- `/portal/api/push/unsubscribe/` - Unregister push

---

## 9. Environment Variables

Add to `.env` (all paid services disabled by default):

```bash
# =============================================================================
# FEATURE FLAGS - Enable paid services as needed
# =============================================================================

# SMS via Twilio (PAID - ~$0.0075 per SMS)
SMS_ENABLED=False                    # Set True to enable
TWILIO_ACCOUNT_SID=ACxxx
TWILIO_AUTH_TOKEN=xxx
TWILIO_PHONE_NUMBER=+1234567890

# Web Push Notifications (FREE)
PUSH_NOTIFICATIONS_ENABLED=False     # Set True to enable
VAPID_PUBLIC_KEY=xxx                 # Generate: npx web-push generate-vapid-keys
VAPID_PRIVATE_KEY=xxx

# Production Email (PAID in cloud)
PRODUCTION_EMAIL_ENABLED=False       # Set True for SendGrid/Mailgun

# Celery Background Tasks (requires Redis)
CELERY_ENABLED=False                 # Set True if you have Redis running
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=django-db

# =============================================================================
# General Settings
# =============================================================================
SITE_URL=https://atletasworld.com
DEFAULT_FROM_EMAIL=noreply@atletasworld.com
```

### Without Celery (Default)
Tasks run **synchronously** when `CELERY_ENABLED=False`. This works fine for low traffic but may slow down requests.

### With Celery (Production)
Tasks run **asynchronously** in background workers. Required for scheduled tasks (weekly reminders, etc.).

---

## 10. Dependencies Added

```
django-celery-beat==2.8.0
django-celery-results==2.5.1
pywebpush==2.0.4
twilio==9.6.0
```

---

## Migration

Run migrations to apply new models:
```bash
python manage.py migrate
```

---

## Usage

### Create Notification Templates in Admin
1. Go to Admin > Notification Templates
2. Create templates for each notification type
3. Use Django template syntax: `{{ client_name }}`, `{{ date }}`, etc.
4. Set target filters for campaigns

### Send Custom Campaign
1. Select template in admin
2. Use "Preview recipients" to check audience size
3. Use "Send campaign now" to trigger immediately

### Monitor Notifications
- Admin > Notifications - View all sent notifications
- Admin > Notification Schedules - View scheduled campaigns
- Admin > Celery Results - View task execution history
