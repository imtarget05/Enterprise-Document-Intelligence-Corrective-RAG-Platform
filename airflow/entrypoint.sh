#!/bin/bash
set -e

echo "[INFO] Starting Airflow Platform for SmartDocument + CreditFlow + SupportDesk..."

# Initialize database schema if needed
echo "[INFO] Running database migrations on Neon PostgreSQL..."
airflow db migrate

# Create default administrative user if not present
echo "[INFO] Provisioning default administrator..."
airflow users create \
    --username "${AIRFLOW_ADMIN_USERNAME:-admin}" \
    --password "${AIRFLOW_ADMIN_PASSWORD:-Admin@2026!Secure}" \
    --firstname "Platform" \
    --lastname "Admin" \
    --role "Admin" \
    --email "admin@portfolio.local" || true

# Start background scheduler
echo "[INFO] Launching Airflow Scheduler in background..."
airflow scheduler &

# Start foreground webserver for Azure Container Apps ingress
echo "[INFO] Launching Airflow Webserver on port ${PORT:-8080}..."
exec airflow webserver --port "${PORT:-8080}"
