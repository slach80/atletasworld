#!/usr/bin/env bash
# Run on EC2 via cron every 15-60 min, e.g.:
#   */30 * * * * /var/www/atletasworld/scripts/backup-db.sh >> /var/log/atletasworld/backup.log 2>&1
set -euo pipefail

DB_PATH="/var/www/atletasworld/src/db.sqlite3"
BUCKET="${BACKUP_S3_BUCKET:-}"   # set in environment or crontab
TIMESTAMP=$(date +%F-%H%M)
TMP="/tmp/db-${TIMESTAMP}.sqlite3"

if [ ! -f "$DB_PATH" ]; then
    echo "ERROR: DB not found at $DB_PATH"
    exit 1
fi

# Hot backup — safe while gunicorn/celery are running (WAL mode recommended)
sqlite3 "$DB_PATH" ".backup '$TMP'"
echo "Backup created: $TMP ($(du -sh "$TMP" | cut -f1))"

if [ -n "$BUCKET" ]; then
    aws s3 cp "$TMP" "s3://${BUCKET}/atletasworld-db/${TIMESTAMP}.sqlite3" \
        --storage-class STANDARD_IA
    echo "Uploaded to s3://${BUCKET}/atletasworld-db/${TIMESTAMP}.sqlite3"
    rm -f "$TMP"
else
    echo "WARNING: BACKUP_S3_BUCKET not set — backup kept locally at $TMP only"
fi
