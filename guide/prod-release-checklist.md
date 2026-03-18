# Production Release Checklist
**Stack:** Django · AWS EC2 + RDS PostgreSQL · S3 · Nginx + Gunicorn
**Domain:** atletasperformancecenter.com

---

## 1. AWS Infrastructure Setup

### 1a. RDS PostgreSQL
- [ ] Create RDS instance (PostgreSQL 15+, `db.t3.micro` to start)
- [ ] VPC security group: allow inbound 5432 **from EC2 security group only** (not public)
- [ ] Note the endpoint, database name, username, password

### 1b. EC2 Instance
- [ ] Launch Ubuntu 22.04 LTS (`t3.small` or larger)
- [ ] Allocate and associate an **Elastic IP** (required so DNS stays stable — see `domain-name-implementation.md`)
- [ ] Security group inbound rules:
  - 22 SSH — your IP only
  - 80 HTTP — 0.0.0.0/0
  - 443 HTTPS — 0.0.0.0/0
- [ ] EC2 security group outbound: allow port 5432 to RDS security group

### 1c. S3 Bucket (static + media files)
- [ ] Create bucket, e.g. `atletasperformancecenter-static`
- [ ] Block public access settings: OFF (or front with CloudFront)
- [ ] Create IAM user with S3 access scoped to this bucket only
- [ ] Save `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`

---

## 2. Server Setup (SSH into EC2)

```bash
ssh -i your-key.pem ubuntu@<elastic-ip>

sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv nginx supervisor git postgresql-client

sudo mkdir -p /var/www/atletasworld
sudo chown ubuntu:ubuntu /var/www/atletasworld
cd /var/www/atletasworld

git clone https://github.com/your-org/atletasworld.git .

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install gunicorn psycopg2-binary django-storages boto3
```

---

## 3. Environment Variables

Create `/var/www/atletasworld/.env`:

```env
SECRET_KEY=<generate-new — see command below>
DEBUG=False
ALLOWED_HOSTS=atletasperformancecenter.com,www.atletasperformancecenter.com,<elastic-ip>

# PostgreSQL (RDS)
DATABASE_URL=postgres://dbuser:dbpassword@<rds-endpoint>:5432/atletasworld

# S3
AWS_ACCESS_KEY_ID=<iam-key>
AWS_SECRET_ACCESS_KEY=<iam-secret>
AWS_STORAGE_BUCKET_NAME=atletasperformancecenter-static
AWS_S3_REGION_NAME=us-east-1

# Stripe (use live keys in production)
STRIPE_PUBLIC_KEY=pk_live_xxx
STRIPE_SECRET_KEY=sk_live_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx

# Email
EMAIL_BACKEND=anymail.backends.sendgrid.EmailBackend
SENDGRID_API_KEY=SG.xxx
DEFAULT_FROM_EMAIL=noreply@atletasperformancecenter.com
PRODUCTION_EMAIL_ENABLED=True

SITE_URL=https://atletasperformancecenter.com

# Celery (requires Redis — install below if enabling)
CELERY_ENABLED=True
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=django-db
```

Generate `SECRET_KEY`:
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

---

## 4. S3 Static File Configuration

Add to `src/atletasworld/settings.py` (conditional block):

```python
if env('AWS_STORAGE_BUCKET_NAME', default=''):
    DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
    STATICFILES_STORAGE = 'storages.backends.s3boto3.S3StaticStorage'
    AWS_ACCESS_KEY_ID = env('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = env('AWS_SECRET_ACCESS_KEY')
    AWS_STORAGE_BUCKET_NAME = env('AWS_STORAGE_BUCKET_NAME')
    AWS_S3_REGION_NAME = env('AWS_S3_REGION_NAME', default='us-east-1')
    AWS_S3_CUSTOM_DOMAIN = f"{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com"
    STATIC_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/static/"
    MEDIA_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/media/"
```

---

## 5. Django Security Settings

Add to `settings.py` if not already present:

```python
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
CSRF_TRUSTED_ORIGINS = ['https://atletasperformancecenter.com', 'https://www.atletasperformancecenter.com']
```

---

## 6. Database Migration (SQLite → RDS PostgreSQL)

