"""
Smart Document Chatbot - Agent Service
FastAPI entrypoint for the multi-agent LangGraph orchestration layer.
Accepts requests from the Spring Boot backend (verified via INTERNAL_SERVICE_TOKEN).
"""

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi import APIRouter

from memory.long_term import LongTermMemory
from memory.graph_memory import GraphMemory
from rate_limiter import RateLimiter
from settings import settings
import state
from routers import (
    health_router,
    chat_router,
    hitl_router,
    a2a_router,
    mcp_router,
    actions_router,
    memory_router,
    admin_router,
    training_jobs_router,
    documents_router,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting agent service ...")

    # 1. LangGraph workflow
    try:
        from graph.workflow import build_workflow

        state._workflow = build_workflow()
    except Exception as exc:
        logger.warning("LangGraph workflow unavailable, continuing without it: %s", exc)
        state._workflow = None

    # 2. Long-term memory
    state._long_term_memory = LongTermMemory()
    await state._long_term_memory.ensure_table()
    await state._long_term_memory.ensure_turn_table()

    # 2b. Graph memory (GraphRAG)
    state._graph_memory = GraphMemory()
    await state._graph_memory.ensure_tables()

    # 3. Rate limiter
    state._rate_limiter = RateLimiter(settings)

    # 4. A2A Protocol Hub
    try:
        from a2a.factory import create_default_hub, register_all_agents
        from agents.rag_agent import RagAgent

        state._a2a_hub = create_default_hub()
        rag_agent = RagAgent()

        async def rag_handler(input_data):
            from typing import cast

            from graph.state import AgentState

            state_dict = {
                "query": input_data.get("query", ""),
                "session_id": input_data.get("session_id", "default"),
                "user_id": input_data.get("user_id", "default"),
                "document_ids": input_data.get("document_ids", []),
                "messages": [],
                "long_term_history": [],
                "retrieved_chunks": [],
                "confidence_score": 0.0,
                "agent_plan": "",
                "agent_type": "",
                "final_answer": "",
                "sources": [],
                "action_result": None,
                "report_path": None,
                "use_web_search": input_data.get("use_web_search", False),
                "hybrid_search_enabled": True,
            }
            return await rag_agent.run(cast(AgentState, state_dict))

        register_all_agents(
            state._a2a_hub,
            handlers={"rag_agent": rag_handler},
        )
        logger.info("A2A Hub initialized with %d agents", len(state._a2a_hub.discover_all()))
    except Exception as exc:
        logger.warning("A2A Hub unavailable: %s", exc)
        state._a2a_hub = None

    # 5. MCP Server
    try:
        from mcp.server import MCPServer

        state._mcp_server = MCPServer(name="smart-doc-agent", version="2.0.0")

        async def web_search_handler(query: str = ""):
            from tools.web_search_tool import TavilySearch

            return await TavilySearch().search(query, max_results=5)

        async def retrieve_handler(query: str = "", top_k: int = 5):
            from tools.qdrant_tool import QdrantHybridSearch

            searcher = QdrantHybridSearch()
            return await searcher.hybrid_search(query, "default", top_k=top_k)

        state._mcp_server.register_tool(
            name="web_search",
            description="Search the web for real-time information",
            handler=web_search_handler,
            input_schema={"query": {"type": "string"}},
            required_params=["query"],
            category="search",
        )
        state._mcp_server.register_tool(
            name="document_retrieval",
            description="Search and retrieve document chunks from Qdrant",
            handler=retrieve_handler,
            input_schema={"query": {"type": "string"}, "top_k": {"type": "integer"}},
            required_params=["query"],
            category="retrieval",
        )
        state._mcp_server.register_tool(
            name="generate_report",
            description="Generate a PDF report from content",
            handler=lambda title, content: {"status": "ok", "path": f"/reports/{title}.pdf"},
            input_schema={"title": {"type": "string"}, "content": {"type": "string"}},
            required_params=["title", "content"],
            category="report",
        )
        logger.info("MCP Server initialized with %d tools", state._mcp_server.info.tools_count)
    except Exception as exc:
        logger.warning("MCP Server unavailable: %s", exc)
        state._mcp_server = None

    # 6. Eval & Benchmark frameworks
    try:
        from eval_framework.api import init_eval_framework as init_eval

        agent_url = f"http://localhost:{getattr(settings, 'server_port', 9000)}"
        init_eval(agent_service_url=agent_url, internal_token=settings.internal_service_token)
        logger.info("Eval framework initialized")
    except Exception as exc:
        logger.warning("Eval framework unavailable: %s", exc)

    try:
        from benchmark.api import init_benchmark_framework as init_bench

        agent_url = f"http://localhost:{getattr(settings, 'server_port', 9000)}"
        init_bench(agent_service_url=agent_url, internal_token=settings.internal_service_token)
        logger.info("Benchmark framework initialized")
    except Exception as exc:
        logger.warning("Benchmark framework unavailable: %s", exc)

    logger.info("Agent service ready.")
    yield
    logger.info("Shutting down agent service ...")


app = FastAPI(
    title="Smart Document Chatbot - Agent Service",
    version="2.0.0",
    description="LangGraph multi-agent orchestration layer",
    lifespan=lifespan,
)

# CORS
_allowed_origins = [o.strip() for o in settings.agent_allowed_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Internal-Token", "X-Request-Id", "X-Langfuse-Trace-Id"],
)


@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.agent_max_request_bytes:
        logger.warning(
            "Request body too large: %s bytes from %s",
            content_length,
            request.client.host if request.client else "unknown",
        )
        return JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content={"error": "Request body exceeds the maximum allowed size."},
        )
    return await call_next(request)


@app.middleware("http")
async def tracing_correlation(request: Request, call_next):
    req_id = request.headers.get("X-Request-Id") or request.headers.get("x-request-id") or ""
    trace_id = request.headers.get("X-Langfuse-Trace-Id") or request.headers.get("x-langfuse-trace-id") or ""
    if not req_id:
        req_id = str(uuid.uuid4())
    request.state.request_id = req_id
    request.state.trace_id = trace_id
    state._request_id_ctx.set(req_id)
    if trace_id:
        state._trace_id_ctx.set(trace_id)
    response = await call_next(request)
    response.headers["X-Request-Id"] = req_id
    if trace_id:
        response.headers["X-Langfuse-Trace-Id"] = trace_id
    return response


# Include modular routers under /v1 prefix
v1_router = APIRouter(prefix="/v1")
v1_router.include_router(health_router)
v1_router.include_router(chat_router)
v1_router.include_router(hitl_router)
v1_router.include_router(a2a_router)
v1_router.include_router(mcp_router)
v1_router.include_router(actions_router)
v1_router.include_router(memory_router)
v1_router.include_router(admin_router)
v1_router.include_router(training_jobs_router)
v1_router.include_router(documents_router)

app.include_router(v1_router)

# Direct root routes for backward compatibility
app.include_router(health_router)
app.include_router(chat_router)

# Register eval + benchmark routers
try:
    from eval_framework.api import router as eval_router
    app.include_router(eval_router)
    logger.info("Eval framework router registered")
except Exception as exc:
    logger.warning("Eval framework router unavailable: %s", exc)

try:
    from benchmark.api import router as bench_router
    app.include_router(bench_router)
    logger.info("Benchmark framework router registered")
except Exception as exc:
    logger.warning("Benchmark framework router unavailable: %s", exc)
