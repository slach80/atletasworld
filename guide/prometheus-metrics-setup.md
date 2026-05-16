# Prometheus Metrics Setup — atletasworld EC2

One-time setup to expose `/metrics` for the homelab monitoring dashboard.

## 1. SSH into the server

```bash
ssh -i ~/Documents/certs/atletasworld-prod.pem ubuntu@3.135.174.227
```

## 2. Install django-prometheus

```bash
cd /var/www/atletasworld
source venv/bin/activate
pip install django-prometheus==0.3.1
```

## 3. Deploy the updated code

The following files have already been updated in the repo:
- `src/atletasworld/settings.py` — added `django_prometheus` to INSTALLED_APPS, added middleware at top and bottom
- `src/atletasworld/urls.py` — added `django_prometheus.urls` include
- `requirements.txt` — added `django-prometheus==0.3.1`

Pull and restart:

```bash
cd /var/www/atletasworld
sudo -u www-data git pull
source venv/bin/activate
pip install -r requirements.txt
sudo supervisorctl restart atletasworld
```

## 4. Verify metrics endpoint is working

```bash
curl http://127.0.0.1:8000/metrics | head -20
```

Should return Prometheus text format starting with `# HELP python_gc_...`

## 5. Update Nginx to expose /metrics (IP-restricted)

Edit the Nginx config:

```bash
sudo nano /etc/nginx/sites-available/atletasworld
```

Add this block **before** the `location /` block:

```nginx
    location /metrics {
        allow 136.34.56.189;  # slach-den homelab public IP
        deny all;
        proxy_pass http://unix:/run/atletasworld/atletasworld.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
```

Test and reload:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

## 6. Verify from outside

From your Mac or slach-den:

```bash
curl https://atletasperformancecenter.com/metrics | head -20
```

Should return metrics. Any other IP gets 403.

## 7. EC2 Security Group

Port 443 is already open (HTTPS). No security group change needed — Nginx handles the IP restriction at the application layer.

## Done

Once `/metrics` is accessible, Prometheus on slach-office (192.168.1.70) will start scraping automatically. Check targets at:
http://192.168.1.70:9090/targets
