# EC2 vs Homelab Proxmox — Deployment Comparison for atletasworld

> Django 5.2 · Gunicorn · Postgres · Redis · Celery/beat · Stripe · Sendgrid · Twilio
> Produced: May 2026

---

## 1. Current EC2 Setup

### Instance Options

| Instance | vCPU | RAM | On-Demand (us-east-1, 2025) | 1-yr Reserved | Notes |
|---|---|---|---|---|---|
| t3.small | 2 | 2 GB | ~$0.0208/hr (~$15/mo) | ~$10/mo | Tight for Celery + Gunicorn + Redis |
| t3.medium | 2 | 4 GB | ~$0.0416/hr (~$30/mo) | ~$20/mo | Comfortable for full stack |
| t3.large | 2 | 8 GB | ~$0.0832/hr (~$60/mo) | ~$40/mo | Headroom for growth |

**Realistic choice for this stack: t3.medium** (4 GB RAM needed for Gunicorn workers + Celery + Redis on one box).

### What's Included with EC2

- Compute (CPU, RAM, ephemeral disk)
- 30 GB gp3 EBS root volume (~$2.40/mo)
- 100 GB outbound data free per month (after that ~$0.09/GB)
- A public IP (Elastic IP: $0 if attached, ~$3.65/mo if unattached)

### What's Extra

| Service | Self-hosted on EC2 | Managed AWS alternative | Monthly delta |
|---|---|---|---|
| Postgres | On-instance (free) | RDS db.t3.micro single-AZ | +$15–25/mo |
| Redis | On-instance (free) | ElastiCache cache.t3.micro | +$13–20/mo |
| Email | Sendgrid free (100/day) or $20/mo | SES ~$0.10/1000 emails | ~$0–20/mo |
| SSL/DNS | Certbot on EC2 (free) | ACM + Route53 | +$0.50/mo (Route53) |
| Backups | Manual cron to S3 | RDS automated snapshots | Included with RDS |
| Monitoring | CloudWatch basic (free) | CloudWatch detailed | +$3–10/mo |

### Typical Monthly Cost — EC2 Self-Hosted (everything on one box)

| Scenario | Components | Monthly Est. |
|---|---|---|
| Minimal viable | t3.small + 30 GB EBS + Elastic IP + S3 backup bucket | ~$20–25 |
| Recommended | t3.medium + 30 GB EBS + Elastic IP + S3 | ~$35–45 |
| Managed services | t3.medium + RDS t3.micro + ElastiCache + S3 | ~$75–100 |

**Current setup (supervisord + git pull deploy on EC2, no managed services): ~$35–50/mo total.**

---

## 2. Homelab Container Option

### Architecture on Proxmox

```
Proxmox cluster (existing, running 24/7)
└── New LXC or VM (e.g. CT450 on pve-04 or pve-05)
    └── Docker Compose stack
        ├── web         (Django + Gunicorn)
        ├── celery      (worker)
        ├── celery-beat (scheduler)
        ├── postgres    (persistent volume)
        ├── redis       (persistent volume)
        └── nginx       (reverse proxy + SSL termination)
```

### Inbound Traffic Options

**Option A: Cloudflare Tunnel (recommended)**
- Install `cloudflared` daemon in the LXC
- Zero open ports on router/firewall
- Cloudflare handles TLS, DDoS protection, and acts as CDN
- Free tier is sufficient for low-medium traffic
- Stripe webhooks work fine (Cloudflare passes POST bodies)
- Latency: +10–30ms vs direct (usually acceptable)

**Option B: Direct port-forward (80/443 on router)**
- Port-forward 443 on home router to Proxmox node IP
- nginx inside LXC handles Let's Encrypt via certbot
- Requires static/stable home IP or dynamic DNS (e.g. Cloudflare DDNS)
- Exposes home IP to internet — less ideal but workable
- Lower latency than tunnel

**Option C: Tailscale + Cloudflare for public endpoints**
- Use Tailscale for SSH/admin access
- Cloudflare tunnel only for public HTTPS traffic
- Best security posture, no home IP exposure

### Docker Compose Structure

