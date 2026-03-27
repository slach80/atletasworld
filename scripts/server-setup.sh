#!/bin/bash
# =============================================================================
# Atletas World — One-Time EC2 Server Setup
# Run once on a fresh Ubuntu 22.04 LTS instance.
#
# Usage:
#   chmod +x server-setup.sh
#   sudo ./server-setup.sh
#
# After running this script:
#   1. Copy your .env file to /var/www/atletasworld/.env
#   2. Add EC2 public key to /home/ubuntu/.ssh/authorized_keys (GitHub deploy key)
#   3. Set up Nginx SSL: sudo certbot --nginx -d atletasperformancecenter.com
#   4. Start services: sudo supervisorctl start atletasworld
# =============================================================================
set -euo pipefail

REPO_URL="https://github.com/slach80/atletasworld.git"
APP_DIR="/var/www/atletasworld"
APP_USER="ubuntu"
PYTHON="python3"
LOG_DIR="/var/log/atletasworld"
SOCK_DIR="/run/atletasworld"

echo "==> [1/9] System packages"
apt update && apt upgrade -y
apt install -y \
    python3 python3-venv python3-pip python3-full \
    nginx supervisor git \
    postgresql-client \
    redis-server \
    certbot python3-certbot-nginx \
    curl unzip

echo "==> [2/9] Create app directory"
mkdir -p "$APP_DIR" "$LOG_DIR" "$SOCK_DIR"
chown -R "$APP_USER:$APP_USER" "$APP_DIR" "$LOG_DIR" "$SOCK_DIR"

echo "==> [3/9] Clone repository"
sudo -u "$APP_USER" git clone "$REPO_URL" "$APP_DIR"

echo "==> [4/9] Python virtual environment"
sudo -u "$APP_USER" $PYTHON -m venv "$APP_DIR/venv"
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "==> [5/9] Supervisor config — Gunicorn"
cat > /etc/supervisor/conf.d/atletasworld.conf << 'EOF'
[program:atletasworld]
command=/var/www/atletasworld/venv/bin/gunicorn
    --workers 3
    --bind unix:/run/atletasworld/atletasworld.sock
    --access-logfile /var/log/atletasworld/access.log
    --error-logfile /var/log/atletasworld/error.log
    --timeout 60
    atletasworld.wsgi:application
directory=/var/www/atletasworld/src
user=ubuntu
autostart=true
autorestart=true
redirect_stderr=true
environment=
    HOME="/home/ubuntu",
    USER="ubuntu"

[program:atletasworld-celery]
command=/var/www/atletasworld/venv/bin/celery
    -A atletasworld worker
    --loglevel=info
    --logfile=/var/log/atletasworld/celery.log
    --concurrency=2
directory=/var/www/atletasworld/src
user=ubuntu
autostart=true
autorestart=true
redirect_stderr=true
stopasgroup=true
killasgroup=true
environment=
    HOME="/home/ubuntu",
    USER="ubuntu"
EOF

echo "==> [6/9] Nginx config"
cat > /etc/nginx/sites-available/atletasworld << 'EOF'
server {
    listen 80;
    server_name atletasperformancecenter.com www.atletasperformancecenter.com;

    client_max_body_size 20M;

    # Static files served directly by Nginx (fallback if not using S3)
    location /static/ {
        alias /var/www/atletasworld/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location /media/ {
        alias /var/www/atletasworld/media/;
        expires 7d;
    }

    location / {
        proxy_pass http://unix:/run/atletasworld/atletasworld.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }
}
EOF

# Enable site, remove default
ln -sf /etc/nginx/sites-available/atletasworld /etc/nginx/sites-enabled/atletasworld
rm -f /etc/nginx/sites-enabled/default
nginx -t

echo "==> [7/9] sudoers — allow ubuntu to restart supervisor without password"
# GitHub Actions deploy needs to restart services via sudo
echo "ubuntu ALL=(ALL) NOPASSWD: /usr/bin/supervisorctl restart atletasworld, /usr/bin/supervisorctl restart atletasworld-celery, /usr/bin/supervisorctl status" \
    > /etc/sudoers.d/atletasworld
chmod 440 /etc/sudoers.d/atletasworld

echo "==> [8/9] Enable and start services"
systemctl enable redis-server && systemctl start redis-server
systemctl enable supervisor && systemctl start supervisor
supervisorctl reread && supervisorctl update
systemctl enable nginx && systemctl start nginx

echo "==> [9/9] Create staticfiles and media directories"
mkdir -p "$APP_DIR/staticfiles" "$APP_DIR/media"
chown -R "$APP_USER:$APP_USER" "$APP_DIR/staticfiles" "$APP_DIR/media"

echo ""
echo "============================================================"
echo "  Server setup complete!"
echo "============================================================"
echo ""
echo "  Next steps:"
echo "  1. Copy .env to $APP_DIR/.env"
echo "  2. Run initial migrations:"
echo "     sudo -u ubuntu $APP_DIR/venv/bin/python $APP_DIR/src/manage.py migrate"
echo "  3. Create superuser:"
echo "     sudo -u ubuntu $APP_DIR/venv/bin/python $APP_DIR/src/manage.py createsuperuser"
echo "  4. Collect static files:"
echo "     sudo -u ubuntu $APP_DIR/venv/bin/python $APP_DIR/src/manage.py collectstatic --noinput"
echo "  5. Start app: sudo supervisorctl start atletasworld atletasworld-celery"
echo "  6. Set up SSL: sudo certbot --nginx -d atletasperformancecenter.com -d www.atletasperformancecenter.com"
echo ""
