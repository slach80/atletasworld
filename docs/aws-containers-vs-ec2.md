# EC2 vs AWS Container Options — Deployment Comparison for atletasworld

> Django 5.2 · Gunicorn · Postgres · Redis · Celery/beat · Stripe · Sendgrid · Twilio
> Produced: May 2026

---

## 1. Current Baseline: EC2 + supervisord

### Setup
Single t3.medium EC2 instance running everything (Django/Gunicorn, Celery worker, Celery-beat, Postgres, Redis) managed by supervisord. Deployments via `git pull` on the instance.

### Cost (us-east-1, 2026)

| Component | Monthly |
|---|---|
| t3.medium on-demand | ~$30 |
| 30 GB gp3 EBS | ~$2.40 |
| Elastic IP | ~$3.65 |
| S3 backups | ~$1 |
| Data transfer (100 GB free) | ~$0 |
| **Total** | **~$37–45** |

With 1-year Reserved Instance: ~$22–28/mo.

### Pros
- Lowest cost
- Simplest ops — one server, SSH in, look at logs
- Zero cold-start latency
- Already working

### Cons
- No isolation between processes (one OOM kill takes everything down)
- Scaling means SSH + manual changes
- Deployments require downtime or careful supervisord restarts
- Mixing app server + DB on one box is risky at scale
- No built-in rollback
- Manual patching burden

---

## 2. ECS Fargate (Serverless Containers)

### What it is
AWS manages the underlying EC2 fleet. You define tasks (CPU/memory), push Docker images, ECS schedules them. No instances to patch.

### Architecture for atletasworld

```
ECR (container registry)
  └── docker images: web, celery, celery-beat

ECS Cluster (Fargate)
  ├── Service: web       (1–N tasks, 0.5 vCPU / 1 GB each)
  ├── Service: celery    (1–N tasks, 0.5 vCPU / 1 GB each)
  └── Task (one-off):    celery-beat (always 1 task, NEVER scaled)

RDS (Postgres)            ← separate managed service
ElastiCache (Redis)       ← separate managed service
ALB (Application Load Balancer)
```

### Key constraints

**Celery-beat must run exactly 1 instance.** Scale it to 2 and you get duplicate scheduled jobs. Use a dedicated ECS service with `desiredCount=1` and do NOT put it behind auto-scaling.

**DB migrations must NOT run at container startup.** With multiple web tasks starting simultaneously, parallel migrations cause race conditions and lock errors. Run migrations as a one-off ECS task before deploying the new service version:
```bash
aws ecs run-task \
  --cluster atletasworld \
  --launch-type FARGATE \
  --task-definition atletasworld-migrate \
  --overrides '{"containerOverrides":[{"name":"web","command":["python","manage.py","migrate","--noinput"]}]}'
```
Wait for it to exit 0, then update the service.

### Cost breakdown

#### Option A: Private subnets + NAT Gateway (avoid this)

| Component | Monthly |
|---|---|
| NAT Gateway (1 AZ) | $32.85 base + data |
| Fargate web (0.5 vCPU / 1 GB, 1 task) | ~$15 |
| Fargate celery (0.5 vCPU / 1 GB, 1 task) | ~$15 |
| Fargate celery-beat (0.25 vCPU / 0.5 GB) | ~$7 |
| RDS db.t3.micro (single-AZ) | ~$15 |
| ElastiCache cache.t3.micro | ~$13 |
| ALB | ~$16 |
| ECR storage | ~$1 |
| **Total** | **~$115–145** |

The NAT Gateway alone is $33/mo. This is the #1 cost trap in Fargate.

#### Option B: Public subnets (recommended for small SaaS)

Fargate tasks get public IPs directly. No NAT Gateway needed. Security Groups still restrict access (only ALB → web tasks, only web+celery → RDS/Redis).

