#!/usr/bin/env bash
# ==============================================================================
# SmartDocument — Azure rollback (chỉ chữa cháy, tạm thời)
# Quay traffic về revision trước đó khi smoke mới thất bại.
# ==============================================================================
set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-smartdoc-prod}"
APP_NAME="${APP_NAME:-smartdoc-api}"
PREVIOUS_REVISION="${1:?Usage: rollback-azure.sh <previous-revision-name>}"

if ! command -v az &> /dev/null; then
    echo "❌ Azure CLI (az) is not installed." >&2
    exit 1
fi

echo "🔙 Rolling back traffic to revision [$PREVIOUS_REVISION] in [$RESOURCE_GROUP]"

az containerapp ingress traffic set \
    --name "$APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --revision-weight "${PREVIOUS_REVISION}=100" \
    --output none

echo "✅ Traffic rolled back to [$PREVIOUS_REVISION]."
