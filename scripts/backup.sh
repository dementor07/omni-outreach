#!/usr/bin/env bash
# Daily PostgreSQL backup script for Omni Outreach.
# Schedule via cron: 0 3 * * * /home/omni-outreach/scripts/backup.sh
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/home/omni-outreach/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILENAME="omni_outreach_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "[backup] Starting pg_dump at $(date)"
docker compose -f /home/omni-outreach/docker-compose.yml exec -T db \
  pg_dump -U outreach -d outreach --no-owner --no-acl \
  | gzip > "${BACKUP_DIR}/${FILENAME}"

SIZE=$(du -h "${BACKUP_DIR}/${FILENAME}" | cut -f1)
echo "[backup] Saved ${FILENAME} (${SIZE})"

# Prune old backups
find "$BACKUP_DIR" -name "omni_outreach_*.sql.gz" -mtime +"$RETENTION_DAYS" -delete
echo "[backup] Pruned backups older than ${RETENTION_DAYS} days"
echo "[backup] Done at $(date)"
