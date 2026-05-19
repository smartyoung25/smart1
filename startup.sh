#!/bin/bash
# Smart Farm Pipeline — container entrypoint
# Registers cron jobs from ENV vars and keeps the container alive.

set -e

LOG=/app/logs/pipeline.log
mkdir -p /app/logs /app/pipeline/state /app/etl_data

echo "[startup] Smart Farm Pipeline starting at $(date)" | tee -a "$LOG"

# ── Write cron jobs ───────────────────────────────────────────────────────────
ETL_SCHEDULE="${ETL_CRON_SCHEDULE:-0 2 * * *}"
RETRAIN_SCHEDULE="${RETRAIN_CRON_SCHEDULE:-0 3 * * *}"
ENV_THRESH="${RETRAIN_ENV_ROWS:-500}"
PROD_THRESH="${RETRAIN_PROD_ROWS:-200}"

cat > /etc/cron.d/smartfarm << CRON
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin

# Incremental ETL: scan /app/etl_data for new CSV files
${ETL_SCHEDULE} root cd /app && python3 -B pipeline/run_etl_dir.py /app/etl_data >> /app/logs/etl.log 2>&1

# Retrain trigger: check row counts, retrain if thresholds exceeded
${RETRAIN_SCHEDULE} root cd /app && python3 -B pipeline/retrain_trigger.py --env_threshold ${ENV_THRESH} --prod_threshold ${PROD_THRESH} >> /app/logs/retrain.log 2>&1

CRON

chmod 644 /etc/cron.d/smartfarm
echo "[startup] Cron registered — ETL: ${ETL_SCHEDULE} / Retrain: ${RETRAIN_SCHEDULE}" | tee -a "$LOG"

# ── Start cron daemon ─────────────────────────────────────────────────────────
service cron start
echo "[startup] Cron daemon started" | tee -a "$LOG"

# Keep container alive and stream logs
tail -f /app/logs/etl.log /app/logs/retrain.log 2>/dev/null || tail -f "$LOG"
