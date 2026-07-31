#!/usr/bin/env bash
# Runs on EC2 — creates a timestamped hot backup of the SQLite DB.
# Unraid pulls from EC2 via scripts/unraid-pull-backup.sh (see that file).
#
# Cron (optional, to keep a local rotation on EC2):
#   */30 * * * * /var/www/atletasworld/scripts/backup-db.sh >> /var/log/atletasworld/backup.log 2>&1
set -euo pipefail

DB_PATH="/var/www/atletasworld/src/db.sqlite3"
BACKUP_DIR="/var/www/atletasworld/backups"
KEEP_DAYS=3  # local EC2 retention — Unraid is the real store

if [ ! -f "$DB_PATH" ]; then
    echo "ERROR: DB not found at $DB_PATH"
    exit 1
fi

mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%F-%H%M)
DEST="$BACKUP_DIR/db-${TIMESTAMP}.sqlite3"

# Hot backup — safe while gunicorn/celery are running (WAL mode recommended)
sqlite3 "$DB_PATH" ".backup '$DEST'"
echo "Backup created: $DEST ($(du -sh "$DEST" | cut -f1))"

# Keep a stable "latest" symlink Unraid can always pull
ln -sf "$DEST" "$BACKUP_DIR/db-latest.sqlite3"

# Prune old local backups — keep only last KEEP_DAYS days
find "$BACKUP_DIR" -name "db-*.sqlite3" -mtime +${KEEP_DAYS} -delete

echo "Done. Latest: $BACKUP_DIR/db-latest.sqlite3"
