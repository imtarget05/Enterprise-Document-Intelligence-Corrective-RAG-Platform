#!/usr/bin/env bash
# ==============================================================================
# SmartDocument — Azure Blob backup (chỉ chữa cháy)
# Export container 'enterprise-documents' sang lưu trữ存档.
# ==============================================================================
set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-smartdoc-prod}"
STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-stsmartdoc}"
CONTAINER="${CONTAINER:-enterprise-documents}"
OUTPUT_DIR="${OUTPUT_DIR:-./backups}"
TIMESTAMP="$(date +%Y%m%d%H%M%S)"
OUTPUT_FILE="${OUTPUT_DIR}/smartdoc-blob-${TIMESTAMP}.tar"

if ! command -v az &> /dev/null; then
    echo "❌ Azure CLI (az) is not installed." >&2
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

echo "📦 Backing up Blob container [$CONTAINER] from [$STORAGE_ACCOUNT]"

ACCOUNT_KEY=$(az storage account keys list \
    --account-name "$STORAGE_ACCOUNT" \
    --resource-group "$RESOURCE_GROUP" \
    --query "[0].value" -o tsv)

az storage blob download-batch \
    --account-name "$STORAGE_ACCOUNT" \
    --account-key "$ACCOUNT_KEY" \
    --source "$CONTAINER" \
    --destination "$OUTPUT_DIR" \
    --output none

tar -cf "$OUTPUT_FILE" -C "$OUTPUT_DIR" .

echo "✅ Backup written to $OUTPUT_FILE"
