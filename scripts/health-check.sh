#!/usr/bin/env bash
# ==============================================================================
# SmartDocument — Azure health-check (chỉ chữa cháy, không thay thế IaC)
# Kiểm tra Container App revision đang nhận traffic và health endpoint.
# ==============================================================================
set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-smartdoc-prod}"
APP_NAME="${APP_NAME:-smartdoc-api}"

if ! command -v az &> /dev/null; then
    echo "❌ Azure CLI (az) is not installed." >&2
    exit 1
fi

echo "🔎 Checking Azure Container App: $APP_NAME ($RESOURCE_GROUP)"

FQDN=$(az containerapp show \
    --name "$APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query "properties.configuration.ingress.fqdn" -o tsv 2>/dev/null) || {
    echo "❌ Container App [$APP_NAME] not found in [$RESOURCE_GROUP]." >&2
    exit 1
}

REVISION=$(az containerapp show \
    --name "$APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query "properties.configuration.ingress.traffic[?weight==\`100\`].revisionName | [0]" -o tsv)

URL="https://${FQDN}/api/actuator/health"
echo "🔗 FQDN: $FQDN"
echo "🟢 Serving revision: $REVISION"
echo "🏥 GET $URL"

STATUS_CODE=$(curl -s -o /tmp/smartdoc-health-body.json -w "%{http_code}" --max-time 30 "$URL" || echo "000")
echo "HTTP $STATUS_CODE"
cat /tmp/smartdoc-health-body.json 2>/dev/null || true
echo

if [[ "$STATUS_CODE" != "200" ]]; then
    echo "❌ Health check failed (HTTP $STATUS_CODE)." >&2
    exit 1
fi

if ! grep -q '"status":"UP"' /tmp/smartdoc-health-body.json 2>/dev/null; then
    echo "❌ Health endpoint did not report UP." >&2
    exit 1
fi

echo "✅ Healthy (HTTP 200, status UP)."