| Component | Monthly |
|---|---|
| Fargate web (0.5 vCPU / 1 GB, 1 task) | ~$15 |
| Fargate celery (0.5 vCPU / 1 GB, 1 task) | ~$15 |
| Fargate celery-beat (0.25 vCPU / 0.5 GB) | ~$7 |
| RDS db.t3.micro (single-AZ) | ~$15 |
| ElastiCache cache.t3.micro | ~$13 |
| ALB | ~$16 |
| ECR storage | ~$1 |
| **Total** | **~$82–95** |

### Pros
- No EC2 instances to patch
- Auto-scaling web and celery workers independently
- Clean Docker image rollbacks (point service to previous image)
- Native CloudWatch log groups per task
- Blue/green deployments with CodeDeploy integration
- Celery and web fully isolated (one can OOM without killing the other)

### Cons
- ~2x cost of EC2 self-hosted
- Cold starts when scaling from 0 (not an issue if `desiredCount >= 1`)
- Postgres and Redis are still separate line items (RDS + ElastiCache)
- Slightly more operational surface than EC2 (task definitions, services, ALB rules, ECR)
- Fargate does not support persistent volumes — media files need S3

---

## 3. ECS on EC2 (Managed Cluster, Your Instances)

### What it is
ECS orchestration, but you provision and manage the underlying EC2 instances. You pay for EC2 capacity whether tasks are running or not.

### Architecture
Same as Fargate but with an EC2 Auto Scaling Group providing the capacity. ECS agent on each instance schedules containers.

### Cost (2 × t3.medium instances for HA)

| Component | Monthly |
|---|---|
| 2 × t3.medium On-Demand | ~$60 |
| RDS db.t3.micro | ~$15 |
| ElastiCache cache.t3.micro | ~$13 |
| ALB | ~$16 |
| ECR | ~$1 |
| **Total** | **~$105–125** |

Can reduce to ~$72/mo with 1-year Reserved Instances for the EC2 fleet.

### Pros
- Cheaper than Fargate when instances are fully utilized
- Can use Spot Instances for celery workers (tolerate interruption)
- Supports EFS for persistent volumes (unlike Fargate without extra config)
- Familiar EC2 capacity model

### Cons
- Still need to patch EC2 instances (OS, ECS agent)
- Over-provisioned capacity when load is low
- More complex than Fargate (capacity planning + task scheduling)
- No meaningful advantage over Fargate for this stack size

### Verdict: skip for atletasworld. ECS on EC2 is the worst of both worlds at this scale — you pay for EC2 overhead and still get containers, but without Fargate's simplicity.

---

## 4. EKS (Kubernetes)

### Cost floor

| Component | Monthly |
|---|---|
| EKS control plane | **$73.00** (fixed, no exceptions) |
| 2 × t3.medium workers | ~$60 |
| RDS + ElastiCache + ALB | ~$44 |
| **Total** | **~$177–240** |

$73/mo just for the control plane exists even if you run zero pods.

### Verdict: Do not use EKS for atletasworld.

EKS makes sense at 10+ services with dedicated platform engineers. For a single Django app with 3 process types, Kubernetes adds massive operational complexity with no benefit. The $73/mo control plane floor alone makes it ~2.5× more expensive than Fargate with no upside.

---

## 5. Comparison Table

