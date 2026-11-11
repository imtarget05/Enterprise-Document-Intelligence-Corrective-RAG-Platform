# Deploy evidence sample — Enterprise SmartDocument (Azure Container Apps)

File này là mẫu định dạng evidence được thu thập sau mỗi deploy lên Azure Container Apps (CI job `Deploy SmartDoc RAG API to Azure`, artifact `smartdoc-deploy-evidence`).

## deploy-evidence/deploy.txt
```
deploy_time=2026-11-11T14:30:00Z
image_tag=da6bd163
app=smartdoc-api
resource_group=rg-smartdoc-prod
```

## deploy-evidence/health.txt (output `scripts/health-check.sh`)
```
🔎 Checking Azure Container App: smartdoc-api (rg-smartdoc-prod)
🔗 FQDN: smartdoc-api.blackisland-5a3f0246.southeastasia.azurecontainerapps.io
🟢 Serving revision: smartdoc-api--deploy1731300000
🏥 GET https://smartdoc-api.../api/actuator/health
HTTP 200
{"status":"UP",...}
✅ Healthy (HTTP 200, status UP).
```

## Gate (định nghĩa done)
- `GET /api/actuator/health` trả HTTP 200 và `"status":"UP"`.
- Smoke test RAG business (`scripts/smoke-azure.sh`) pass trên revision mới trước khi switch traffic.
- Trivy không phát hiện CRITICAL/HIGH fixable; Sonar quality gate xanh.
- Không deploy production khi có gate P0 mở.

## Lưu ý
- Secrets (Azure credentials, Key Vault) không được commit. Chỉ xác nhận tên secret/biến tồn tại trong repo.
- Mỗi artifact evidence đi kèm workflow run URL để truy ngguồn.
