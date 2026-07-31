#!/usr/bin/env bash
# Runs on EC2 — hot-backup SQLite DB to a temp file, print path.
# Called remotely by Unraid's unraid-pull-backup.sh; no local retention.
set -euo pipefail

DB_PATH="/var/www/atletasworld/src/db.sqlite3"
DEST="/tmp/atletasworld-db-backup.sqlite3"

if [ ! -f "$DB_PATH" ]; then
    echo "ERROR: DB not found at $DB_PATH" >&2
    exit 1
fi

sqlite3 "$DB_PATH" ".backup '$DEST'"
echo "$DEST"
