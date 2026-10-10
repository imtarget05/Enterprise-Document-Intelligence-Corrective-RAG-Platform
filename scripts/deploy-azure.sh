#!/usr/bin/env bash
# ==============================================================================
# SmartDocument — Automated Deployment Script for Azure Container Apps (ACA)
# Deploys Spring Boot 3 API with Scale-to-Zero (minReplicas=0) for cost efficiency
# ==============================================================================

set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-portfolio-prod}"
LOCATION="${LOCATION:-southeastasia}"
ACR_NAME="${ACR_NAME:-crportfolioa3deec}"
CONTAINERAPPS_ENVIRONMENT="${CONTAINERAPPS_ENVIRONMENT:-cae-portfolio-env}"
APP_NAME="smartdoc-api"
TARGET_PORT=8080
IMAGE_TAG="${IMAGE_TAG:-${GITHUB_SHA:-latest}}"
CORS_ALLOWED_ORIGINS="${CORS_ALLOWED_ORIGINS:-https://smart-doc-chatbot.pages.dev,https://smartdocument-39o.pages.dev}"

echo "=========================================================="
echo "🚀 Deploying SmartDocument API to Azure Container Apps"
echo "Resource Group: $RESOURCE_GROUP | Location: $LOCATION"
echo "=========================================================="

if ! command -v az &> /dev/null; then
    echo "❌ Error: Azure CLI (az) is not installed."
    exit 1
fi

ACR_LOGIN_SERVER=$(az acr show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" --query loginServer -o tsv)
if ! az containerapp show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" --output none 2>/dev/null; then
    echo "❌ Container App [$APP_NAME] does not exist. Provision its secrets and runtime configuration before deploying."
    exit 1
fi

if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
    echo "🔨 Building and pushing ${APP_NAME}:${IMAGE_TAG} from this source tree..."
    az acr build \
        --registry "$ACR_NAME" \
        --image "${APP_NAME}:${IMAGE_TAG}" \
        --file backend/Dockerfile.azure \
        backend \
        --output table
fi

echo "🚀 Copying the serving revision, preserving its secrets and runtime configuration..."
SERVING_REVISION=$(az containerapp show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" --query "properties.configuration.ingress.traffic[?weight==\`100\`].revisionName | [0]" -o tsv)
if [[ -z "$SERVING_REVISION" ]]; then
    echo "❌ Expected one revision receiving 100% of traffic. Inspect traffic before deploying."
    exit 1
fi
REVISION_SUFFIX="deploy$(date +%s)"
NEW_REVISION="${APP_NAME}--${REVISION_SUFFIX}"
python3 - "$APP_NAME" "$RESOURCE_GROUP" "$SERVING_REVISION" "$REVISION_SUFFIX" "${ACR_LOGIN_SERVER}/${APP_NAME}:${IMAGE_TAG}" "$CORS_ALLOWED_ORIGINS" <<'PY'
import json
import subprocess
import sys

app, group, source, suffix, image, cors = sys.argv[1:]
revision = json.loads(subprocess.check_output([
    "az", "containerapp", "revision", "show", "--name", app,
    "--resource-group", group, "--revision", source, "--output", "json",
]))
env = revision["properties"]["template"]["containers"][0]["env"]
args = []
for item in env:
    name = item["name"]
    if name == "CORS_ALLOWED_ORIGINS":
        value = cors
    elif item.get("secretRef"):
        value = "secretref:" + item["secretRef"]
    else:
        value = item["value"]
    args.append(f"{name}={value}")
if not any(item["name"] == "CORS_ALLOWED_ORIGINS" for item in env):
    args.append("CORS_ALLOWED_ORIGINS=" + cors)
subprocess.run([
    "az", "containerapp", "revision", "copy", "--name", app,
    "--resource-group", group, "--from-revision", source,
    "--revision-suffix", suffix, "--image", image,
    "--replace-env-vars", *args, "--output", "none",
], check=True)
PY

SOURCE_ENV_COUNT=$(az containerapp revision show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" --revision "$SERVING_REVISION" --query 'length(properties.template.containers[0].env)' -o tsv)
NEW_ENV_COUNT=$(az containerapp revision show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" --revision "$NEW_REVISION" --query 'length(properties.template.containers[0].env)' -o tsv)
if [[ "$NEW_ENV_COUNT" -lt "$SOURCE_ENV_COUNT" ]]; then
    echo "❌ Runtime configuration was lost ($SOURCE_ENV_COUNT -> $NEW_ENV_COUNT variables). Traffic remains on $SERVING_REVISION."
    exit 1
fi

REVISION_FQDN=$(az containerapp revision show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" --revision "$NEW_REVISION" --query properties.fqdn -o tsv)
echo "🔎 Checking new revision [$NEW_REVISION] before routing traffic..."
HEALTHY=0
for attempt in {1..8}; do
    if curl --fail --silent --show-error --max-time 30 "https://${REVISION_FQDN}/api/actuator/health" | grep -q '"status":"UP"'; then
        HEALTHY=1
        break
    fi
    sleep 10
done
if [[ "$HEALTHY" -ne 1 ]]; then
    echo "❌ New revision did not pass health. Traffic remains on $SERVING_REVISION."
    exit 1
fi

echo "🔎 Running authenticated RAG business smoke against the new revision..."
python3 -u scripts/production_smoke.py \
    --mode rag \
    --browser-origin https://smart-doc-chatbot.pages.dev \
    --base-url "https://${REVISION_FQDN}/api"

az containerapp ingress traffic set --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" --revision-weight "${NEW_REVISION}=100" --output none

APP_URL=$(az containerapp show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" --query "properties.configuration.ingress.fqdn" -o tsv)

echo "=========================================================="
echo "✅ Healthy revision [$NEW_REVISION] receives 100% traffic."
echo "🔗 Public Live API: https://${APP_URL}/api/actuator/health"
echo "=========================================================="
