# Deployment Runbook — Enterprise RAG (Smart Document Chatbot)

Generated: 2026-11-13
Scope: Publish Cloudflare Pages, fix Keycloak, consolidate Azure vs Render,
LangGraph checkpoints, live RAG benchmark, monitoring.

Prerequisites (obtain before starting):
- `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` (GitHub Repo Secrets)
- Azure portal access (Container Apps, Keycloak migration)
- Render dashboard access (if using Render fallback)
- Neon Postgres connection string (for LangGraph checkpoints)
- Qdrant URL + API key + LLM provider key (for live benchmark)

---

## Step 1 — Publish Cloudflare Pages (G1 / P1.1)

Goal: Frontend live on Cloudflare Pages, pointing to Azure canonical API.

1. Confirm `AZURE_CREDENTIALS` secret is set in GitHub repo Settings → Secrets.
2. Confirm `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` are set.
3. In `.github/workflows/pages.yml`, verify `VITE_API_URL` points to:
   `https://smartdoc-api.blackisland-5a3f0246.southeastasia.azurecontainerapps.io/api`
4. Run `pages.yml` workflow (workflow_dispatch) from `main` branch.
5. Wait for `deploy-azure.yml` to complete first (pages.yml triggers on
   `workflow_run` from deploy-azure completed).
6. Verify: `curl https://smart-doc-chatbot.pages.dev/` returns 200.
7. Verify Playwright e2e: browser auth flow against Pages + Azure API passes.

Evidence to collect: Pages deployment log, `release.json` SHA match,
Playwright e2e screenshot.

---

## Step 2 — Fix Keycloak `$PORT` binding (G2 / P1.2) — CRITICAL

Goal: SSO/Auth working, not down on Render free tier.

Option A — Migrate Keycloak to Azure Container Apps (recommended):
1. Create Azure Container App for Keycloak (Docker image `quay.io/keycloak/keycloak:26`).
2. Set env: `KC_HOSTNAME=https://<public-url>`, `KC_PROXY=edge`,
   `KEYCLOAK_ADMIN`, `KEYCLOAK_ADMIN_PASSWORD`.
3. Set `SSO_OIDC_ISSUER_URI` to the new public URL in backend env.
4. Update `render.yaml` Keycloak service: point to new URL or remove
   Render Keycloak service.
5. Verify: `GET https://<keycloak-url>/realms/master` returns 200.

Option B — Render paid tier:
1. Upgrade Render Keycloak service from free to paid.
2. Fix `$PORT` binding in Dockerfile/start command.
3. Verify health endpoint.

Evidence to collect: Keycloak `/realms/master` health 200, SSO login smoke test.

---

## Step 3 — Consolidate Azure vs Render (G3 / P1.3)

Goal: Single canonical backend (Azure), Render as documented standby only.

1. Confirm Azure Container Apps receives 100% traffic.
2. In `render.yaml`, ensure all services have `autoDeploy: false` (already
   done in commit b200e3f).
3. Document failover procedure in `docs/P1_FAILOVER.md`.
4. Verify: Azure `/api/actuator/health` returns `{"status":"UP"}`.

---

## Step 4 — LangGraph Checkpoints on Neon (G4 / P1.4)

Goal: HITL approvals survive redeploy (not lost on ephemeral disk).

1. Set `DATABASE_URL` / `NEON_DATABASE_URL` secret in Render dashboard
   (Neon Postgres connection string).
2. Set `LANGGRAPH_CHECKPOINT_SHARED_REQUIRED=true` in agent service env.
3. Verify agent boots with Postgres checkpointer (not SQLite fallback).
4. Run `agent/tests/test_production_readiness.py` — must pass.
5. Redeploy agent service and confirm paused HITL runs are preserved.

Evidence to collect: Test run output, agent logs showing Postgres saver.

---

## Step 5 — HITL Fail-Closed Test (P1.5)

Goal: Actions blocked when Redis unavailable.

1. Confirm `HITL_FAIL_CLOSED=true`, `HITL_REQUIRE_APPROVAL=true`.
2. Confirm Redis Upstash `rediss://` with TLS is reachable.
3. Run `agent/tests/test_production_readiness.py` — verifies gate blocks
   action when store unavailable.
4. Simulate Redis downtime: action should return
   `status=store_unavailable`, NOT execute.

Evidence to collect: Test run output.

---

## Step 6 — Live RAG Benchmark (P1.6)

Goal: Measured retrieval quality (not fixture mock).

1. Set Qdrant URL + API key, LLM provider key (LM Studio/Qwen or Cloudflare Workers AI).
2. Run: `python eval/run_live_benchmark.py --base-url http://localhost:8080/api`
3. Collect: `eval/results/live_benchmark.json` with Hit@K / Recall@K / MRR.
4. Do NOT fabricate results — requires live backend + Qdrant + LLM provider.

Evidence to collect: `live_benchmark.json` with real provider provenance.

---

## Step 7 — Monitoring & Alerting (P1.7)

Goal: Uptime monitoring and alert on backend downtime.

1. Configure Azure Monitor or external uptime provider.
2. Set alert: 502 errors > 5 minutes on Azure API health endpoint.
3. Configure alert notification channel (email/Slack/PagerDuty).

Evidence to collect: Alert rule screenshot, test notification.

---

## Step 8 — Smoke Evidence (P1.8)

Goal: Collected evidence for system design presentation.

1. Run Playwright `e2e/browser-auth-live.spec.ts` against Pages + Azure API.
2. Collect screenshots: CSRF pass, cookie security, file upload, owner
   isolation, RAG chat with citations.
3. Add to `docs/AZURE_SYSTEM_DESIGN_EVIDENCE.md`.

---

## Rollback

- Azure API down: Manual failover to Render standby (set `autoDeploy: true`
  on Render services, point Cloudflare Pages `VITE_API_URL` at Render host).
- Keycloak down: Revert to previous Keycloak URL if migration fails.

---

## Sign-off checklist

- [ ] Cloudflare Pages published, frontend 200
- [ ] Keycloak `/realms/master` returns 200, SSO login works
- [ ] Azure backend health UP, Render standby `autoDeploy: false`
- [ ] LangGraph checkpoints on Neon, HITL survives redeploy
- [ ] HITL fail-closed test passes
- [ ] Live RAG benchmark results collected (not fabricated)
- [ ] Monitoring alert configured
- [ ] Smoke evidence screenshots collected