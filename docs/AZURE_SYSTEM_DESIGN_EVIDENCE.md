# Azure System Design Evidence — Enterprise RAG

Generated: 2026-11-12
Source: Azure Container Apps deploy (deploy-azure.yml), Cloudflare Pages (pages.yml),
CI smoke tests (audit 2026-10-10). No secrets are included in this document.

## 1. Backend — Azure Container Apps (canonical)

| Item | Evidence |
|------|----------|
| Target | `smartdoc-api.blackisland-5a3f0246.southeastasia.azurecontainerapps.io` |
| Health endpoint | `GET /api/actuator/health` → `{"status":"UP"}` |
| RAG business smoke | Browser auth flow against Azure API passed (2026-10-10 audit) |
| Deploy CI | `.github/workflows/deploy-azure.yml` — `azure/login` + `mvn package` + `deploy-azure.sh` + health verify |
| CI gate | Trivy vuln CRITICAL/HIGH blocking; TruffleHog + gitleaks secret scan; Semgrep/CodeQL informational |
| Spring profile | `mongodb` active; `PaymentAuditRepository` loads under mongodb profile |
| Redis | Upstash `rediss://` with TLS; HITL store fail-closed (`HITL_FAIL_CLOSED=true`) |

## 2. Frontend — Cloudflare Pages

| Item | Evidence |
|------|----------|
| Project | `smart-doc-chatbot`, branch `main` |
| Build env | `VITE_API_URL=https://smartdoc-api.blackisland-5a3f0246.southeastasia.azurecontainerapps.io/api` |
| CI | `.github/workflows/pages.yml` — triggered by `deploy-azure.yml` completion on `main` |
| Verification | Polls `release.json` for SHA match (300s deadline), then Playwright `e2e/browser-auth-live.spec.ts` against Pages + Azure API |
| Status | **Not yet published** (G1) — P1.1 required |

## 3. Keycloak / Auth (G2 — CRITICAL)

| Item | Evidence |
|------|----------|
| Current | Render free service `smartdoc-keycloak`, `$PORT` binding down → SSO broken |
| Hostname | `https://smartdoc-keycloak.onrender.com` |
| Remediation | Migrate to Azure Container Apps or Render paid tier; `KC_HOSTNAME` must point to public URL |

## 4. LangGraph Checkpoints (G4 — HIGH)

| Item | Evidence |
|------|----------|
| Current | SQLite `checkpoints.sqlite` on ephemeral Render disk → HITL approvals lost on redeploy |
| Configured | `DATABASE_URL` / `NEON_DATABASE_URL` sync: false in render.yaml; `LANGGRAPH_CHECKPOINT_SHARED_REQUIRED` opt-in |
| Code | `agent/graph/workflow.py` — `AsyncPostgresSaver` when Postgres URL present; fail-closed when `SHARED_REQUIRED=1` |
| Test | `agent/tests/test_production_readiness.py` — verifies Postgres selection + fail-closed |

## 5. HITL Fail-Closed (P1.5)

| Item | Evidence |
|------|----------|
| Config | `HITL_FAIL_CLOSED=true`, `HITL_REQUIRE_APPROVAL=true`, Redis Upstash reachable |
| Code | `agent/graph/workflow.py` `hitl_gate_node` — on `HITLStoreUnavailable`, parks run with `status=store_unavailable`, action NOT executed |
| Test | `agent/tests/test_production_readiness.py` — verifies gate blocks action when store unavailable |

## 6. Smoke Test Evidence (Azure, 2026-10-10 audit)

| Test | Result |
|------|--------|
| CSRF protection | Pass — cookie `SameSite=Strict`, anti-CSRF token validated |
| Cookie security | Pass — `Secure`, `HttpOnly`, `SameSite` flags set |
| File upload | Pass — R2 bucket, signed URLs, virus scan |
| Owner isolation | Pass — tenant-scoped queries, cross-tenant access rejected (404) |
| RAG chat | Pass — Azure backend returns grounded answers with citations |

## 7. Gaps Remaining (require deploy credentials)

| Gap | Blocker |
|-----|---------|
| G1 — Publish Cloudflare Pages | Needs `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` (GitHub Secrets) |
| G2 — Fix Keycloak `$PORT` | Needs Render/Azure deploy access |
| G3 — Consolidate Azure vs Render | Needs render.yaml + Azure deploy confirmation |
| P1.6 — Live RAG benchmark | Needs Qdrant + LLM provider credentials |
| P1.7 — Monitoring & alerting | Needs Azure Monitor / uptime provider config |
| P1.8 — Collect smoke evidence screenshots | Needs live Azure + Pages endpoints |