```yaml
services:
  web:
    build: .
    command: gunicorn atletasworld.wsgi:application --bind 0.0.0.0:8000 --workers 3
    env_file: .env
    depends_on: [postgres, redis]
    volumes:
      - static_files:/app/staticfiles
      - media_files:/app/media

  celery:
    build: .
    command: celery -A atletasworld worker -l info
    env_file: .env
    depends_on: [postgres, redis]

  celery-beat:
    build: .
    command: celery -A atletasworld beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
    env_file: .env
    depends_on: [postgres, redis]

  postgres:
    image: postgres:16-alpine
    volumes:
      - postgres_data:/var/lib/postgresql/data
    env_file: .env

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf
      - static_files:/var/www/static
      - media_files:/var/www/media
      - /etc/letsencrypt:/etc/letsencrypt:ro
    depends_on: [web]

volumes:
  postgres_data:
  redis_data:
  static_files:
  media_files:
```

---

## 3. Pro/Cons Comparison Table

| Dimension | EC2 (current) | Homelab Proxmox |
|---|---|---|
| **Cost** | $35–50/mo (realistic) | ~$3–5/mo marginal |
| **Reliability/Uptime** | AWS SLA 99.99%, automatic AZ failover possible | Home ISP dependent. Mitigated by existing monitoring stack. |
| **Maintenance burden** | OS patching, supervisord, manual scaling | Docker isolation is cleaner. Still need host OS + Docker updates. |
| **Scalability** | Easy vertical/horizontal scale in AWS console | Limited by Proxmox cluster capacity. |
| **Security** | AWS Security Groups, IAM, VPC isolation | UFW + Cloudflare tunnel removes open ports. Home network shared-trust boundary. |
| **Ease of deploy** | Git pull via GH Actions (already working) | Same pattern. Docker adds image build step. |
| **Backup story** | S3 via cron (works) | Explicit pg_dump cron + Proxmox PBS snapshot + offsite (B2/NAS). |
| **Stripe webhooks** | Direct HTTPS to EC2 | Works via Cloudflare tunnel. Update endpoint URL in dashboard. |
| **SSL/TLS** | Certbot on EC2 or ACM | Let's Encrypt or Cloudflare proxy |
| **Observability** | CloudWatch (basic free) | Prometheus + Grafana already on CT301 — native fit |
| **Data sovereignty** | AWS region | On-premises — full control |
| **ISP outage risk** | None | Home ISP down = app down. ~44 hrs/yr for typical cable ISP. |

---

## 4. Cost Comparison

### EC2 Monthly (2025/2026 us-east-1 pricing)

| Tier | Setup | Monthly |
|---|---|---|
| Minimal | t3.small, all-in-one, S3 backups | $22–28 |
| Recommended | t3.medium, all-in-one, S3 backups, Elastic IP | $38–48 |
| Managed | t3.medium + RDS t3.micro + ElastiCache + S3 | $80–110 |

### Homelab Monthly

| Component | Cost |
|---|---|
| Proxmox cluster (already running) | $0 marginal |
| New LXC/VM compute | $0 (spare capacity exists) |
| Storage for Postgres data volume | $0 (NAS/local SSD) |
| Cloudflare tunnel | $0 (free tier) |
| Domain renewal amortized | ~$1/mo |
| Power delta for one LXC (est. 5–10W) | ~$0.50–1.00/mo |
| Backblaze B2 offsite pg_dump (~10 GB) | ~$0.50–2/mo |
| **Total marginal** | **~$3–5/mo** |

**Annual savings vs EC2 recommended: ~$400–520/yr.**

### Hidden costs

- Your time: homelab setup is a one-time ~4–8 hour project
- Risk cost of downtime: 1 hour down during peak = lost new bookings (existing bookings safe in DB)
- ISP reliability: ~44 hrs/yr downtime for typical cable vs EC2's ~53 min/yr SLA

---

## 5. Recommendation

**For a single-operator, low-medium traffic sports booking SaaS: migrate to homelab.**

### Why homelab wins here

1. **$400–520/yr saving** is real money for a bootstrapped SaaS
2. **Homelab already has reliability infrastructure** — 6-node Proxmox cluster, Prometheus + Grafana on CT301, 24/7 uptime for existing services
3. **Docker Compose is a clean upgrade from supervisord** — easier rollbacks, cleaner environment isolation
4. **Cloudflare tunnel eliminates home-IP exposure** and adds free CDN/DDoS layer
5. **Booking SaaS failure modes are tolerable**: existing bookings survive an outage; only new booking creation is blocked

### When to stay on EC2

- Paying clients with explicit SLA requirements
- Planning for 50+ concurrent users in next 6 months
- Cannot tolerate any unplanned downtime

### Hybrid option (recommended initially)

Keep EC2 as a **cold standby** (stopped instance = ~$2.50/mo for EBS only). Run on homelab day-to-day. If homelab outage > 30 min, start EC2, point DNS, restore from latest pg_dump.

