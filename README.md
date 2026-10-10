<div align="center">
  <h1>📄 Smart Document Chatbot — Enterprise RAG Q&A Platform</h1>
  <p><strong>Self-Hosted Document Intelligence with Corrective RAG, LangGraph Agents & Local-First LLM</strong></p>

  [![Java 17](https://img.shields.io/badge/Java-17-ED8B00?style=flat-square&logo=openjdk&logoColor=white)](https://openjdk.org/)
  [![Spring Boot](https://img.shields.io/badge/Spring%20Boot-3.2-6DB33F?style=flat-square&logo=spring&logoColor=white)](https://spring.io/)
  [![React 18](https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev/)
  [![TypeScript](https://img.shields.io/badge/TypeScript-5.x-3178C6?style=flat-square&logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
  [![Python 3.11](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org/)
  [![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com/)
  [![LangGraph](https://img.shields.io/badge/LangGraph-000000?style=flat-square&logo=langchain&logoColor=white)](https://langchain.com/)
  [![Qdrant](https://img.shields.io/badge/Qdrant-FE3C00?style=flat-square&logo=qdrant&logoColor=white)](https://qdrant.tech/)
  [![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docker.com)
  [![Tests](https://img.shields.io/badge/Tests-665%20passing-success?style=flat-square)](#)
  [![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)

  [![CI/CD](https://github.com/imtarget05/Smart-Document-Chatbot/actions/workflows/ci.yml/badge.svg)](https://github.com/imtarget05/Smart-Document-Chatbot/actions)
</div>

---

**Smart Document Chatbot** is a production-oriented, self-hosted RAG (Retrieval-Augmented Generation) platform that lets users upload legal and business documents, ask questions in natural language (Vietnamese & English), and receive citation-backed answers with abstention when evidence is insufficient. The system employs a **Corrective RAG (CRAG)** architecture with a 5-layer verification pipeline, a local-first LLM strategy via Ollama, and a LangGraph-powered autonomous agent capable of multi-step reasoning and Human-in-the-Loop (HITL) action execution.

Core workflow: `Upload → Retrieve → Verify → Cite → Answer`

## 🚦 Production status (audited 2026-10-10)

| Component | URL | State |
|---|---|---|
| Frontend (Cloudflare Pages) | https://smart-doc-chatbot.pages.dev | Live bundle still points to Render. The revised Pages workflow builds against Azure after CI, but has not been published. A Playwright test opened this Pages origin and successfully completed Azure registration, login, and `/auth/me` with a cross-site cookie on 2026-10-10. |
| Spring backend (Azure, canonical demo API) | https://smartdoc-api.blackisland-5a3f0246.southeastasia.azurecontainerapps.io | Revision `smartdoc-api--deploy1791607168` receives 100% traffic, retains all 21 runtime variables, and passed live CSRF, browser cookie, upload, owner isolation, and RAG chat smoke on 2026-10-10. Agent mode still falls back to RAG (`ragStrategy=direct`). |
| Spring backend (Render mirror) | https://smartdoc-backend-2hhz.onrender.com | Health and full chat intermittently returned 502 on 2026-10-09; not the frontend target until stable. |
| Spring backend (Render, legacy) | https://smart-doc-backend-h4mt.onrender.com | Legacy/alternate endpoint — **status unresolved** (last known Down with `x-render-routing: no-server`); **not canonical** until re-verified via Render dashboard. Not to be referenced in new deploy config |
| LLM router / Keycloak (Render free) | — | **Down** — Keycloak had the same `$PORT` binding issue (fixed here); router requires Cloudflare credentials in the Render dashboard |
| Python agent (Azure) | https://smartdoc-agent.blackisland-5a3f0246.southeastasia.azurecontainerapps.io | Container revision is provisioned but public `/health` and `/ready` timed out on 2026-10-09; agent workflows are not yet verified live. |

The `fix/pages-api-h4mt` branch (repoints Pages + Docker build-args to h4mt) must **not** be
merged until Render dashboard/OAuth console evidence confirms `h4mt` is a valid backend for
this project; today `h4mt` is legacy/unresolved, `2hhz` is a Render mirror, and Azure is the verified RAG demo API. CI runs tests and scans; Azure deployment and Pages publication run afterward with their own readiness gates.

## ✨ Key Features & Engineering Decisions

1. **Corrective RAG (CRAG) Pipeline**: 5-layer verification — Hybrid Retrieval → Relevance Grading → Knowledge Refinement → Hallucination Check → Answer Grading. If evidence is insufficient, the system honestly refuses rather than hallucinating.
2. **Hybrid Search with RRF**: Combines Dense (Qdrant cosine) + Sparse (BM25) retrieval, fused via Reciprocal Rank Fusion, ensuring high recall across semantic and keyword queries.
3. **Local-First LLM Strategy**: Routes through `LocalOllamaProvider` first (health probe with TTL cache). Falls back to Cloudflare Workers AI only when local is unavailable. No mid-request fallback — fail fast, fail clean.
4. **LangGraph Agent Orchestration**: Multi-agent architecture with 9 specialized agents (RAG, CSKH, Research, Report, Engineering Analysis, Ingestion, Action, Comparator) orchestrated by a central agent with state persistence.
5. **Human-in-the-Loop (HITL)**: Side-effect actions (document ingestion, external API calls) require explicit human approval before execution, preventing unintended mutations.
6. **Agent-First Routing**: All chat queries default to Agent mode (LangGraph multi-step reasoning) with RAG as fallback. The agent *reasons*, the RAG *retrieves* — each has its lane.
7. **Enterprise Security Stack**: HttpOnly SameSite cookie authentication + in-memory token state (replaces localStorage token storage), CSRF protection, sliding-window rate limiting, CORS, Audit Logging, and PII-aware guardrails. Password reset uses cryptographically secure single-use SHA-256 hashed tokens (`V21__password_reset_tokens.sql`) with generic request responses and IP/user rate limiting to eliminate account takeover vulnerabilities. Dependency posture (2026-10-05): `npm audit --omit=dev` reports **0 vulnerabilities** in production dependencies; remaining advisories (esbuild dev-server, braces via chokidar, vitest chain) are dev-only and fixable only via breaking upgrades (Vite 8 / Tailwind v4) — tracked, not hidden.
8. **Real-Time Streaming & Endpoints**: Server-Sent Events (SSE) with progressive rendering via `POST /chat/stream` (with legacy `/chat/ask-stream`), search via `POST /search` and `POST /documents/search`, and owner-scoped ingestion monitoring via `GET /jobs/{id}`. Event sequence is `status → metadata → content chunk(s) → complete` (+ `error` on failure). Chunk granularity is word/full-answer depending on the serving path (Spring CRAG emits one content chunk; the Python agent word-splits the completed answer) — this is progressive rendering, not guaranteed provider token-by-token streaming. Dedicated `SseStreamManager`, deduplication via `ChatDedupService`, and dead-letter queue via `ChatDlqService`.
9. **A/B Testing & Evaluation Framework**: Built-in evaluation suite supporting both fast, transparent mock fixture tests (`eval/run_fixture_eval.py` tagged as smoke tests) and live production benchmarks (`eval/run_live_benchmark.py`) computing real chunk-level Hit@K, Recall@K, and MRR.
10. **Cloud-Native Storage**: Neon PostgreSQL (managed), Qdrant Cloud (vector), Cloudflare R2 (document blobs) — wired in code/config (`render.yaml`, `docker/docker-compose.yml`); live reachability follows the Production status table above (backend/router currently down, not "verified live").
11. **Durable Ingestion Queue (ADR-004) & Correlation Tracing**: The async document workflow runs as a DB-backed job with idempotent enqueue, `FOR UPDATE SKIP LOCKED` claiming, exponential-backoff retry, and durable dead-letter replay. `DocumentController` returns `jobId` in `UploadResponse` on `POST /documents`. SLF4J MDC binds `traceId` (from `X-Trace-Id` header), `jobId`, and `documentId` across the execution pipeline for end-to-end observability.
12. **Cloud-Native Kubernetes Topology (manifests-only, NOT live)**: Declarative manifests in `k8s/` (`10-qdrant.yaml`, `15-llm-router.yaml`, `20-smartdoc-backend.yaml`, `30-smartdoc-frontend.yaml`) configure containerized deployments with horizontal pod autoscaling (HPA), non-root execution profiles, resource guarantees, and health probes. These YAMLs are validated (`CV_EVIDENCE.md`) but describe a portability/demo target — no live cluster, metrics-server, or HPA operation is claimed.

---

## 🏗️ Architecture

### System Topology & Request Lifecycle

```mermaid
graph TD
    A[User / Browser] -->|HTTPS| B[React 18 SPA + TypeScript]
    B -->|REST / SSE| C[Spring Boot 3.2 Backend :8080]

    C -->|Agent Delegation| D[Agent Service - FastAPI :9000]
    C -->|LLM Queries| E[LLM Router - FastAPI :8001]
    C -->|Read/Write| F[(Neon PostgreSQL)]

    D -->|Orchestration| G[LangGraph StateGraph]
    G --> G1[RAG Agent]
    G --> G2[Research Agent]
    G --> G3[Report Agent]
    G --> G4[Action Agent]
    G --> G5[CSKH Agent]

    G1 -->|Hybrid Search| H[Qdrant Cloud]
    D -->|Tool Calls| H

    E -->|Local First| I[Ollama - qwen2.5:3b]
    E -->|Fallback| J[Cloudflare Workers AI]

    C -->|Document Storage| K[Cloudflare R2]

    G4 -->|Side Effects| L((HITL Approval))
    L -->|Approved| M[Execute Action]
    L -->|Rejected| N[Abort]
```

### Two retrieval paths (deliberate, not duplication)

| Path | Owner | Store | Method | Used when |
|:---|:---|:---|:---|:---|
| Spring CRAG fallback | Spring Boot `RetrievalService` | PostgreSQL legal chunks | Lexical retrieval with diacritic folding + legal-structure boost, owner-isolated | Agent unavailable/degraded, or request explicitly `mode: "rag"` |
| Agent hybrid search | Python `rag_agent` + `qdrant_tool` | Qdrant | Dense cosine + BM25-over-subset fused by RRF | Default chat path (agent-first routing) |

Do not claim "all retrieval uses Qdrant": the Spring path never touches Qdrant, and the agent path never touches PostgreSQL chunks. Each path enforces owner isolation independently.

### Corrective RAG (CRAG) Pipeline
```mermaid
graph TD
    Q[User Question] --> R[Hybrid Retrieval]
    R --> R1[Qdrant Dense Top-K]
    R --> R2[BM25 Sparse Top-K]
    R1 --> F[Reciprocal Rank Fusion]
    R2 --> F

    F --> G{Relevance Grading}
    G -->|All Irrelevant| WS[Web Search Fallback]
    G -->|Mixed| KR[Knowledge Refinement]
    G -->|All Relevant| CA[Context Assembly]

    WS --> CA
    KR --> CA
    CA --> LLM[LLM Generation]
    LLM --> HC{Hallucination Check}
    HC -->|Grounded| AG{Answer Grading}
    HC -->|Not Grounded| LLM
    AG -->|Useful| CITE[Citation Response]
    AG -->|Not Useful| WS
```

---

## 🛠️ Tech Stack

| Category | Technologies |
|---|---|
| **Backend** | Java 17, Spring Boot 3.2, Spring Security, Flyway, Maven |
| **Agent Service** | Python 3.11+, FastAPI, LangGraph, LangChain, Google ADK |
| **LLM Router** | Python 3.11+, FastAPI, Ollama (qwen2.5:3b), Cloudflare Workers AI |
| **Frontend** | React 18, TypeScript 5, Vite, Tailwind CSS |
| **Vector Store** | Qdrant Cloud (Hybrid Dense + BM25 Sparse, RRF) |
| **Database** | Neon PostgreSQL (managed, Flyway migrations V1–V15) |
| **Object Storage** | Cloudflare R2 (S3-compatible) |
| **Embeddings** | nomic-embed-text (768-dim, local via Ollama) |
| **Observability** | Langfuse Tracing, Prometheus metrics, structured logging |
| **DevOps** | Docker, Docker Compose, GitHub Actions CI/CD, Render Blueprints |

---

## 🚀 Quick Start

### Prerequisites
- Java 17+, Maven 3.9+
- Python 3.11+
- Node.js 18+
- [Ollama](https://ollama.ai/) (for local LLM)
- Docker & Docker Compose (optional)

### Option 1: Docker Compose (Recommended)

```bash
cp .env.example .env   # Fill in your credentials
docker compose -f docker/docker-compose.yml up --build -d
```

#### Validate the Compose file without credentials

From a clean clone you can prove the Compose file is well-formed before
provisioning any secret, using the committed `.env.test` fixture (dummy values
only — `JWT_SECRET` decodes to `test-secret-key-for-testing-purposes-only`):

```bash
docker compose --env-file .env.test -f docker/docker-compose.yml config > /dev/null \
  && echo "compose config OK"
```

This also verifies that every `condition: service_healthy` dependency targets a
service that actually defines a `healthcheck`. `.env.test` is a validation
fixture only — never run the stack with it; real runs use `.env` from Option 1.

### Option 2: Local Development

```bash
# Terminal 1: Pull LLM models & start Ollama (M1 Pro 16GB plan, 2026-09-18)
# KEEP qwen2.5:3b (chat RAG default, num_ctx 4096, keep_alive 5m) +
# nomic-embed-text (kept so stored vectors stay valid).
ollama pull qwen2.5:3b
ollama pull nomic-embed-text
# Optional (on demand only): code tasks + Vietnamese embeddings
# make local-ollama-pull-code      # qwen2.5-coder:1.5b (task=code only)
# make local-ollama-pull-embed-vi  # qwen3-embedding:0.6b (~400MB, requires re-index)
# Run Ollama with OLLAMA_NUM_PARALLEL=1 OLLAMA_MAX_LOADED_MODELS=1 (16GB RAM).
# Enable local-first: LOCAL_OLLAMA_URL=http://localhost:11434 (see .env.example
# for LOCAL_OLLAMA_CODE_MODEL / LOCAL_OLLAMA_EMBED_MODEL / NUM_CTX / KEEP_ALIVE).

# Terminal 2: Backend (Spring Boot)
cd backend
cp ../.env.example ../.env   # Configure credentials
mvn spring-boot:run

# Terminal 3: LLM Router
cd llm-router
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8001 --reload

# Terminal 4: Agent Service
cd agent
pip install -r requirements.txt
uvicorn main:app --port 9000 --reload

# Terminal 5: Frontend
cd frontend
npm install
npm run dev
```

---

## 📡 API Reference

### Backend (Spring Boot — :8080)

| Method | Endpoint | Description |
|:---|:---|:---|
| `POST` | `/api/auth/login` | JWT authentication |
| `POST` | `/api/auth/google` | Google OAuth2 / One Tap login |
| `POST` | `/api/chat` | Send query (Agent-first, RAG fallback) |
| `GET` | `/api/chat/stream` | SSE streaming (status → metadata → chunk → complete) |
| `POST` | `/api/documents/upload` | Upload PDF/DOCX/TXT documents |
| `GET` | `/api/documents` | List uploaded documents |
| `GET` | `/api/history` | Conversation history |
| `GET` | `/api/health` | System health check |

### Agent Service (FastAPI — :9000)

| Method | Endpoint | Description |
|:---|:---|:---|
| `POST` | `/agent/chat` | LangGraph multi-step reasoning |
| `POST` | `/agent/ingest` | Document ingestion pipeline |
| `GET` | `/agent/actions/pending` | List pending HITL approvals |
| `POST` | `/agent/actions/confirm` | Approve/reject side-effect action |
| `POST` | `/memory/store` | Store long-term memory |
| `GET` | `/health` | Agent health + model status |

### LLM Router (FastAPI — :8001)

| Method | Endpoint | Description |
|:---|:---|:---|
| `POST` | `/api/chat` | Routed LLM inference (local-first) |
| `POST` | `/api/chat/stream` | Streaming LLM inference |
| `POST` | `/api/embeddings` | Generate embeddings (nomic-embed-text) |
| `GET` | `/api/models` | List available models |
| `GET` | `/health` | Router health + provider status |

---

## 📂 Project Structure

```text
├── backend/                    # Spring Boot 3.2 backend
│   ├── src/main/java/
│   │   ├── controller/         # REST controllers (Chat, Document, Auth, Admin)
│   │   ├── service/            # Business logic (ChatService, SseStreamManager, DedupService)
│   │   ├── model/              # JPA entities
│   │   ├── repository/         # Spring Data JPA repos
│   │   ├── config/             # Security, CORS, Rate Limiting, Flyway
│   │   └── dto/                # Request/Response DTOs
│   └── src/test/               # 283 JUnit tests (53 test classes)
├── agent/                      # Python Agent Service (FastAPI + LangGraph)
│   ├── agents/                 # 9 specialized agents (RAG, CSKH, Research, Report...)
│   ├── graph/                  # LangGraph StateGraph workflow
│   ├── routers/                # 8 FastAPI routers (chat, actions, admin, hitl, mcp...)
│   ├── tools/                  # Agent tools (Qdrant, Web Search, Notification, Report)
│   ├── memory/                 # Short-term, Long-term, Graph memory
│   ├── connectors/             # Gmail, Google Drive, Slack, SharePoint
│   ├── benchmark/              # Performance benchmarking framework
│   ├── eval_framework/         # Automated evaluation pipeline
│   └── tests/                  # 199 pytest tests (16 test files)
├── llm-router/                 # LLM Gateway (FastAPI)
│   ├── app/                    # Providers, routing, cache, circuit breaker, prompt compressor
│   ├── agent/                  # Document processing graph (OCR, chunking)
│   └── tests/                  # 80 pytest tests (9 test files)
├── frontend/                   # React 18 + TypeScript SPA
│   └── src/
│       ├── pages/              # ChatPage, LoginPage, AdminPage
│       ├── components/         # Reusable UI components
│       ├── services/           # API client layer
│       ├── hooks/              # Data-fetching hooks (chat sessions, documents, audit logs)
│       └── context/            # Auth context provider
├── docker/                     # Dockerfiles & compose configs
├── docs/                       # Architecture docs, reports, benchmarks
├── eval/                       # RAG evaluation datasets & grader
├── scripts/                    # Ops scripts (backup, restore, smoke tests, load tests)
├── .github/workflows/          # CI/CD pipelines (ci, cd, eval, compliance, load-test)
├── render.yaml                 # Render Cloud Blueprint
└── Makefile                    # Dev commands (test, lint, build, deploy)
```

---

## 🧪 Testing — Lệnh test chuẩn (P0)

> venv chuẩn: `agent/.venv` tạo từ `agent/requirements.txt` (`python3.11 -m venv agent/.venv && agent/.venv/bin/python -m pip install -r agent/requirements.txt`).
> marks đã đăng ký trong `pytest.ini` + `agent/tests/conftest.py`: `asyncio`, `integration`, `slow`.

```bash
# Agent Service — lệnh chuẩn (tái lập agent/tests + tests/, gồm test_chaos.py)
agent/.venv/bin/python -m pytest agent/tests tests -q
# hoặc
make test-agent
# fast path (bỏ integration/slow):
make test-agent-fast  # pytest -m "not integration and not slow"

# Backend — current verified baseline: 310 tests as of 2026-10-06 @ b046a02
# (`mvn test` reactor summary; naive surefire-report grep-sum shows 319 due to a
# stale VideoJobServiceTest report under target/ — clean with `mvn clean`)
cd backend && mvn test

# LLM Router (80 tests — MUST dùng llm-router/.venv)
cd llm-router && .venv/bin/python -m pytest -q

# Frontend (104 tests)
cd frontend && npm test
```

Tái lập 2026-09-18: `agent/tests` collect 219 tests; chạy kèm `tests/` = 221 — **221 passed** (fix: `agent/tests/conftest.py` force in-memory fallback, không chạm Neon staging; trước fix: 214 passed + 7 failed `test_graph_memory.py` do `.env` trỏ Neon thật).

### Eval semantics — fixture smoke vs live benchmark (read before quoting numbers)

Two tracks, different meanings — do not mix them:

| Track | Command | What it measures | Evidence |
|:---|:---|:---|:---|
| Fixture smoke (mock backend) | `pytest eval` (28 tests) or `python eval/run_fixture_eval.py` | Deterministic grader + fixture regression on 31 questions; the ~96.8% figure in `eval/results/offline_eval.json` is the **fixture retrieval pass rate against a mock backend** (`mock_responses: 31, genuine_llm_responses: 0`) — a CI regression signal, **not** live retrieval accuracy | `eval/results/offline_eval.json` (self-labeled `test_type: fixture_grader_smoke_test`) |
| Live benchmark (real stack) | `python eval/run_live_benchmark.py --base-url http://localhost:8080/api` | Chunk-level Hit@K / Recall@K / MRR against the live Spring + Qdrant stack with a real provider | `eval/results/live_benchmark.json` — **requires a running backend, Qdrant, and an LLM provider (LM Studio/Qwen or Cloudflare Workers AI); cannot run offline and must never be fabricated** |

Wording rule: say "96.8% fixture pass rate (mock, 31 questions)" — never "96.8% live retrieval accuracy" — unless `live_benchmark.json` with real provider provenance exists to back it.

### Local LLM Benchmark (Apple M1 Pro, 16GB)

| Model | Throughput | Warm Latency | Vietnamese Quality |
|---|---|---|---|
| qwen2.5:3b | ~52.7 tok/s | ~1.03s | ⭐⭐⭐⭐ Excellent |

---

## ☁️ Deployment

> **Chi tiết từng bước trên hạ tầng 100% miễn phí**: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)

- **Backend & Agent**: Deployed on **Render** via `render.yaml` Blueprint (Docker, `plan: free`)
- **Frontend**: **Cloudflare Pages** (global CDN, unlimited bandwidth) — auto-deploy qua `pages.yml`
- **Database**: **Neon PostgreSQL** (serverless, free vĩnh viễn — không dùng Render free Postgres vì hết hạn sau 30 ngày; Flyway-managed schema V1–V17)
- **Vector Store**: **Qdrant Cloud** (managed, free cluster 1GB)
- **Object Storage**: **Cloudflare R2** (S3-compatible, 10GB free)
- **LLM & Embeddings**: **Cloudflare Workers AI** (10k neurons/day free)
- **CI/CD**: **GitHub Actions** — automated testing, compliance checks, and deployment
- **Chi phí tổng: $0/tháng** — mọi component đều trong free tier vĩnh viễn

---

## 🔒 DEPLOYMENT CHỐT — Local-First (Hybrid by Classification)

> Chi tiết: [`docs/DEPLOYMENT_LOCAL_FIRST.md`](docs/DEPLOYMENT_LOCAL_FIRST.md)

- **Training duy nhất**: Colab LLM Fine-tuning (LoRA Llama-3.2/Qwen) —
  [`colab/finetune_lora_T4.ipynb`](colab/finetune_lora_T4.ipynb). Không train reranker.
- **Deployment duy nhất**: **LOCAL-FIRST** — Ollama/vLLM (model LoRA đã finetune)
  + Qdrant local là mặc định. Cloud fallback **CHỈ** cho tài liệu **PUBLIC**.
- **Reranker**: pretrained `bge-reranker-v2-m3` inference thuần (không finetune).

| Classification | Local OK | Local lỗi → | Ghi chú |
|:---|:---:|:---|:---|
| **PUBLIC** | ✅ serve local | ✅ fallback Cloudflare Workers AI | Dữ liệu công khai, được phép ra cloud |
| **CONFIDENTIAL** | ✅ serve local | ⛔ **403 `policy_violation` — KHÔNG đẩy cloud** | `llm-router/app/service.py::_active` chặn; `main.py` trả 403 |

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

*Developed by [imtarget05](https://github.com/imtarget05)*
