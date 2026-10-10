# Deployment Guide — 100% Free Tier

Hệ thống deploy trọn vẹn trên hạ tầng miễn phí. Không có service nào mất phí,
không có trial hết hạn (trừ những mục đã ghi chú). Vận hành theo blueprint:
`render.yaml` được Render đọc trực tiếp từ repo (Render Dashboard → **New → Blueprint**).

## Tổng quan hạ tầng

| Component | Dịch vụ | Free tier & giới hạn | Lưu ý |
|---|---|---|---|
| Backend (Spring Boot) | Render Web Service (Docker, `plan: free`) | Spin-down sau 15' idle, wake 30–50s | `render.yaml` ✓ |
| LLM Router (FastAPI) | Render Web Service (Python, `plan: free`) | Như trên | `render.yaml` ✓ |
| Agent (RAG re-ranker) | Render Web Service (Python, `plan: free`) | Như trên | `render.yaml` ✓ |
| Keycloak (SSO/OIDC) | Render Web Service (Docker, `plan: free`) | Như trên | `render.yaml` ✓ |
| PostgreSQL | **Neon** (free vĩnh viễn, ~0.5GB) | Không hết hạn | **Không dùng** Render free Postgres — hết hạn sau 30 ngày |
| Vector DB | Qdrant Cloud (free cluster 1GB) | 1GB vectors | cloud.qdrant.tech |
| File storage | Cloudflare R2 (10GB free) | 10GB lưu + egress free | Đã cấu hình `STORAGE_PROVIDER=r2` |
| LLM inference | Cloudflare Workers AI | 10k neurons/day | `@cf/meta/llama-3.3-70b-instruct-fp8-fast` |
| Embeddings | Cloudflare Workers AI | Cùng quota | `@cf/baai/bge-base-en-v1.5` |
| Rate-limit store | Upstash Redis (10k commands/day) | TLS bắt buộc | `REDIS_SSL_ENABLED=true` đã set |
| Frontend | Cloudflare Pages | Unlimited bandwidth | Deploy qua `.github/workflows/pages.yml` |
| Observability | Langfuse Cloud (free) + GitHub Actions | — | Opt-in qua LANGFUSE_* keys |

Flyway Community (migration V1→V17) là **thư viện trong backend jar** — miễn phí
vĩnh viễn, không giới hạn số migration, không cần account. Index partial unique
V17 là tính năng PostgreSQL tiêu chuẩn.

## Các bước deploy

### 1. Tạo dịch vụ miễn phí và lấy credentials

1. **Neon**: neon.tech → Create project → copy connection string.
   - `SPRING_DATASOURCE_URL` = `jdbc:postgresql://<host>/<db>?sslmode=require`
   - `SPRING_DATASOURCE_USERNAME` / `SPRING_DATASOURCE_PASSWORD` từ cùng string.
2. **Qdrant Cloud**: cloud.qdrant.tech → Free cluster → copy URL host + API key.
3. **Cloudflare R2**: Dashboard → R2 → Create bucket `smart-doc-documents` →
   API token (Object Read & Write) → copy Account ID + Access Key ID + Secret.
4. **Upstash**: upstash.com → Redis (Regional) → copy host, port 6379, password.
5. **Cloudflare Workers AI**: Dashboard → Workers AI → tạo API token (Workers AI edit).
6. **Render**: render.com → sign in bằng GitHub (grant repo access).

### 2. Deploy blueprint trên Render

Render Dashboard → **New → Blueprint** → chọn repo. Render đọc `render.yaml`
(tạo 4 services: llm-router, backend, agent, keycloak, tất cả `plan: free`).
Điền các env vars đánh dấu `sync: false`:

```
CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN        # Workers AI (llm-router)
ROUTER_INTERNAL_TOKEN                              # random 32+ chars
REDIS_URL                                          # Upstash rediss://... (llm-router + agent HITL store)
LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY           # opt-in
SPRING_DATASOURCE_URL/USERNAME/PASSWORD            # Neon (backend)
R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY
QDRANT_HOST, QDRANT_API_KEY
JWT_SECRET                                         # random 64+ chars
INTERNAL_SERVICE_TOKEN                             # random (backend + agent shared)
REDIS_HOST, REDIS_PASSWORD                         # Upstash (backend; SSL đã bật)
# HITL governance (agent): REDIS_URL ở trên là bắt buộc; thêm 3 vars sau
# (đã có sẵn trong render.yaml — chỉ cần điền REDIS_URL trong dashboard).
# docker compose prod: xem REDIS_URL/HITL_* trong .env + service redis.
# k8s: thêm REDIS_PASSWORD + INTERNAL_SERVICE_TOKEN vào portfolio-secrets.
#   HITL_STORE_BACKEND=redis, HITL_FAIL_CLOSED=true, HITL_REQUIRE_APPROVAL=true
# Frontend approvals: ADMIN + ENGINEER duyệt tại tab "Phê duyệt" (admin view)
# hoặc card ngay dưới message chat khi agent tạm dừng (hitlPending).
KEYCLOAK_ADMIN_PASSWORD                            # Keycloak
GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_API_KEY   # nếu dùng Google OAuth
SSO_OIDC_ISSUER_URI/CLIENT_ID/CLIENT_SECRET/ADMIN_USERNAMES  # sau khi Keycloak healthy
```
Agent and LLM-router rate limits use the ASGI peer address. The agent does not
trust raw `X-Forwarded-For` values because they may be client-supplied. If
forwarded-IP normalization is later enabled, restrict Uvicorn's trust to a
verified ingress and add proxy-boundary tests before deploying it.
headers from arbitrary peers.