**Total cost with hybrid: ~$5–8/mo with manual failover.**

---

## 6. Migration Path: EC2 → Homelab

### Pre-migration checklist

- [ ] Provision new LXC on Proxmox (Ubuntu 22.04 or Debian 12, 2 vCPU, 4 GB RAM, 40 GB disk)
- [ ] Install Docker Engine + Docker Compose plugin on LXC
- [ ] Set up Cloudflare tunnel and verify HTTPS reaches the LXC
- [ ] Build `docker-compose.prod.yml` for atletasworld (Gunicorn + Nginx + Postgres + Redis + Celery)
- [ ] Configure GitHub Actions deploy workflow targeting homelab SSH (or self-hosted runner in LXC)
- [ ] Test full stack on homelab with staging subdomain (e.g. `staging.atletasworld.com`)
- [ ] Lower DNS TTL to 60 seconds 24 hours before cutover

### Step-by-step cutover

**Step 1: Dump Postgres from EC2**

```bash
# On EC2
pg_dump -U atletasworld -d atletasworld_prod -F c -f /tmp/atletasworld_$(date +%Y%m%d).dump
scp /tmp/atletasworld_20260521.dump user@homelab:/opt/atletasworld/backups/
```

**Step 2: Restore on homelab**

```bash
docker compose exec -T postgres pg_restore \
  -U atletasworld -d atletasworld_prod \
  /backups/atletasworld_20260521.dump
```

**Step 3: Sync media files**

```bash
rsync -avz --progress ec2-user@EC2_IP:/var/www/atletasworld/media/ /opt/atletasworld/media/
```

**Step 4: Verify homelab stack**

```bash
docker compose up -d
docker compose exec web python manage.py check --deploy
docker compose exec web python manage.py migrate --run-syncdb
# Smoke test: login, create a booking, check Celery receives tasks
```

**Step 5: Update Stripe webhook**

- Stripe Dashboard → Developers → Webhooks → edit endpoint URL
- Copy new webhook signing secret into homelab `.env`
- Update `STRIPE_WEBHOOK_SECRET`

**Step 6: DNS cutover**

```bash
# Point atletasworld.com CNAME to Cloudflare tunnel ID
# OR A record to homelab public IP
dig atletasworld.com +short
curl -I https://atletasworld.com/health/
```

**Step 7: Update .env on homelab**

```bash
DATABASE_URL=postgresql://atletasworld:password@postgres:5432/atletasworld_prod
REDIS_URL=redis://redis:6379/0
ALLOWED_HOSTS=atletasworld.com,www.atletasworld.com
CSRF_TRUSTED_ORIGINS=https://atletasworld.com,https://www.atletasworld.com
STRIPE_WEBHOOK_SECRET=whsec_new_value_from_dashboard
```

**Step 8: Monitor 48 hours**

- Prometheus/Grafana on CT301 for Django errors, Celery queue depth, Postgres connections
- Cloudflare analytics for request counts
- Keep EC2 stopped (not terminated) for 1 week as fallback

**Step 9: Final cleanup (after 1 week)**

```bash
# Terminate EC2 instance, delete EBS volume, release Elastic IP
# Keep S3 bucket for historical backups
```

### Backup cron for homelab LXC

```bash
# Daily Postgres dump to NAS (mount /mnt/nas/backups in LXC)
0 2 * * * docker exec atletasworld_postgres_1 pg_dump -U atletasworld atletasworld_prod \
  | gzip > /mnt/nas/backups/atletasworld_$(date +\%Y\%m\%d).sql.gz

# Weekly sync to Backblaze B2
0 3 * * 0 rclone sync /mnt/nas/backups/ b2:atletasworld-backups/
```

### Proxmox PBS snapshot

```
Datacenter → Backup → Add job
  Storage: PBS
  Schedule: daily 03:00
  Mode: snapshot
  Node: pve-0x (wherever LXC lives)
  Retention: 7 daily, 4 weekly
```

---

## Rollback plan

If DNS cutover fails:
1. Flip DNS back to EC2 IP (TTL=60s propagates in ~60 seconds)
2. Start EC2 instance if stopped
3. Restore Postgres from dump taken in Step 1
4. Update Stripe webhook back to EC2 URL

**Data loss window**: transactions between the pg_dump and the DNS flip — typically < 5 min if you minimize gap.

---

*Pricing based on AWS us-east-1 on-demand rates as of Q1 2026. Verify at https://aws.amazon.com/ec2/pricing/on-demand/ before budgeting.*
