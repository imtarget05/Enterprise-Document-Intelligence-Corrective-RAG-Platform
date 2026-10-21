# Smart Document Chatbot API

Base URL: `/api`. Swagger UI is available at `/api/swagger-ui/index.html`; the generated OpenAPI JSON is at `/api/v3/api-docs`.

## Authentication

Create an account with `POST /auth/register` or log in using `POST /auth/login`. Passwords must be 12 to 100 characters. Protected endpoints require:

```http
Authorization: Bearer <jwt>
```

Documents and chat histories are scoped to the authenticated username. A client cannot retrieve a different user's object by supplying its ID or session ID.

## Public Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/auth/register` | Register and issue JWT |
| `POST` | `/auth/login` | Authenticate and issue JWT |
| `GET` | `/actuator/health` | Health and Kubernetes probes |
| `GET` | `/actuator/info` | Service information |
| `GET` | `/v3/api-docs` | OpenAPI schema |
| `GET` | `/swagger-ui/index.html` | Interactive API documentation |

## User Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/documents/upload` | Upload PDF, DOCX or TXT, maximum 50 MB |
| `GET` | `/documents` | List the user's documents |
| `GET` | `/documents/{id}` | Read one owned document |
| `DELETE` | `/documents/{id}` | Delete one owned document and vector collection |
| `GET` | `/documents/{id}/mindmap` | Generate or return the cached concept map |
| `POST` | `/chat/ask` | Synchronous RAG question |
| `POST` | `/chat/ask-stream` | SSE RAG response |
| `GET` | `/chat/history/{sessionId}` | User-scoped conversation history |
| `DELETE` | `/chat/history/{sessionId}` | Clear user-scoped conversation history |
| `POST` | `/agent/invoke` | Authenticated principal scopes LangGraph agent orchestration; caller `X-User` is ignored |
| `GET/POST` | `/agent/approvals[/{id}/approve|reject]` | ADMIN/ENGINEER proxy to HITL queue; upstream success still requires agent readiness |

The Python service also exposes direct `/v1/agent/action`, `/report`, and
`/connector/ingest`. These mutate state outside the graph approval gate and
therefore return **403 by default**, even with a valid internal token. They
are available only when `ALLOW_DIRECT_MUTATION_DEMOS=true` in a local/dev/test
environment; staging/production always reject them. Clients of the former
direct routes must migrate to a reviewed approval executor before deployment.
The approval gate applies to the orchestrated action branch, not every
state-changing API. The [side-effect inventory](PORTFOLIO_ENTERPRISE_AUDIT.md#side-effect-inventory-and-trust-boundary)
lists operator, graph-memory, MCP/A2A and document-purge trust boundaries.

Chat payload:

```json
{
  "sessionId": "browser-session-id",
  "documentIds": [1, 2],
  "message": "Summarize the differences."
}
```

`sessionId` is limited to 100 characters and `message` to 8,000 characters.

Agent invoke payload:

```json
{
  "sessionId": "browser-session-id",
  "documentIds": ["doc_collection_or_connector_collection"],
  "query": "Summarize failures and generate an 8D report.",
  "intentOverride": "engineering",
  "useWebSearch": false
}
```

Connector ingestion payload:

```json
{
  "source": "sharepoint",
  "params": {
    "mock": true
  }
}
```

The connector response includes a Qdrant `collection_id`; pass that value in
`documentIds` for `/agent/invoke`.

## Internal Endpoints

These endpoints require `X-Internal-Token: <INTERNAL_SERVICE_TOKEN>`. They are not user APIs.

| Method | Path | Caller |
| --- | --- | --- |
| `POST` | `/documents/{id}/etl-complete` | Airflow callback |
| `POST` | `/documents/{id}/etl-fail` | Airflow callback |
| `GET` | `/actuator/prometheus` | Prometheus scraper |

Production deployments must inject a unique internal token into both backend and Airflow. Prometheus must send the same value as a bearer credential or `X-Internal-Token`.

## System Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/system/health` | RAG infrastructure health (Qdrant + Ollama status). Public. |
| `GET` | `/system/metrics` | Aggregated RAG metrics (requests, latency, fallback/error rates). Requires JWT. |

## Rate Limiting

Token-bucket limits (bucket4j) protect the expensive and abuse-prone surface. Exceeded requests receive `429 Too Many Requests` with a `Retry-After` header in seconds. Limits are configurable via `ratelimit.*` properties and disabled entirely with `RATE_LIMIT_ENABLED=false`.

| Scope | Endpoint(s) | Bucket | Default |
| --- | --- | --- | --- |
| per user | `/chat/ask`, `/chat/ask-stream` | 30 requests/min | LLM calls are costly |
| per user | `/documents/upload` | 10 uploads/min | ingestion is heavy |
| per client IP (honors `X-Forwarded-For`) | `/auth/register`, `/auth/login` | 10 requests/min | brute-force damping, complements account lockout |

## Resilience

LLM router calls from the backend run behind a resilience4j circuit breaker (`llmService`): transport errors, 5xx responses and unusable bodies count as failures; at a 50% failure rate over a 10-call window the circuit opens for 30 seconds and requests fail fast with the standard "temporarily unavailable" message instead of hammering the provider. The breaker state is exported on `/actuator/prometheus` (`resilience4j.circuitbreaker.*`) and intentionally does not affect `/actuator/health`. The llm-router service applies its own circuit breaker toward Cloudflare Workers AI (`CIRCUIT_FAILURE_THRESHOLD`, default 5 consecutive failures → fail fast for `CIRCUIT_OPEN_SECONDS`, default 30s).

