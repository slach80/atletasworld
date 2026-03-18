# Domain Name Implementation Guide
**Domain:** atletasperformancecenter.com
**Registrar:** Google Workspace (DNS managed via Squarespace)
**Target:** AWS EC2 + HTTPS via Let's Encrypt

---

## Overview

Your domain was registered through Google Workspace and is managed via Squarespace's DNS panel. You'll log into Squarespace with your Google Workspace email to manage DNS records.

Steps:
1. Assign an Elastic IP to your EC2 instance
2. Add DNS A records in Squarespace
3. Update Django settings
4. Install SSL certificate

---

## 1. Assign an Elastic IP to EC2

An Elastic IP ensures your server's public IP never changes, even after reboots.

1. AWS Console → **EC2** → **Elastic IPs** → **Allocate Elastic IP address**
2. Select the new IP → **Actions** → **Associate Elastic IP address**
3. Select your EC2 instance → **Associate**
4. Note the Elastic IP — this is the IP you'll point your domain at

---

## 2. Configure DNS in Squarespace

1. Go to [domains.squarespace.com](https://domains.squarespace.com) — log in with your **Google Workspace email**
2. Click **atletasperformancecenter.com** → **DNS Settings** (or **DNS** tab)
3. Add the following records:

| Type | Host | Value | TTL |
|------|------|-------|-----|
| A | `@` | `<your-elastic-ip>` | 3600 |
| A | `www` | `<your-elastic-ip>` | 3600 |

- `@` points the root domain (`atletasperformancecenter.com`) to EC2
- `www` points the www subdomain to the same server
- If an existing A record is there, **replace it** — don't create a duplicate

4. Save. DNS propagation takes **5–30 minutes** (up to 48 hours in rare cases).

### Verify propagation

```bash
# From your local machine
dig atletasperformancecenter.com +short
# Should return your Elastic IP

nslookup atletasperformancecenter.com
# Should show your Elastic IP under "Address"
```

You can also check at [dnschecker.org](https://dnschecker.org).

---

## 3. Update Django Settings

In `/var/www/atletasworld/.env` on the server:

```env
ALLOWED_HOSTS=atletasperformancecenter.com,www.atletasperformancecenter.com,<elastic-ip>
SITE_URL=https://atletasperformancecenter.com
```

In `src/atletasworld/settings.py`, ensure:

```python
CSRF_TRUSTED_ORIGINS = [
    'https://atletasperformancecenter.com',
    'https://www.atletasperformancecenter.com',
]
```

---

## 4. Update django-allauth Site Domain

The allauth library stores the domain in the database. After going live:

```bash
source venv/bin/activate
cd src
python manage.py shell -c "
from django.contrib.sites.models import Site
site = Site.objects.get_or_create(id=1)[0]
site.domain = 'atletasperformancecenter.com'
site.name = 'Atletas Performance Center'
site.save()
print('Site updated')
"
```

This affects allauth email confirmation links and social auth callbacks.

---

## 5. Nginx Configuration

Make sure the Nginx server block uses the real domain name (not just the IP):

```nginx
# /etc/nginx/sites-available/atletasworld
server {
    listen 80;
    server_name atletasperformancecenter.com www.atletasperformancecenter.com;

    location / {
        proxy_pass http://unix:/run/atletasworld.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## 6. Install SSL Certificate (Let's Encrypt)

> DNS must be pointing to the EC2 Elastic IP before running this — Certbot verifies by resolving the domain.

```bash
sudo apt install certbot python3-certbot-nginx

sudo certbot --nginx \
    -d atletasperformancecenter.com \
    -d www.atletasperformancecenter.com
```

Certbot will:
- Obtain a certificate from Let's Encrypt
- Automatically rewrite the Nginx config to add HTTPS (port 443)
- Add an HTTP → HTTPS redirect for port 80
- Set up auto-renewal via a systemd timer

### Verify auto-renewal

```bash
sudo certbot renew --dry-run
# Should say "Congratulations, all simulated renewals succeeded"
```

Certificates expire every 90 days but auto-renew 30 days before expiry.

---

## 7. Verify HTTPS is Working

```bash
# From your local machine
curl -I https://atletasperformancecenter.com
# Look for: HTTP/2 200 and server: nginx

# Test redirect
curl -I http://atletasperformancecenter.com
# Should return: 301 Moved Permanently → https://...
```

In a browser:
- Navigate to `http://atletasperformancecenter.com` — should redirect to `https://`
- Click the padlock icon → certificate should show `atletasperformancecenter.com` issued by Let's Encrypt

---

## 8. Google Workspace Email (Optional)

If you want to send email from `@atletasperformancecenter.com` using Google Workspace, add MX records in Squarespace:

| Type | Host | Value | Priority |
|------|------|-------|----------|
| MX | `@` | `aspmx.l.google.com` | 1 |
| MX | `@` | `alt1.aspmx.l.google.com` | 5 |
| MX | `@` | `alt2.aspmx.l.google.com` | 5 |
| MX | `@` | `alt3.aspmx.l.google.com` | 10 |
| MX | `@` | `alt4.aspmx.l.google.com` | 10 |

Google Workspace setup walks you through these records during domain verification. If verification is already pending (as shown in the screenshot), these records may already be in place or will be added as part of that flow.

---

## 9. Stripe Webhook Domain Update

Once the domain is live and HTTPS is confirmed, register the production webhook:

1. Stripe Dashboard → Developers → Webhooks → **Add endpoint**
2. URL: `https://atletasperformancecenter.com/payments/webhook/`
3. Copy the signing secret → update `STRIPE_WEBHOOK_SECRET` in `.env`
4. Restart: `sudo supervisorctl restart atletasworld`

---

## Summary Checklist

- [ ] Elastic IP allocated and associated with EC2
- [ ] DNS A records set in Squarespace (`@` and `www` → Elastic IP)
- [ ] DNS propagation confirmed (`dig` or dnschecker.org)
- [ ] `ALLOWED_HOSTS` and `SITE_URL` updated in `.env`
- [ ] `CSRF_TRUSTED_ORIGINS` updated in `settings.py`
- [ ] allauth Site domain updated in database
- [ ] Nginx config updated with real domain name
- [ ] Certbot installed and certificate issued
- [ ] HTTPS verified in browser (padlock present)
- [ ] HTTP → HTTPS redirect verified
- [ ] Auto-renewal dry-run passes
