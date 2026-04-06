# Email Notification Setup

## Current Status

Email notifications are **not active** by default.
The backend is set to `console` — emails print to the server terminal instead of being delivered.

`django-anymail` v13.1 is already installed and configured. Only a provider API key + 3 env vars are needed to go live.

---

## What Needs to Be Done

1. Choose a provider (Google Workspace, SendGrid, Mailgun, or Resend)
2. Follow the setup steps for your chosen option
3. Add the required lines to `/var/www/atletasworld/.env` on the server
4. Restart the app

---

## Provider Options

### Option A — Google Workspace (Gmail Business) ⭐ Recommended if you already use Google

If `info@atletasperformancecenter.com` is a Google Workspace account, you can send email directly through it using an **App Password** — no third-party service needed.

> **Note:** This uses Django's built-in SMTP backend, NOT django-anymail. No API key required.

**Steps:**

1. Log in to the Google account: `info@atletasperformancecenter.com`
2. Go to **https://myaccount.google.com/security**
3. Make sure **2-Step Verification is ON** (required for App Passwords)
4. Search for **App Passwords** in the search bar → click it
5. Select app: **Mail** · Select device: **Other (custom name)** → type `APC Website`
6. Click **Generate** → copy the 16-character password (looks like: `xxxx xxxx xxxx xxxx`)

**`.env` additions:**
```
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=info@atletasperformancecenter.com
EMAIL_HOST_PASSWORD=xxxxxxxxxxxxxxxxxxxx
PRODUCTION_EMAIL_ENABLED=True
```

> **Limits:** Google Workspace allows up to **2,000 emails/day** — more than enough for APC.

> **Important:** Use the App Password (16 chars, no spaces), NOT your regular Google account password.

---

### Option A — SendGrid ⭐ (recommended)
- **Free tier:** 100 emails/day
- **URL:** https://sendgrid.com

**Steps:**
1. Create account → Settings → API Keys → **Create API Key** (Full Access)
2. Settings → Sender Authentication → **Authenticate a Domain** → enter `atletasperformancecenter.com`
3. Add the 3 CNAME records they provide to your DNS (wherever the domain is managed)
4. Wait for verification (usually < 1 hour)

**`.env` additions:**
```
EMAIL_BACKEND=anymail.backends.sendgrid.EmailBackend
SENDGRID_API_KEY=SG.xxxxxxxxxxxxxxxxxxxx
PRODUCTION_EMAIL_ENABLED=True
```

---

### Option B — Mailgun
- **Free tier:** 1,000 emails/month for 3 months, then pay-as-you-go
- **URL:** https://mailgun.com

**Steps:**
1. Create account → Sending → Domains → **Add Domain** → enter `atletasperformancecenter.com`
2. Add the DNS records they provide (MX + TXT + CNAME)
3. Mailgun Dashboard → API Keys → copy your Private API key

**`.env` additions:**
```
EMAIL_BACKEND=anymail.backends.mailgun.EmailBackend
MAILGUN_API_KEY=key-xxxxxxxxxxxxxxxxxxxx
MAILGUN_SENDER_DOMAIN=atletasperformancecenter.com
PRODUCTION_EMAIL_ENABLED=True
```

---

### Option C — Resend (newest, simplest)
- **Free tier:** 3,000 emails/month, 100/day
- **URL:** https://resend.com

**Steps:**
1. Create account → Domains → **Add Domain** → enter `atletasperformancecenter.com`
2. Add their DNS records (3 TXT/CNAME records)
3. API Keys → **Create API Key**

**`.env` additions:**
```
EMAIL_BACKEND=anymail.backends.resend.EmailBackend
RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxx
PRODUCTION_EMAIL_ENABLED=True
```

---

## Applying the Changes on the Server

```bash
# SSH into the server
ssh -i ~/Documents/certs/atletasworld-prod.pem ubuntu@3.135.174.227

# Edit the env file
sudo nano /var/www/atletasworld/.env

# Add the 3 lines for your chosen provider, save (Ctrl+O, Enter, Ctrl+X)

# Restart the app
sudo supervisorctl restart atletasworld atletasworld-celery
```

---

## Verifying It Works

1. Log in as owner → **Notify** → select **All Clients** (or a small test group)
2. Enter a subject and message → Send
3. Check that emails arrive in the recipient inbox

If emails don't arrive:
- Check the server logs: `sudo tail -50 /var/log/atletasworld/error.log`
- Make sure domain DNS records are verified in the provider dashboard
- Confirm `PRODUCTION_EMAIL_ENABLED=True` (not `False`) is in `.env`

---

## How the Code Works

Settings (`src/atletasworld/settings.py`) reads from `.env`:

```python
EMAIL_BACKEND = env('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
PRODUCTION_EMAIL_ENABLED = env.bool('PRODUCTION_EMAIL_ENABLED', default=False)
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='noreply@atletasperformancecenter.com')
```

**No code changes are needed** — only the `.env` file on the server.

The `DEFAULT_FROM_EMAIL` is already set to `noreply@atletasperformancecenter.com`, which means emails will appear to come from that address. Make sure the sending domain `atletasperformancecenter.com` is verified with your provider.

---

## Emails Sent By the App

| Trigger | Recipient | Template |
|---|---|---|
| Owner → Notify | Any group or individual | Custom subject + body |
| Booking confirmation | Client | `emails/booking_confirmation.html` |
| Booking reminder (24h) | Client | `emails/booking_reminder.html` |
| Package expiring soon | Client | `emails/package_expiring.html` |
| Assessment ready | Client | `emails/assessment_ready.html` |
| Coach notify parents | Client | `emails/base_email.html` |
| Weekly digest | Client | `emails/weekly_reminder.html` |
| Inactive client reminder | Client | `emails/inactive_client.html` |

> **Note:** Background reminder emails (booking reminders, expiry alerts) are sent via **Celery**. Celery is already running on the server (`atletasworld-celery` supervisor process). Once `PRODUCTION_EMAIL_ENABLED=True` is set, these will start delivering automatically.
