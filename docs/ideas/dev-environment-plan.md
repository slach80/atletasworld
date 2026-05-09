# Dev / Staging Environment Plan

## Current Setup
- **Prod**: EC2 t3.small (`i-080c6e77fb3d673a7`), us-east-2c, `3.135.174.227`
- **Local dev**: Django on `localhost:8001` — good for application code, no public URL

## When You Need a Dev Server

A staging instance becomes necessary for:
- Stripe webhook testing (needs a public URL for `stripe listen --forward-to`)
- Showing the client new features before they go live
- Testing Nginx/Gunicorn/SSL config changes safely
- Verifying migrations against a prod-like DB before running on prod

## Plan: AMI → t3.micro Dev Instance

### Steps
1. Create AMI snapshot from prod instance `i-080c6e77fb3d673a7`
2. Launch new **t3.micro** instance from the AMI (same AZ `us-east-2c`, same key pair `atletasworld-prod.pem`)
3. On the dev instance, update `/var/www/atletasworld/.env`:
   - `DEBUG=True`
   - `ALLOWED_HOSTS=<dev-ip>,localhost`
   - Stripe test keys (`pk_test_...`, `sk_test_...`) instead of live keys
4. No SSL required on dev — HTTP on port 80 is fine
5. Stop the instance when not in use to minimize cost

### Cost
| State | Cost |
|---|---|
| Running | ~$8/month (t3.micro) |
| Stopped | ~$0.10/month (EBS volume only) |

### Compared to Prod
| | Prod | Dev |
|---|---|---|
| Instance | t3.small | t3.micro |
| RAM | 2 GB | 1 GB |
| Cost (running) | ~$17/mo | ~$8/mo |
| SSL | Yes (Let's Encrypt) | No needed |
| Debug | False | True |
| Stripe keys | Live (`pk_live_`) | Test (`pk_test_`) |

## Alternative: Skip Dev Server, Use Local + Stripe CLI

For Stripe webhook testing specifically, the Stripe CLI can forward events to localhost — no public URL needed:

```bash
stripe listen --forward-to localhost:8001/payments/webhook/
```

This covers webhook dev work without spinning up a server. A staging instance is mainly useful for client demos and config testing.

## Trigger

Start with Option C (local dev) for Stripe pre-work (migrations, views, templates).
Spin up the dev instance when:
- Stripe keys arrive from the client, OR
- A feature is ready to demo to the client before going live