```bash
source venv/bin/activate
cd src

# Verify RDS connection
python manage.py dbshell   # should open psql prompt

# Run all migrations against RDS
python manage.py migrate

# Create owner superuser
python manage.py createsuperuser

# Create auth groups
python manage.py shell -c "
from django.contrib.auth.models import Group
for name in ['Owner', 'Coach', 'Client']:
    Group.objects.get_or_create(name=name)
print('Groups OK')
"
```

> **Note:** Do not attempt to migrate SQLite data to RDS — start fresh in production and re-enter any needed seed data.

---

## 7. Collect Static Files

```bash
source venv/bin/activate
cd src
python manage.py collectstatic --noinput
# Uploads to S3 if configured, otherwise writes to STATIC_ROOT
```

---

## 8. Gunicorn (via Supervisor)

Create `/etc/supervisor/conf.d/atletasworld.conf`:

```ini
[program:atletasworld]
command=/var/www/atletasworld/venv/bin/gunicorn
    --workers 3
    --bind unix:/run/atletasworld.sock
    --access-logfile /var/log/atletasworld/access.log
    --error-logfile /var/log/atletasworld/error.log
    atletasworld.wsgi:application
directory=/var/www/atletasworld/src
user=ubuntu
autostart=true
autorestart=true
```

```bash
sudo mkdir -p /var/log/atletasworld
sudo supervisorctl reread && sudo supervisorctl update
sudo supervisorctl start atletasworld
```

---

## 9. Nginx

Create `/etc/nginx/sites-available/atletasworld`:

```nginx
server {
    listen 80;
    server_name atletasperformancecenter.com www.atletasperformancecenter.com;

    client_max_body_size 20M;

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
sudo ln -s /etc/nginx/sites-available/atletasworld /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

---

## 10. SSL (Let's Encrypt / Certbot)

> Complete domain DNS pointing first — see `domain-name-implementation.md`

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d atletasperformancecenter.com -d www.atletasperformancecenter.com

# Verify auto-renew
sudo certbot renew --dry-run
```

Certbot rewrites the Nginx config to add HTTPS and redirect HTTP → HTTPS automatically.

---

## 11. Celery + Redis (Background Tasks)

```bash
sudo apt install redis-server
sudo systemctl enable redis-server && sudo systemctl start redis-server
```

Add to `/etc/supervisor/conf.d/atletasworld.conf`:

```ini
[program:atletasworld-celery]
command=/var/www/atletasworld/venv/bin/celery
    -A atletasworld worker --loglevel=info
    --logfile=/var/log/atletasworld/celery.log
directory=/var/www/atletasworld/src
user=ubuntu
autostart=true
autorestart=true
```

```bash
sudo supervisorctl reread && sudo supervisorctl update
```

---

## 12. Stripe Webhook Registration

Once the site is live:
1. Go to Stripe Dashboard → Developers → Webhooks → Add endpoint
2. URL: `https://atletasperformancecenter.com/payments/webhook/`
3. Events to listen for: `payment_intent.succeeded`, `payment_intent.payment_failed`, `customer.subscription.updated`, `customer.subscription.deleted`, `charge.refunded`
4. Copy the signing secret → update `STRIPE_WEBHOOK_SECRET` in `.env`
5. `sudo supervisorctl restart atletasworld`

---

## 13. Post-Deploy Smoke Tests

- [ ] `https://atletasperformancecenter.com` loads home page with no mixed-content warnings
- [ ] HTTP redirects to HTTPS
- [ ] Login as Owner — portal loads, nav items correct
- [ ] Login as Coach — coach portal loads
- [ ] Login as Client — client portal loads
- [ ] Service catalog accessible at `/owner-portal/services/`
- [ ] Field/facility rental list and request flow works
- [ ] Static assets (CSS, JS, images) load from S3
- [ ] Django admin at `/admin/` is accessible
- [ ] Check `/var/log/atletasworld/error.log` — no critical errors
- [ ] Stripe test payment succeeds (use `4242 4242 4242 4242`)

---

## 14. Ongoing Deploys

```bash
cd /var/www/atletasworld
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
cd src
python manage.py migrate --noinput
python manage.py collectstatic --noinput
sudo supervisorctl restart atletasworld
```
