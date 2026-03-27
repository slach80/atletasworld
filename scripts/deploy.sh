#!/bin/bash
# =============================================================================
# Atletas World — Server-Side Deploy Script
# Called by GitHub Actions via SSH on every push to main.
#
# Assumes server-setup.sh has already been run once.
# =============================================================================
set -euo pipefail

APP_DIR="/var/www/atletasworld"
VENV="$APP_DIR/venv/bin"
MANAGE="$VENV/python $APP_DIR/src/manage.py"

echo "[deploy] $(date '+%Y-%m-%d %H:%M:%S') — starting deploy"

echo "[deploy] Pulling latest code from main..."
cd "$APP_DIR"
git fetch origin main
git reset --hard origin/main

echo "[deploy] Installing/updating Python dependencies..."
"$VENV/pip" install --quiet -r requirements.txt

echo "[deploy] Running database migrations..."
cd "$APP_DIR/src"
$MANAGE migrate --noinput

echo "[deploy] Collecting static files..."
$MANAGE collectstatic --noinput --clear

echo "[deploy] Restarting application..."
sudo /usr/bin/supervisorctl restart atletasworld
sudo /usr/bin/supervisorctl restart atletasworld-celery

echo "[deploy] Checking service status..."
sudo /usr/bin/supervisorctl status

echo "[deploy] $(date '+%Y-%m-%d %H:%M:%S') — deploy complete"
