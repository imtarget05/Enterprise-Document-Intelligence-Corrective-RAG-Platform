# Secret Inventory — Enterprise RAG

Generated: 2026-11-12
Source: `.env.example`, `render.yaml`
Convention: `sync: false` = supplied via Render dashboard / GitHub Secret (never committed); `generateValue: true` = Render-generated; `REPLACE_WITH_*` = placeholder in `.env.example`, must be set by operator.

## Backend (smart-doc-backend)
| Key | Source | Status | Notes |
|-----|--------|--------|-------|
| CLOUDFLARE_ACCOUNT_ID | render.yaml | sync: false | Render dashboard |
| CLOUDFLARE_API_TOKEN | render.yaml | sync: false | Render dashboard |
| INTERNAL_SERVICE_TOKEN | render.yaml / .env.example | sync: false / placeholder | ≥32 chars |
| POSTGRES_PASSWORD | .env.example | placeholder | ≥12 chars |
| QDRANT_API_KEY | render.yaml / .env.example | sync: false / placeholder | Empty for local unauth Qdrant |
| JWT_SECRET | render.yaml | sync: false | |
| SPRING_DATASOURCE_URL | render.yaml | sync: false | Neon Postgres connection string |
| SPRING_DATASOURCE_USERNAME | render.yaml | sync: false | |
| SPRING_DATASOURCE_PASSWORD | render.yaml | sync: false | |
| R2_ACCOUNT_ID | render.yaml | sync: false | |
| R2_ACCESS_KEY_ID | render.yaml | sync: false | |
| R2_SECRET_ACCESS_KEY | render.yaml | sync: false | |
| REDIS_URL | render.yaml | sync: false | Upstash rediss:// with TLS |
| REDIS_PASSWORD | render.yaml | sync: false | |
| SSO_OIDC_ISSUER_URI | render.yaml | sync: false | |
| SSO_OIDC_CLIENT_ID | render.yaml | sync: false | |
| SSO_OIDC_CLIENT_SECRET | render.yaml | sync: false | |
| SSO_OIDC_ADMIN_USERNAMES | render.yaml | sync: false | |
| GOOGLE_CLIENT_ID | render.yaml | sync: false | |
| GOOGLE_CLIENT_SECRET | render.yaml | sync: false | |
| GOOGLE_API_KEY | render.yaml | sync: false | |
| OAUTH2_CLIENT_ID | render.yaml | sync: false | |
| OAUTH2_CLIENT_SECRET | render.yaml | sync: false | |
| LANGFUSE_PUBLIC_KEY | render.yaml | sync: false | |
| LANGFUSE_SECRET_KEY | render.yaml | sync: false | |
| KAFKA_BOOTSTRAP_SERVERS | render.yaml | sync: false | |
| KAFKA_SASL_MECHANISM | render.yaml | sync: false | |
| KAFKA_SASL_JAAS_CONFIG | render.yaml | sync: false | |

## Agent (smart-doc-agent)
| Key | Source | Status | Notes |
|-----|--------|--------|-------|
| INTERNAL_SERVICE_TOKEN | render.yaml | sync: false | |
| REDIS_URL | render.yaml | sync: false | HITL store; fail-closed |
| DATABASE_URL | render.yaml | sync: false | LangGraph checkpoints (Neon/Postgres) |
| RERANKER_MODEL | render.yaml | value | Empty on free tier |

## Keycloak (smartdoc-keycloak)
| Key | Source | Status | Notes |
|-----|--------|--------|-------|
| KEYCLOAK_ADMIN_PASSWORD | render.yaml | sync: false | |
| KC_HOSTNAME | render.yaml | value | https://smartdoc-keycloak.onrender.com |

## Non-secret config (for reference)
CLOUDFLARE_CHAT_MODEL, CLOUDFLARE_EMBED_MODEL, CLOUDFLARE_TIMEOUT_SECONDS, CORS_ALLOWED_ORIGINS, LOGGING_LEVEL_*, COST_PER_1K_TOKENS, CHAT_SSE_THREADS, HITL_FAIL_CLOSED, HITL_REQUIRE_APPROVAL, LANGGRAPH_CHECKPOINT_SHARED_REQUIRED, SSO_OIDC_ENABLED=false (until Keycloak public URL ready).

## Hardcode check
No hardcoded token/password found in source tree outside `.env.example`/`render.yaml` placeholders. Verify with `scripts/check_no_secrets.py` before each commit.
