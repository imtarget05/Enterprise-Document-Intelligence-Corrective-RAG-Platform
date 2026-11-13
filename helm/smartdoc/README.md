# smartdoc Helm chart

Production-grade Helm chart for the Enterprise Document Intelligence /
Corrective-RAG platform, mirroring the raw manifests in [`k8s/`](../../k8s/):

| Component | Source manifest | Kind | Image |
|---|---|---|---|
| Qdrant vector DB | `k8s/10-qdrant.yaml` | Deployment + PVC | `qdrant/qdrant:v1.12.4` |
| LLM router (FastAPI) | `k8s/15-llm-router.yaml` | Deployment | `smart-doc-llm-router:latest` |
| Redis (HITL store) | `k8s/16-redis.yaml` | Deployment + PVC | `redis:7-alpine` |
| Spring Boot backend | `k8s/20-smartdoc-backend.yaml` | Deployment (+ HPA) | `smart-document:latest` |
| Agent (LangGraph/HITL) | `k8s/25-smartdoc-agent.yaml` | Deployment | `smart-doc-agent:latest` |
| Frontend (nginx) | `k8s/30-smartdoc-frontend.yaml` | Deployment | `smart-doc-frontend:latest` |

Every component is toggleable: `qdrant.enabled`, `llmRouter.enabled`,
`backend.enabled`, `frontend.enabled` (plus `redis.enabled`, `agent.enabled`),
all `true` by default.

## Files

```
helm/smartdoc/
├── Chart.yaml
├── values.yaml          # defaults (mirror the k8s/ manifests)
├── values-dev.yaml      # 1 replica everywhere, no HPA, no ingress
├── values-prod.yaml     # backend 2 replicas + HPA, ingress, storage-class placeholder
├── README.md
└── templates/
    ├── _helpers.tpl
    ├── NOTES.txt
    ├── qdrant.yaml          # Deployment + Service + PVC
    ├── llm-router.yaml      # Deployment + Service
    ├── backend.yaml         # Deployment + Service
    ├── agent.yaml           # Deployment + Service
    ├── redis.yaml           # Deployment + Service + PVC
    ├── frontend.yaml        # Deployment + Service
    ├── hpa.yaml             # backend HPA (conditional)
    ├── ingress.yaml         # / -> frontend, /api -> backend (conditional)
    ├── secret-template.yaml # placeholder Secret (use ExternalSecrets!)
    └── serviceaccount.yaml  # optional backend ServiceAccount
```

## Prerequisites

- Helm 3.x
- A Kubernetes namespace (the raw manifests use `portfolio`)
- The `portfolio-secrets` Secret (see below)

## Credentials — IMPORTANT

**Never commit real credentials.** By default the chart does NOT render a
Secret; all workloads read `secretKeyRef`s from `secrets.existingName`
(default `portfolio-secrets`, same as the raw manifests). Create it out of
band or, better, with ExternalSecrets:

```bash
kubectl -n portfolio create secret generic portfolio-secrets \
  --from-literal=SMARTDOC_JDBC_URL='...' \
  --from-literal=SPRING_DATASOURCE_USERNAME='...' \
  --from-literal=SPRING_DATASOURCE_PASSWORD='...' \
  --from-literal=JWT_SECRET='...' \
  --from-literal=KAFKA_BOOTSTRAP_SERVERS='...' \
  --from-literal=KAFKA_SECURITY_PROTOCOL='...' \
  --from-literal=REDIS_PASSWORD='...' \
  --from-literal=AGENT_DATABASE_URL='...' \
  --from-literal=INTERNAL_SERVICE_TOKEN='...' \
  --from-literal=R2_ACCOUNT_ID='...' \
  --from-literal=R2_ACCESS_KEY_ID='...' \
  --from-literal=R2_SECRET_ACCESS_KEY='...'
# optional: KAFKA_SASL_MECHANISM, KAFKA_SASL_JAAS_CONFIG,
#           SSO_OIDC_ISSUER, QDRANT_URL, LLM_PROVIDER_API_KEY
```

`templates/secret-template.yaml` exists only as a documented placeholder
(`secrets.create=true`) and MUST be replaced by ExternalSecrets in any real
cluster.

## Install — dev

```bash
helm lint helm/smartdoc -f helm/smartdoc/values-dev.yaml
helm upgrade --install smartdoc helm/smartdoc \
  -n portfolio --create-namespace \
  -f helm/smartdoc/values-dev.yaml
```

Dev profile: 1 replica per component, no HPA, no ingress, 5Gi Qdrant PVC.

## Install — prod

```bash
helm lint helm/smartdoc -f helm/smartdoc/values-prod.yaml
helm upgrade --install smartdoc helm/smartdoc \
  -n portfolio \
  -f helm/smartdoc/values-prod.yaml \
  --set qdrant.persistence.storageClass=gp3 \
  --set ingress.host=smartdoc.yourdomain.com
```

Prod profile: backend 2 replicas + HPA (2→6 @70% CPU), frontend/agent 2
replicas, ingress routing `/` → frontend and `/api` → backend.

## Preview rendered output

```bash
helm template smartdoc helm/smartdoc -f helm/smartdoc/values-dev.yaml
helm template smartdoc helm/smartdoc -f helm/smartdoc/values-prod.yaml
```

## Notes

- Release name `smartdoc` yields service names identical to the raw manifests
  (`smartdoc-qdrant`, `smartdoc-llm-router`, `smartdoc-backend`,
  `smartdoc-agent`, `smartdoc-redis`, `smartdoc-frontend`), so the in-pod
  `QDRANT_HOST`, `LLM_BASE_URL`, `AGENT_BASE_URL`, `REDIS_HOST`,
  `BACKEND_UPSTREAM` values resolve as-is.
- The agent's `REDIS_URL` uses Kubernetes `$(REDIS_PASSWORD)` env expansion;
  the env helper renders variables in alphabetical order, which keeps
  `REDIS_PASSWORD` before `REDIS_URL` — do not rename these keys.
- Set `backend.serviceAccount.create=true` to have the chart create the
  backend ServiceAccount; otherwise it references the pre-existing
  `portfolio-api` account.