| Dimension | EC2 + supervisord | ECS Fargate (public subnets) | ECS on EC2 | EKS |
|---|---|---|---|---|
| **Monthly cost** | $37–45 ($22 reserved) | ~$85–95 | ~$105–125 | ~$177–240 |
| **Ops complexity** | Low (one server) | Medium (task defs, ECR, ALB) | Medium-High | Very High |
| **Patching burden** | Manual OS + deps | None (Fargate serverless) | EC2 patching | EC2 + K8s patching |
| **Process isolation** | None (supervisord) | Full (separate tasks) | Full | Full |
| **Scaling** | Manual (SSH) | Auto-scale per service | Auto-scale + capacity planning | HPA + cluster autoscaler |
| **Rollback** | Git reset + restart | Point service to prev image | Same as Fargate | Same |
| **Celery-beat safety** | 1 process by design | Must set `desiredCount=1` | Same | Must use leader election |
| **DB migrations** | Run on deploy | One-off ECS task first | Same | Init container / hook |
| **Media files** | Local disk | S3 required | S3 or EFS | S3 or EFS |
| **Cold starts** | None | ~5–10s (if scaling from 0) | ~5–10s | ~30–60s (node scale-up) |
| **Stripe webhooks** | Direct to EC2 IP | ALB → ECS task | Same | Same |
| **Logs** | Manual tail/grep | CloudWatch Logs (automatic) | Same | Same |
| **SSL/TLS** | Certbot on EC2 | ACM on ALB (free, auto-renew) | Same | Same |
| **Right for this app?** | Yes (current) | **Yes (recommended upgrade)** | No | No |

---

## 6. Recommendation

**Stay on EC2 until revenue justifies the move. Migrate to ECS Fargate (public subnets) when any of these trigger:**

- Celery worker OOM kills are taking down the web process
- You need zero-downtime deploys
- You're spending > 4 hours/month on manual ops
- Monthly revenue > $500 (the $50/mo premium is then < 10% of revenue)

### Why ECS Fargate over ECS on EC2 or EKS

1. **No servers to patch** — biggest operational win for a solo operator
2. **Process isolation is real** — celery worker OOM does not affect web
3. **~$85/mo with public subnets** — NAT Gateway is avoidable, making it only $40–50 more than EC2
4. **Rollbacks are fast** — `aws ecs update-service --task-definition arn:...:42` — no SSH
5. **ACM handles SSL** — free TLS cert, auto-renews, attached to ALB

### Cost reality check

| Setup | Monthly | Annual |
|---|---|---|
| EC2 t3.medium on-demand | ~$42 | ~$504 |
| EC2 t3.medium 1-yr reserved | ~$25 | ~$300 |
| ECS Fargate (public subnets) | ~$90 | ~$1,080 |
| ECS Fargate (private + NAT) | ~$130 | ~$1,560 |
| EKS | ~$200 | ~$2,400 |

Fargate premium over reserved EC2: ~$65/mo (~$780/yr). That's the price of not patching servers and getting proper isolation.

---

## 7. Migration Path: EC2 → ECS Fargate

### Phase 1: Containerize (1–2 hours)

