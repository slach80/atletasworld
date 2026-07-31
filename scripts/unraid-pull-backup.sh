#!/usr/bin/env bash
# Runs on Unraid — pulls the latest DB backup from EC2 via SSH.
#
# Setup (run once on Unraid):
#   1. Copy your EC2 key to Unraid:
#      scp ~/Documents/certs/atletasworld-deploy-key root@192.168.1.40:/root/.ssh/atletasworld-deploy-key
#      chmod 600 /root/.ssh/atletasworld-deploy-key
#   2. Test access:
#      ssh -i /root/.ssh/atletasworld-deploy-key ubuntu@3.135.174.227 "ls /var/www/atletasworld/backups/"
#   3. Create local backup dir on Unraid (adjust share path as needed):
#      mkdir -p /mnt/user/backup/atletasworld
#   4. Add to Unraid cron (Settings → Scheduler, or /etc/cron.d/atletasworld-backup):
#      0 */2 * * * /root/scripts/unraid-pull-backup.sh >> /var/log/atletasworld-backup.log 2>&1
#
# This pulls every 2 hours. Adjust cron interval to taste.

set -euo pipefail

EC2_HOST="ubuntu@3.135.174.227"
EC2_KEY="/root/.ssh/atletasworld-deploy-key"
EC2_BACKUP_DIR="/var/www/atletasworld/backups"
LOCAL_DIR="/mnt/user/backup/atletasworld"
KEEP_DAYS=30

mkdir -p "$LOCAL_DIR"

TIMESTAMP=$(date +%F-%H%M)
DEST="$LOCAL_DIR/db-${TIMESTAMP}.sqlite3"

echo "[$(date)] Pulling backup from EC2..."

# Ensure a fresh backup exists on EC2 first
ssh -i "$EC2_KEY" -o StrictHostKeyChecking=no "$EC2_HOST" \
    "/var/www/atletasworld/scripts/backup-db.sh"

# Pull it
scp -i "$EC2_KEY" -o StrictHostKeyChecking=no \
    "${EC2_HOST}:${EC2_BACKUP_DIR}/db-latest.sqlite3" \
    "$DEST"

echo "Saved: $DEST ($(du -sh "$DEST" | cut -f1))"

# Keep a stable latest copy
ln -sf "$DEST" "$LOCAL_DIR/db-latest.sqlite3"

# Prune old Unraid backups
find "$LOCAL_DIR" -name "db-*.sqlite3" -mtime +${KEEP_DAYS} -delete

echo "[$(date)] Done. Unraid backup: $DEST"
