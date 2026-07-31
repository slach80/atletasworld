#!/usr/bin/env bash
# Runs on Unraid — pulls DB from EC2, writes hourly copies to Unraid,
# then syncs daily snapshots to LACHNAS (/mnt/lachnas_backups).
#
# Retention:
#   Unraid  (/mnt/user/backup/atletasworld/)   hourly, 3 days (72 files)
#   LACHNAS (/mnt/lachnas_backups/atletasworld/) daily,  7 days
#
# One-time setup on Unraid:
#   1. Copy EC2 deploy key:
#        mkdir -p /root/.ssh
#        scp slach@192.168.1.92:~/Documents/certs/atletasworld-deploy-key \
#            root@192.168.1.40:/root/.ssh/atletasworld-deploy-key
#        # (or copy manually via Unraid terminal)
#        chmod 600 /root/.ssh/atletasworld-deploy-key
#   2. Smoke-test SSH:
#        ssh -i /root/.ssh/atletasworld-deploy-key ubuntu@3.135.174.227 "echo ok"
#   3. Copy this script to Unraid:
#        scp scripts/unraid-pull-backup.sh root@192.168.1.40:/root/scripts/unraid-pull-backup.sh
#        ssh root@192.168.1.40 "chmod +x /root/scripts/unraid-pull-backup.sh"
#   4. Add to Unraid cron (Settings → Scheduler, or edit /etc/cron.d/):
#        0 * * * * /root/scripts/unraid-pull-backup.sh >> /var/log/atletasworld-backup.log 2>&1

set -euo pipefail

EC2_HOST="ubuntu@3.135.174.227"
EC2_KEY="/root/.ssh/atletasworld-deploy-key"

HOURLY_DIR="/mnt/user/backup/atletasworld/hourly"
DAILY_DIR="/mnt/lachnas_backups/atletasworld/daily"

HOURLY_KEEP_DAYS=3
DAILY_KEEP_DAYS=7

mkdir -p "$HOURLY_DIR" "$DAILY_DIR"

TIMESTAMP=$(date +%F-%H%M)
HOURLY_DEST="$HOURLY_DIR/db-${TIMESTAMP}.sqlite3"
DATE_ONLY=$(date +%F)
DAILY_DEST="$DAILY_DIR/db-${DATE_ONLY}.sqlite3"

echo "[$(date)] Triggering backup on EC2..."
ssh -i "$EC2_KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=15 "$EC2_HOST" \
    "/var/www/atletasworld/scripts/backup-db.sh" > /dev/null

echo "[$(date)] Pulling backup..."
scp -i "$EC2_KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=15 \
    "${EC2_HOST}:/tmp/atletasworld-db-backup.sqlite3" \
    "$HOURLY_DEST"

SIZE=$(du -sh "$HOURLY_DEST" | cut -f1)
echo "Hourly saved: $HOURLY_DEST ($SIZE)"

# Write daily snapshot to LACHNAS (overwrite same-day file if re-run)
cp "$HOURLY_DEST" "$DAILY_DEST"
echo "Daily saved:  $DAILY_DEST ($SIZE)"

# Prune hourly backups older than HOURLY_KEEP_DAYS
find "$HOURLY_DIR" -name "db-*.sqlite3" -mtime +${HOURLY_KEEP_DAYS} -delete

# Prune daily backups older than DAILY_KEEP_DAYS
find "$DAILY_DIR" -name "db-*.sqlite3" -mtime +${DAILY_KEEP_DAYS} -delete

echo "[$(date)] Done."