Create `Dockerfile` and `docker-compose.prod.yml` (already have dev version). Add `.dockerignore`.

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ .
RUN python manage.py collectstatic --noinput
CMD ["gunicorn", "atletasworld.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
```

### Phase 2: ECR + RDS + ElastiCache (2–3 hours)

```bash
# Create ECR repo
aws ecr create-repository --repository-name atletasworld

# Push image
aws ecr get-login-password | docker login --username AWS --password-stdin $ECR_URI
docker build -t atletasworld .
docker tag atletasworld:latest $ECR_URI/atletasworld:latest
docker push $ECR_URI/atletasworld:latest

# Create RDS (migrate from on-EC2 Postgres)
aws rds create-db-instance \
  --db-instance-identifier atletasworld-prod \
  --db-instance-class db.t3.micro \
  --engine postgres \
  --master-username atletasworld \
  --master-user-password $DB_PASSWORD \
  --allocated-storage 20 \
  --no-multi-az
```

Dump and restore Postgres:
```bash
# From EC2
pg_dump -U atletasworld -d atletasworld_prod -F c -f /tmp/atletasworld.dump

# To RDS
pg_restore -h $RDS_ENDPOINT -U atletasworld -d atletasworld_prod /tmp/atletasworld.dump
```

### Phase 3: ECS Task Definitions (1–2 hours)

Three task definitions: `atletasworld-web`, `atletasworld-celery`, `atletasworld-beat`.

All share the same container image. `web` runs gunicorn, `celery` runs `celery -A atletasworld worker`, `beat` runs `celery -A atletasworld beat`.

Secrets (DATABASE_URL, STRIPE_SECRET_KEY, etc.) stored in AWS Secrets Manager or Parameter Store — never in task definition plaintext.

### Phase 4: ECS Services + ALB (1–2 hours)

```bash
# Create cluster
aws ecs create-cluster --cluster-name atletasworld

# Create services
aws ecs create-service --cluster atletasworld \
  --service-name web --task-definition atletasworld-web \
  --desired-count 1 --launch-type FARGATE \
  --load-balancers targetGroupArn=$TG_ARN,containerName=web,containerPort=8000

aws ecs create-service --cluster atletasworld \
  --service-name celery --task-definition atletasworld-celery \
  --desired-count 1 --launch-type FARGATE

aws ecs create-service --cluster atletasworld \
  --service-name celery-beat --task-definition atletasworld-beat \
  --desired-count 1 --launch-type FARGATE
  # WARNING: never add auto-scaling to celery-beat
```

### Phase 5: CI/CD Update + DNS Cutover

Update GitHub Actions to:
1. Build + push Docker image to ECR
2. Run migration as one-off ECS task (wait for exit 0)
3. `aws ecs update-service --force-new-deployment` for web and celery

DNS cutover: point `atletasworld.com` CNAME or A record to ALB DNS name. Lower TTL to 60s 24h before.

Update Stripe webhook endpoint URL in dashboard to `https://atletasworld.com/payments/webhook/`.

### Deployment pipeline (GitHub Actions)

```yaml
- name: Run migrations
  run: |
    TASK_ARN=$(aws ecs run-task \
      --cluster atletasworld \
      --launch-type FARGATE \
      --task-definition atletasworld-web \
      --overrides '{"containerOverrides":[{"name":"web","command":["python","manage.py","migrate","--noinput"]}]}' \
      --query 'tasks[0].taskArn' --output text)
    aws ecs wait tasks-stopped --cluster atletasworld --tasks $TASK_ARN
    EXIT=$(aws ecs describe-tasks --cluster atletasworld --tasks $TASK_ARN \
      --query 'tasks[0].containers[0].exitCode' --output text)
    [ "$EXIT" = "0" ] || (echo "Migration failed" && exit 1)

- name: Deploy web
  run: |
    aws ecs update-service --cluster atletasworld \
      --service web --force-new-deployment
```

---

## 8. Key Gotchas Summary

| Gotcha | Detail |
|---|---|
| **NAT Gateway costs $33/mo baseline** | Use public subnets to avoid it; Security Groups still protect the tasks |
| **EKS costs $73/mo just for control plane** | Never the right call for a single Django app |
| **Never scale celery-beat** | `desiredCount=1`, no auto-scaling — duplicate beats cause duplicate jobs |
| **Migrations race in ECS** | Must run as one-off task before service update, not at container startup |
| **Media files need S3 with Fargate** | Local disk is ephemeral; use `django-storages` + S3 for `MEDIA_ROOT` |
| **Secrets in Secrets Manager** | Never put DATABASE_URL or STRIPE_SECRET_KEY in task definition plaintext |
| **ALB idle timeout** | Default 60s; increase to 300s if Stripe webhooks or long requests time out |
| **ECS service minimum healthy %** | Default 100% — means new task must start before old stops; requires 2× capacity briefly |

---

## 9. Media Files on ECS Fargate

Fargate task storage is ephemeral. Uploaded files (player photos, documents) written to local disk disappear when the task restarts.

Required changes:
1. Add `django-storages` and `boto3` to requirements
2. Set `DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'`
3. Set `AWS_STORAGE_BUCKET_NAME`, `AWS_S3_REGION_NAME`
4. Use IAM role attached to the ECS task (not hardcoded keys)

---

*AWS pricing based on us-east-1 on-demand rates as of Q1 2026. Verify at https://aws.amazon.com/ecs/pricing/ and https://aws.amazon.com/fargate/pricing/ before budgeting.*
