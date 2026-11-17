# System Design — Enterprise AI Automation Platform

Generated: 2026-11-12
Scope: Enterprise RAG, IncidentIQ, QuanLyKho (3 projects)

## 1. Design Goals

| Goal | Rationale |
|------|-----------|
| Production SLA | 99.9% uptime for backend APIs (Azure/AKS + Cloudflare) |
| Multi-cloud resilience | Azure canonical backend; Cloudflare edge/AI; Render as documented standby |
| Data durability | LangGraph checkpoints in Neon Postgres (survives redeploy); HITL fail-closed |
| Security | No hardcoded secrets; env vars / secret manager; input validation at boundary |
| Observability | Health endpoints, smoke tests, uptime alerts, cost dashboards |

## 2. Decision Trade-offs

### 2.1 Azure for Canonical Backend
**Chosen:** Azure Container Apps (Enterprise RAG) + AKS (QuanLyKho)
**Reasons:**
- Managed platform, no server management
- Integrated with Neon Postgres, Qdrant, Keycloak
- Production SLA available
- Existing CI/CD (`deploy-azure.yml`) already validated

**Rejected:** Render as canonical — free tier spin-down causes 502 (G3), intermittent downtime (G2)

### 2.2 Cloudflare for Edge + AI
**Chosen:** Cloudflare Pages (frontend), Workers AI (embedding/LLM), R2 (storage), Workers (IncidentIQ API)
**Reasons:**
- Edge proximity to users
- Workers AI provides GPU-accelerated inference without managing infra
- R2 has no egress fees
- Workers provides isolated D1/Vectorize per environment (preview vs prod)

**Rejected:** Vercel/Netlify — no native Workers AI integration, higher egress costs

### 2.3 Neon for LangGraph Checkpoints
**Chosen:** Neon Postgres (serverless, auto-suspend)
**Reasons:**
- Shared checkpoints across replicas (HITL persistence)
- Survives redeploy (unlike SQLite ephemeral disk)
- Fail-closed option via `LANGGRAPH_CHECKPOINT_SHARED_REQUIRED`

**Rejected:** SQLite on ephemeral disk — checkpoints lost on every redeploy (G4)

### 2.4 Qdrant for Vector Search
**Chosen:** Qdrant (managed cloud)
**Reasons:**
- Purpose-built vector database
- HNSW indexing, filtering, payload storage
- Integrates with Azure backend

**Rejected:** pgvector — sufficient for small scale, but Qdrant better for production vector search at scale

## 3. Per-Project Design Summary

### 3.1 Enterprise RAG
| Component | Choice | Status |
|-----------|--------|--------|
| Frontend | Cloudflare Pages | Not yet published (G1) |
| Backend | Azure Container Apps | Canonical (P1.3) |
| Auth | Keycloak | Render free down (G2) — needs migration |
| Checkpoints | Neon Postgres | Configured, needs DATABASE_URL secret |
| HITL | Redis Upstash + fail-closed | Configured, test written (P1.5) |
| Eval | Live benchmark | Not yet run (P1.6) |

### 3.2 IncidentIQ
| Component | Choice | Status |
|-----------|--------|--------|
| API | Cloudflare Workers | CI/CD configured (deploy-preview/prod) |
| Database | Cloudflare D1 | Isolated preview/prod |
| Vector | Cloudflare Vectorize | Isolated preview/prod |
| ETL | Cloudflare Queues + DLQ | Retry + dead-letter tested (P2.3) |
| Tenant isolation | API key hash binding | Tests written (P2.2) |
| Frontend auth | Not complete (G7) | Needs implementation |

### 3.3 QuanLyKho
| Component | Choice | Status |
|-----------|--------|--------|
| Frontend | Cloudflare Pages / Workers Assets | Preview domain (G8) — needs production domain |
| Backend | Render preview → Modal (actual) | Reconcile render.yaml vs Modal (P3.2) |
| AI provider | `disabled` → `cloudflare` | Config changed (P3.3), needs secret |
| AI integration | Cloudflare Workers AI / Ollama | Code exists in `services/ai.py` |
| E2E tests | 355 tests | 531 passed locally (P3.5) |
| ArgoCD | GitOps migration job | Needs cluster access (P3.6) |

## 4. Security Model

| Layer | Control |
|-------|---------|
| Secrets | `.env.example` placeholders only; real values in Render dashboard / GitHub Secrets / `wrangler secret put` |
| Input validation | Spring validation (backend), Pydantic schemas (QuanLyKho), Zod (IncidentIQ MCP) |
| Auth | Keycloak OIDC (Enterprise RAG), API key hash binding (IncidentIQ), session binding (QuanLyKho) |
| Tenant isolation | DB-level `tenant_id` filtering on every query |
| Secrets scan | TruffleHog + gitleaks + Trivy in CI (blocking) |
| Error handling | No silent swallows; server-side detailed logs, client-safe messages |

## 5. Observability

| Signal | Tool | Status |
|--------|------|--------|
| Health checks | `/api/actuator/health`, `/health/live`, `/health/ready` | Implemented |
| Uptime monitoring | To be configured (P1.7) | Pending |
| Cost dashboard | To be configured (P2.6) | Pending |
| AI latency | Langfuse traces | Implemented (QuanLyKho) |
| Smoke tests | CI + browser auth | Azure evidence collected (P1.8) |

## 6. Remaining Gaps (Deploy-Blocked)

| # | Gap | Required |
|---|-----|----------|
| G1 | Publish Cloudflare Pages | `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` GitHub Secrets |
| G2 | Fix Keycloak `$PORT` binding | Render/Azure deploy access |
| P1.1 | Publish frontend to Cloudflare Pages | Credentials above |
| P1.6 | Live RAG benchmark | Qdrant + LLM provider credentials |
| P1.7 | Monitoring & alerting | Azure Monitor / uptime provider |
| P2.1/P2.5 | IncidentIQ preview/prod deploy | Cloudflare API tokens |
| P3.1/P3.2 | QuanLyKho production domain + backend | Cloudflare + Render/Modal access |
| P3.6 | ArgoCD GitOps production | AKS cluster access |

## 7. Handoff Package

All documentation consolidated in `docs/production-readiness/`:
- `AZURE_SYSTEM_DESIGN_EVIDENCE.md` — Azure smoke test results
- `ARCHITECTURE_DIAGRAM.md` — Multi-cloud Mermaid diagram
- `COST_ANALYSIS.md` — Free vs paid tier comparison
- `SYSTEM_DESIGN.md` — This document (trade-offs, decisions)
- `SECRET_INVENTORY.md` — Secret sources (no values)
- `CI_AUDIT.md` — CI/CD workflow analysis
- `CONTRIBUTING.md` — ECC conventions (TDD, immutability, coverage, commits)
