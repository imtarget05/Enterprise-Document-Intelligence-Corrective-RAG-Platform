# CI Audit — Enterprise RAG

Generated: 2026-11-12
Source: `.github/workflows/*.yml`

## Workflows

### `.github/workflows/ci.yml` — CI/CD Pipeline
**Triggers:** `workflow_dispatch`, `push` to `main`/`develop`, `pull_request` to `main`  
**Runs on PR:** Yes — gates merge into `main`.

| Job | Purpose | Gating |
|-----|---------|--------|
| backend-test | Maven `mvn clean verify` against service Postgres (pgvector pg16); JaCoCo line coverage gate ≥ 65% | Blocking |
| frontend-test | Vitest `test:coverage` (lines 80 / branches 70 / functions 65) + `npm run build` | Blocking |
| frontend-e2e | Playwright chat-ui hermetic; fullstack-smoke opt-in via `E2E_API_URL` secret | Blocking (hermetic) |
| agent-test | Python `pytest tests/` with `APP_ENV=test`, offline HF/Transformers | Blocking |
| eval-grader | Offline grader unit tests + `scripts/tests` unittest | Blocking |
| eval-llm-judge-mock | Golden dataset ≥ 50 entries; LLMJudge(mock=True) avg ≥ 0.5; offline semantic check | Blocking |
| chaos-test | Circuit breaker fault injection (`tests/test_chaos.py`) | Blocking |
| security-scan | TruffleHog secrets (all detected), Trivy vuln CRITICAL/HIGH `--exit-code 1` blocking with Maven-429 offline fallback, Semgrep + CodeQL continue-on-error (informational) | **Blocking gate** (Trivy rc + degraded check) |
| gitleaks | Secret scanning pattern gate (SHA-pinned v3) | Blocking |
| canary-smoke | `main` only; preview smoke via `RENDER_PREVIEW_URL` secret (skip if unset) | Non-blocking |
| contract-test | OpenAPI spec presence stub | Blocking |
| docker-build | Build backend + frontend Docker images (no push) | Blocking (needs all test jobs) |

### `.github/workflows/pages.yml` — Deploy Frontend to Cloudflare Pages
**Triggers:** `workflow_dispatch`, `workflow_run` from `Deploy SmartDoc RAG API to Azure` (completed, `main`)  
**Project:** `smart-doc-chatbot`, branch `main`  
**Build env:** `VITE_API_URL=https://smartdoc-api.blackisland-5a3f0246.southeastasia.azurecontainerapps.io/api`  
**Verification:** polls `release.json` for source SHA match (300s deadline), then Playwright `e2e/browser-auth-live.spec.ts` against Pages + Azure API.

### `.github/workflows/deploy-azure.yml` — Deploy SmartDoc RAG API to Azure
**Triggers:** `workflow_dispatch`, `workflow_run` from `CI/CD Pipeline` (completed, `main`)  
**Auth:** `azure/login` with `AZURE_CREDENTIALS` secret (id-token: write)  
**Steps:** `mvn -B package -DskipTests` → `./scripts/deploy-azure.sh` → verify `/api/actuator/health` == UP → RAG business smoke (browser auth) → agent `/ready` readiness (warning only) → record `source_sha.txt` artifact → fail if `AZURE_CREDENTIALS` missing.

## Findings
- CI already runs on PR → satisfies P0.4 merge-gating requirement in combination with GitHub branch protection.
- `security-scan` is the authoritative blocking gate (Trivy CRITICAL/HIGH fixable). TruffleHog + gitleaks cover hardcoded secrets.
- Frontend build is coupled to Azure API URL in `pages.yml`; confirm this is the canonical production backend before publishing Pages.
- `deploy-azure.yml` fails the job when `AZURE_CREDENTIALS` is missing — build-only is not counted as a successful deployment.

## To do (P0)
- [ ] Enable GitHub branch protection on `main`: require PR, require review, require CI status checks.
- [ ] Confirm `AZURE_CREDENTIALS`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` secrets are configured in the repo.
