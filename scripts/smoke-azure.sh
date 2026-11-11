#!/usr/bin/env bash
# ==============================================================================
# SmartDocument — Azure smoke test (chỉ chữa cháy)
# Chạy authenticated RAG smoke trên revision mới trước khi switch traffic.
# ==============================================================================
set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-smartdoc-prod}"
APP_NAME="${APP_NAME:-smartdoc-api}"
REVISION="${1:?Usage: smoke-azure.sh <revision-name>}"
BASE_URL="${2:-}"

if ! command -v az &> /dev/null; then
    echo "❌ Azure CLI (az) is not installed." >&2
    exit 1
fi

if [[ -z "$BASE_URL" ]]; then
    REVISION_FQDN=$(az containerapp revision show \
        --name "$APP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --revision "$REVISION" \
        --query properties.fqdn -o tsv)
    BASE_URL="https://${REVISION_FQDN}/api"
fi

echo "🔎 Running authenticated RAG smoke against revision [$REVISION] at $BASE_URL"

python3 -u scripts/production_smoke.py \
    --mode rag \
    --browser-origin https://smart-doc-chatbot.pages.dev \
    --base-url "$BASE_URL"

echo "✅ Smoke test passed for revision [$REVISION]."
