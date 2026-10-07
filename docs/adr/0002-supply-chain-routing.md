# ADR 0002: Supply-Chain Intent Routing

Status: SUPERSEDED / REMOVED (2026-10-06, verified by `git grep` + `mvn test`)

> **Removal record:** `SupplyChainIntentDetector.java` / `SupplyChainIntentDetectorTest.java`
> do not exist at HEAD (`b046a02`) — zero hits in `backend/`, `frontend/`, `agent/`,
> `llm-router/`, `eval/`, `scripts/`. The detector was removed in an earlier refactor;
> this ADR is retained as historical context only. Current routing (verified by
> `ChatServiceTest` 11/11 + `AgentClientTest` 5/5):
>
> ```text
> Chat request → ChatService → mode routing
>   ├─ default / mode:"agent" → AgentClient → Python Agent (Qdrant+BM25+RRF)
>   └─ mode:"rag" (or Agent failure) → Spring CRAG → PostgreSQL lexical retrieval
> ```

## Context

The chatbot serves two distinct query classes over the same document corpus:

1. **General legal/RAG questions** — answered by the Corrective RAG (CRAG) loop
   over PostgreSQL lexical chunks (`RetrievalService` + `QueryReformulator` +
   Tavily web fallback). This path is production-hardened.
2. **Supply-chain questions** — forecasting, inventory/EOQ, supplier risk, lead
   time, logistics, procurement. These benefit from a multi-agent reasoning
   workflow (orchestrator → rag/report/compare/research/action/engineering)
   rather than a single retrieval pass.

Without explicit routing, every query is forced through the same CRAG path.
Supply-chain queries lose the structured decomposition, tool use (Qdrant,
web search, report generation) and long-term memory that the agent service
(`agent/main.py`, LangGraph `graph/workflow.py`) provides. Conversely, routing
*every* query to the agent wastes latency/cost on simple lookups and couples the
core chat flow to an experimental service.

We need a cheap, deterministic way to decide, at the edge of `ChatService`,
whether a query is supply-chain and should be diverted to the agentic path
(chain #4), while keeping a safe fallback to CRAG when the agent is unavailable.

## Decision

- A lightweight, dependency-free classifier `SupplyChainIntentDetector`
  (`backend/.../service/SupplyChainIntentDetector.java`) runs **before** the CRAG
  loop in `ChatService.processQuery` (line ~73).
- Classification rules:
  - **STRONG keywords** (e.g. "dự báo nhu cầu", "supplier risk", "EOQ",
    "lead time", "chuỗi cung ứng") — weight 3, a single hit concludes intent.
  - **WEAK keywords** (e.g. "tồn kho", "purchase order", "delivery", "on-time",
    "defect", "forecast") — weight 1, require ≥ 2 co-occurring hits.
  - **Negation guard** — phrases like "order of magnitude", "in order to",
    "out of order", "order by", "made to order" are stripped before counting,
    preventing false positives on the bare word "order".
- If `isSupplyChainIntent(message)` is true, `ChatService` calls
  `AgentClient.invokeAgent(...)` → `POST {agent.base-url}/v1/agent/invoke`
  (field contract: `query`, `session_id`, `user_id`; response: `answer`,
  `agent_type`, `sources`, `confidence_score`). The result is persisted and
  returned directly, skipping CRAG.
- The agent call is wrapped in try/catch: **any failure falls back to the normal
  CRAG path** (logged, metrics recorded as `agentic` attempt then RAG fallback).
  This keeps the experimental agent fully non-blocking for the core product.
- `AgentClient` writes one `agent_state` row per invocation (best-effort;
  DB errors are swallowed) for observability.

## Alternatives Considered

- **Route everything through the agent.** Rejected: CRAG is faster, cheaper and
  production-proven for the 90% general-legal case; coupling it to an
  experimental service would regress latency and availability.
- **LLM-based intent classification.** Rejected: adds a model call + latency +
  cost on every query, and is non-deterministic. The keyword classifier is
  instant, free, testable (`SupplyChainIntentDetectorTest`, `ChatServiceTest`).
- **Hard rule table in config.** Rejected in favour of a single classifier with
  strong/weak weights — easier to tune and unit-test than a flat regex list.
- **Call the agent synchronously inside the SSE stream.** Rejected: the
  `/ask-stream` endpoint is reserved for token-by-token RAG; supply-chain
  routing uses the non-streaming `/ask` path to keep the streaming contract clean.

## Consequences

- Supply-chain questions get structured multi-agent reasoning; general questions
  stay on the fast CRAG path.
- The core chat flow never hard-depends on the agent: a down agent degrades to
  RAG, not to errors (verified by `AgentClientTest` failure path).
- `agent.base-url` must point at the **agent service (port 9000)**, not the
  llm-router (8001); the Docker Compose var is `AGENT_BASE_URL`. A mismatch
  silently breaks routing (`AgentClientTest` locks this contract).
- Tunability cost: the keyword lists need periodic review against real traffic;
  false positives still possible when ≥2 weak keywords appear outside a
  supply-chain context (accepted for a PoC-grade classifier).
- The agent workflow is experimental (`_workflow` may be `None` in some
  environments, returning an ADK demo fallback). This is acceptable because the
  Java side already falls back to CRAG.
