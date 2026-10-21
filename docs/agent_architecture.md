# Agent Architecture (Python LangGraph Service)

> **Trạng thái tại commit `8b6d394`:** Spring `ChatService` đã nối `AgentClient`
> và mặc định thử agent trước, rồi fallback sang Spring CRAG nếu agent lỗi.
> Đây là **code-connected**, chưa phải bằng chứng agent chạy thành công trên
> Azure: lần smoke live được ghi ở README (2026-10-10) trả
> `ragStrategy=direct`. Python service có endpoint riêng và test local, nhưng
> đường agent live còn `NOT_VERIFIED`. Nginx không cần gọi agent trực tiếp;
> Spring là client của Python service.

## Vai trò hai dịch vụ

| Dịch vụ | Vai trò | Trạng thái |
|---|---|---|
| Spring Boot (`:8080`) | Auth JWT, owner isolation, document CRUD, chat CRAG, SSE streaming, persistence | **Product path (đã nối)** |
| Python Agent (`:9000`) | LangGraph multi-agent, RAG Qdrant, connector ingestion, report/action, evaluation | **Đã nối trong Spring code; agent live chưa verified** |

## Python Agent Service

Flow nội bộ (khi gọi trực tiếp `/v1/agent/invoke`):

```text
Request
  -> Prompt-injection + input guardrails (block HIGH, sanitize MEDIUM)
  -> Short/long-term memory load
  -> LangGraph StateGraph:
       orchestrator -> (rag | engineering | comparator | researcher | action | report | ingestion)
  -> Tool calls: Qdrant hybrid search, Tavily web search
  -> Output guardrails + SSE streaming
```

### Các thành phần

- `graph/workflow.py` — LangGraph StateGraph thật (import `langgraph`),
  wiring orchestrator + 7 specialist agents còn lại qua conditional edges.
- `agents/` — 9 file agent: orchestrator + 7 agents gắn vào graph
  (rag, engineering, comparator, researcher, action, report, ingestion)
  và `cskh_agent.py` **chưa được dùng** (orphan — không phải graph node).
- `security/prompt_injection.py` + `guardrails.py` — bảo vệ thật, chạy trên
  mọi entry point.
- `memory/` — long-term (asyncpg/PostgreSQL), short-term, context summarizer,
  VI-EN language handler — đều được dùng bởi rag_agent.
- `connectors/` — Gmail/Google Drive/Slack dùng SDK thật; SharePoint mặc định
  mock mode (`sharepoint_mock_enabled=true`).
- `eval_framework/`, `benchmark/` — chạy như router `/eval/*`, `/benchmark/*`.

### ADK / A2A / MCP — custom implementations (KHÔNG phải SDK chính thức)

Các module này lấy cảm hứng từ khái niệm của Google ADK, A2A và MCP nhưng là
code tự viết, **không** dùng `google.adk`, `mcp` SDK hay JSON-RPC A2A chính
thức — không có package tương ứng trong `requirements.txt`. Chúng chỉ được gọi
qua các endpoint demo riêng (`/v1/agent/adk/demo`, `/v1/a2a/*`, `/v1/mcp/*`)
và không nằm trong invoke path. Khi trình bày, hãy mô tả đúng:

> "Tôi xây lớp orchestration tùy chỉnh lấy cảm hứng từ các mẫu agent hiện đại
> (ADK/A2A/MCP concepts), không phải triển khai chính thức các giao thức đó."

### Connector Ingestion Flow (chỉ qua endpoint riêng)

```text
Google Drive / Gmail / Slack / SharePoint
  -> Connector fetch_documents()
  -> IngestionAgent -> ConnectorIngestionPipeline
  -> chunk -> embed (LLM Router / Ollama) -> upsert Qdrant (collection per user+doc hash)
```

Endpoint: `POST /v1/agent/connector/ingest` (trực tiếp trên agent:9000).

### Evaluation

- `eval/eval.py` — đánh giá classic `/chat/ask` (Spring Boot).
- `eval/agent_eval.py` — đánh giá `/v1/agent/invoke` (intent routing, retrieval
  accuracy, answer completeness, hallucination, latency, citation rate).
- `agent/eval_framework/` — suite cases (answer quality, hallucination,
  retrieval quality, robustness, security, cost, latency).

## Interview Positioning

- Java Spring Boot là product/API layer: auth, ownership, CRAG, persistence,
  stable user-facing APIs.
- Python LangGraph là AI agent layer đã được Spring gọi trong code. Local test
  chứng minh orchestration; live Azure smoke gần nhất rơi về Spring CRAG.
- HITL serving path hiện dùng approval store + graph `END`, rồi re-invoke từ
  snapshot đã lưu. Nó **không dùng** LangGraph `interrupt()/Command(resume=...)`.
  Approval được claim trước khi action chạy: nếu process chết trong khoảng đó,
  retry không được bảo đảm. Demo LangGraph interrupt/checkpoint ở
  `eval/portfolio_demo/agent_hitl.py` là sandbox tách biệt, không phải proof
  rằng serving path đã có exactly-once side effect.
- HITL gate chỉ nằm trong nhánh action của graph. `POST /v1/agent/action`
  gọi `ActionAgent.execute` trực tiếp sau internal-token auth;
  `/v1/agent/connector/ingest` và `/v1/agent/report` cũng là route riêng.
  Chúng được chặn **403 mặc định** bởi `require_local_mutation_demo`; opt-in
  chỉ hoạt động ở local/dev/test. Đây là fail-closed containment, chưa phải
  approval workflow cho các route đó. Client từng dùng chúng ở production sẽ
  nhận 403 và phải chuyển sang luồng được duyệt sau khi có executor bền vững.

HITL này không bao phủ mọi API ghi: training promotion/rollback, graph-memory
extraction, document deletion/purge và improvement proposal có ranh giới tin
cậy riêng. Bảng đường ghi và giới hạn chính xác nằm trong
`docs/PORTFOLIO_ENTERPRISE_AUDIT.md`.
