# CV Evidence Matrix — Smart-Document-Chatbot

Date: 2026-10-05. Status: VERIFIED = reproducible here; PARTIAL = real but
bounded; REMOVE / BLOCKED = do not claim without the stated evidence.

| CV claim | Evidence (file:line / artifact) | Reproduce command | Status |
|---|---|---|---|
| Spring Boot auth + single-use password reset tokens (P0 fixed) | `backend/.../config/SecurityConfig.java`, `AuthController`, `PasswordResetTokenService`, `PasswordResetTokenRepository`; Flyway migration `V21__password_reset_tokens.sql`; SHA-256 token hashing + single-use invalidation | `cd backend && mvn test -Dtest=PasswordResetTokenServiceTest,AuthControllerTest` | VERIFIED |
| Async Document Ingestion lifecycle & correlation tracing | `DocumentController` returns `jobId` in `UploadResponse`; `DocumentIngestionJobRepository`; `RequestIdFilter` injects `X-Trace-Id` / `X-Request-Id`; `DocumentJobExecutor` binds `jobId` & `documentId` into SLF4J MDC | `cd backend && mvn test -Dtest=DocumentControllerTest,JobControllerTest` | VERIFIED |
| Backend test suite | `backend/` — 319 passed, 0 failures, 0 errors (Java 17, Spring Boot 3.2.3, Flyway, H2/Neon) | `cd backend && mvn test` | VERIFIED (319 passed, 2026-10-06) |
| Agent hybrid retrieval (Qdrant dense + BM25 + RRF) | `agent/agents/rag_agent.py`, `agent/tools/qdrant_tool.py`; Spring fallback is PostgreSQL lexical (`RetrievalService.java`), documented in README "Two retrieval paths" | `python -m pytest agent/tests -q -m "not integration and not slow"` (219 passed) | VERIFIED (code + fast tests; live Qdrant not exercised here) |
| SSE streaming | Spring `ChatService.processQueryStream` emits `status → metadata → chunk → complete`; agent `routers/chat.py::stream_answer_tokens` word-splits completed answers; frontend `ChatPage.tsx` renders incrementally | Frontend `104 passed`; backend stream tests in `mvn test` | VERIFIED — progressive rendering is real; never claim guaranteed provider token-by-token (README now states this) |
| Eval: fixture smoke 28 tests & live benchmark harness | `eval/tests/test_grader.py`; `eval/questions.json` (31 questions); `eval/tests/test_live_benchmark_scoring.py` (6 passed); `eval/run_live_benchmark.py` | `pytest eval` → 28 passed; `pytest eval/tests/test_live_benchmark_scoring.py` → 6 passed | VERIFIED |
| "96.8% retrieval accuracy" | `eval/results/offline_eval.json`: `fixture_retrieval_pass_rate: 0.9677` with `mock_responses: 31, genuine_llm_responses: 0`, self-labeled `fixture_grader_smoke_test — NOT live LLM retrieval accuracy` | `python eval/run_fixture_eval.py` (needs mock backend) | REWRITE — say "96.8% fixture pass rate (mock, 31 questions)"; REMOVE any "live retrieval accuracy" wording unless a real `live_benchmark.json` exists |
| Live benchmark (Hit@K/Recall@K/MRR) | `eval/run_live_benchmark.py` (verified script, machine-readable artifact incl. timestamp/SHA/thresholds) | Requires running backend + Qdrant + provider (LM Studio/Qwen or Workers AI) | BLOCKED_BY_EXTERNAL_DEPENDENCY — script kept and validated, no fabricated output |
| Frontend suite | `frontend/` — 104 passed (2026-10-06) | `cd frontend && npm test` | VERIFIED |
| Production deps vulnerability posture | `npm audit --omit=dev` → 0 vulnerabilities; remaining advisories dev-only (breaking-change fixes) | `npm audit --omit=dev`; `npm audit` | VERIFIED as documented |
| Kubernetes Cloud-Native topology | `k8s/10-qdrant.yaml`, `k8s/15-llm-router.yaml`, `k8s/20-smartdoc-backend.yaml`, `k8s/30-smartdoc-frontend.yaml` (Deployments, Services, HPA, Probes, non-root securityContext) | `python3 -c 'import yaml, glob; [list(yaml.safe_load_all(open(f))) for f in glob.glob("k8s/*.yaml")]'` | VERIFIED (all YAMLs valid) |

## 2026-11-13 update — production infrastructure rows

| CV claim | Evidence (file:line / artifact) | Reproduce command | Status |
|---|---|---|---|
| Production frontend on Cloudflare Pages | `https://smart-doc-chatbot.pages.dev` (project `smart-doc-chatbot`, CLOUDFLARE_PAGES_PROJECT var); deployed via OAuth `wrangler pages deploy` from `frontend/dist`; `release.json` stamped with deploy SHA | `curl -s https://smart-doc-chatbot.pages.dev/release.json` → SHA of main | VERIFIED (2026-11-13, homepage 200 + release.json matches `0c7dcf36`) |
| Keycloak SSO on Render with durable Postgres (Neon) | `docker/Dockerfile.keycloak` (PORT-aware entrypoint `sh -c ... ${PORT:-8080}`); service `smartdoc-keycloak` on Render; `KC_DB=postgres` against Neon project `smartdoc-keycloak` (`bold-dew-42291496`) — realm survives container restarts; autodeploy disabled (manual deploys) | `curl -s https://smartdoc-keycloak.onrender.com/realms/smartdoc` → 200; redeploy and re-check → still 200 (durable) | VERIFIED (2026-11-13, deploy `dep-dbripmd9` live) |
| OIDC confidential client for backend (SSO wired) | realm `smartdoc`, client `smartdoc-backend` (confidential, service accounts, redirect URIs for pages + backend); client secret injected via Render env `SSO_OIDC_CLIENT_SECRET`; backend env `SSO_OIDC_ENABLED=true`, `SSO_OIDC_ISSUER_URI=https://smartdoc-keycloak.onrender.com/realms/smartdoc` | OAuth2 client-credentials grant against `realms/smartdoc/protocol/openid-connect/token` returns access_token | VERIFIED (2026-11-13, run 43456038045) |
| Backend on Render with SSO env | `https://smartdoc-backend-2hhz.onrender.com` service `smartdoc-backend`; 24 env vars incl. SSO block; `/api/actuator/health` 200 after SSO wiring | `curl -s https://smartdoc-backend-2hhz.onrender.com/api/actuator/health` | VERIFIED (2026-11-13) |

Known limitations: live benchmark execution requires running LLM provider or local Ollama;
production Qdrant Cloud requires API key credentials. Keycloak runs on Render free tier
(cold start ~30–60 s on first request; Neon compute scales to zero between requests).