Backend tự chạy Flyway V1→V17 lúc start (`application-prod.yml`: Flyway enabled,
`ddl-auto=validate`). Sau khi `smartdoc-keycloak` healthy:

- Đặt `SSO_OIDC_ENABLED=true`, `SSO_OIDC_ISSUER_URI=https://smartdoc-keycloak.onrender.com/realms/smartdoc`,
  tạo realm `smartdoc` + client trong Keycloak admin console.

### 3. Deploy frontend lên Cloudflare Pages

Tự động qua GitHub Actions (`.github/workflows/pages.yml`) sau khi workflow CI
hoàn tất thành công trên `main`; có thể dispatch thủ công. Cần set repo secrets/vars:

| Tên | Loại | Giá trị |
|---|---|---|
| `CLOUDFLARE_API_TOKEN` | secret | Pages edit + Workers AI token |
| `CLOUDFLARE_ACCOUNT_ID` | secret | Cloudflare Account ID |
| `VITE_API_URL` | build env | `https://smartdoc-api.blackisland-5a3f0246.southeastasia.azurecontainerapps.io/api` |

Workflow tự tạo Pages project (`smart-doc-chatbot`) và deploy `frontend/dist`.
SPA fallback (`public/_redirects`) + security headers (`public/_headers`) đã có sẵn.

### 4. CORS (quan trọng)

`CORS_ALLOWED_ORIGINS` trong `render.yaml` phải khớp domain Pages thật:

```
https://smart-doc-chatbot.pages.dev,https://*.smart-doc-chatbot.pages.dev
```

Backend dùng `setAllowedOriginPatterns` nên wildcard `*.pages.dev` được hỗ trợ —
che phủ các preview deployment (subdomain ngẫu nhiên theo PR). Nếu đổi tên
project Pages, sửa cả render.yaml và `CLOUDFLARE_PAGES_PROJECT`.

### 5. Verify sau deploy

```bash
# Router
curl -s https://<llm-router>.onrender.com/health
# Backend (Render health check cũng dùng endpoint này)
curl -s https://<backend>.onrender.com/api/actuator/health
# Frontend
curl -sI https://smart-doc-chatbot.pages.dev | head -1
```

Chi tiết smoke test: `docs/render-smoke-test.md`.

## Trade-off của free tier (đọc trước khi demo)

- **Spin-down 15 phút**: request đầu sau idle chậm 30–50s (cả backend, router,
  Keycloak). Chấp nhận cho portfolio; ping định kỳ bằng cron là *vi phạm tinh thần*
  free tier — dùng ít nếu có.
- **Render free Postgres hết hạn sau 30 ngày** — lý do dùng Neon.
- **Workers AI 10k neurons/day**: đủ demo/portfolio, không đủ traffic thật.
- **Upstash 10k commands/day**: đủ rate-limit (store fail-open khi thiếu Redis).
- **Neon 0.5GB**: đủ hàng nghìn tài liệu; monitor usage trên dashboard.
- Cold-start Keycloak làm lần login SSO đầu chậm — ghi chú trong demo.

## Chi phí tổng: $0/tháng

Mọi component đều nằm trong free tier vĩnh viễn. Nếu tăng traffic, điểm nâng cấp
đầu tiên là Render paid plan (tắt spin-down) — mọi cấu hình khác giữ nguyên.

## Render production recovery checklist (updated 2026-10-09)

Ordered steps to bring the production chain back (dashboard work + this repo's code):

1. **Backend `smartdoc-backend-2hhz`**: Docker runtime — no startCommand override.
   The app now binds `${SERVER_PORT:${PORT:8080}}`, so Render's `$PORT` is honored.
   Fill `sync:false` env: `SPRING_DATASOURCE_*` (Neon), `QDRANT_*`, `R2_*`,
   `JWT_SECRET`, `INTERNAL_SERVICE_TOKEN`, Langfuse keys.
2. **Gate 1**: `curl https://smartdoc-backend-2hhz.onrender.com/api/actuator/health`
   → `200` with `"status":"UP"`.
3. **llm-router**: set `CLOUDFLARE_ACCOUNT_ID` / `CLOUDFLARE_API_TOKEN` (+ optional
   `ROUTER_INTERNAL_TOKEN`, Langfuse). Gate: `GET /health/live` → 200.
4. **Keycloak**: container now passes `--http-port=${PORT:-8080}`. Gate:
   `GET /realms/master` → 200. Then flip `SSO_OIDC_ENABLED=true` + issuer URI.
5. **GitHub secrets**: `AZURE_CREDENTIALS` for the canonical RAG API workflow;
   `RENDER_API_KEY` + `RENDER_SERVICE_ID` for the separate Render mirror check.
6. **Frontend**: Pages and Docker build-args target the Azure API after CI;
   after a successful CI-gated Pages deployment, run `python scripts/production_smoke.py`
   (health → register/login → upload → chat) must pass.

