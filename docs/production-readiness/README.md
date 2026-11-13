# Production Readiness Handoff Package

Generated: 2026-11-12
Scope: Enterprise RAG, IncidentIQ, QuanLyKho

## Contents

| File | Description |
|------|-------------|
| `../AZURE_SYSTEM_DESIGN_EVIDENCE.md` | Azure smoke test evidence (CSRF, cookie, upload, isolation, RAG chat) |
| `../ARCHITECTURE_DIAGRAM.md` | Multi-cloud Mermaid diagram (Azure, Cloudflare, Render, Neon, Qdrant) |
| `../COST_ANALYSIS.md` | Free vs paid tier comparison, break-even analysis |
| `../SYSTEM_DESIGN.md` | System design document — decisions, trade-offs, per-project summary |
| `../SECRET_INVENTORY.md` | Secret sources per repo (no values) |
| `../CI_AUDIT.md` | CI/CD workflow audit for all 3 repos |
| `../CONTRIBUTING.md` | ECC conventions (TDD, immutability, 80%+ coverage, conventional commits) |

## Checkpoint Status

| Phase | Status | Deliverables |
|-------|--------|--------------|
| P0 — Foundation | Complete | Branch `release/production-ready` on 3 repos; SECRET_INVENTORY.md; CI_AUDIT.md; CONTRIBUTING.md |
| P1 — Enterprise RAG | Partial | render.yaml consolidated (P1.3); checkpointer + HITL tests (P1.4/P1.5); Azure evidence doc |
| P2 — IncidentIQ | Partial | Tenant isolation tests (P2.2); ETL failure tests (P2.3); CI/CD already configured |
| P3 — QuanLyKho | Partial | AI_PROVIDER=cloudflare (P3.3); 531 backend tests pass (P3.5) |
| P4 — Evidence | Complete | This package (all docs above) |

## Deploy-Blocked Tasks (Require Real Credentials)

| Task | Required Credential | Where to Configure |
|------|---------------------|-------------------|
| P1.1 Publish Cloudflare Pages | `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` | GitHub repo Secrets |
| P1.2 Fix Keycloak | Render/Azure deploy access | Render dashboard or Azure portal |
| P1.6 Live RAG benchmark | Qdrant URL + API key, LLM provider key | `.env` / Render dashboard |
| P1.7 Monitoring | Azure Monitor / uptime provider | Azure portal |
| P2.1/P2.5 IncidentIQ deploy | `CLOUDFLARE_API_TOKEN` | GitHub repo Secrets |
| P3.1/P3.2 QuanLyKho production | Cloudflare + Render/Modal access | Cloudflare dashboard / Render dashboard |
| P3.6 ArgoCD production | AKS cluster kubeconfig | Azure AKS |

## Convention (ECC)

- TDD: test first (RED), implement (GREEN), refactor, coverage ≥ 80%
- Immutability: no input mutation; return copies
- Secrets: env vars only, never hardcoded
- Code review: `ecc:code-reviewer` per PR; `ecc:security-reviewer` for auth/user data
- Commits: `type(scope): summary` + `Signed-off-by`
- File size: < 800 lines per source file
- Error handling: no silent swallows; server-side detailed logs

## Security follow-up — 2026-11-13

See [security gate review](SECURITY_REVIEW_2026-11-13.md) and
[local Trivy result](TRIVY_2026-11-13.json). The complete current agent suite
passes 356 tests with one skip. Release commits scan clean, but historical
credential findings remain blocking. The discovered Azure app is a quickstart
placeholder, not a working EDI production backend. These conditions prevent
claiming full production readiness.
