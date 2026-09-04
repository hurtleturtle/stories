#!/usr/bin/env bash
# Nightly DB backup, run by story-backup.timer. Keeps 14 days on /mnt/backup.
set -euo pipefail

BACKUP_DIR=/mnt/backup
KEEP_DAYS=14

cd /opt/stories
source .env
STAMP=$(date +%Y%m%d-%H%M%S)

docker compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" \
    | gzip > "$BACKUP_DIR/stories-$STAMP.sql.gz"

find "$BACKUP_DIR" -maxdepth 1 -name 'stories-*.sql.gz' -mtime "+$KEEP_DAYS" -delete
