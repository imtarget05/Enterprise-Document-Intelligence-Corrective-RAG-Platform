"""
Health check and Prometheus metrics endpoints.
"""

import logging
from fastapi import APIRouter
from fastapi.responses import JSONResponse

import state
from settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    # Liveness: the process is alive and serving. Always 200.
    return {"status": "ok", "service": "agent", "version": "2.0.0"}


def _component_status() -> tuple[dict[str, str], list[str]]:
    """Inspect shared state singletons and return (components, errors)."""
    components: dict[str, str] = {}
    errors: list[str] = []

    # 1. LangGraph workflow
    if state._workflow is None:
        components["workflow"] = "unavailable"
        errors.append("workflow: build_workflow failed or not initialized")
    else:
        components["workflow"] = "ok"

    # 2. Long-term memory (in-memory fallback = degraded)
    ltm = state._long_term_memory
    if ltm is None:
        components["long_term_memory"] = "unavailable"
        errors.append("long_term_memory: not initialized")
    elif getattr(ltm, "_pool", None) is False or getattr(ltm, "_pool", None) is None:
        components["long_term_memory"] = "degraded_in_memory_fallback"
        errors.append("long_term_memory: using in-memory fallback (PostgreSQL unavailable)")
    else:
        components["long_term_memory"] = "ok"

    # 2b. Graph memory (in-memory fallback = degraded)
    gm = state._graph_memory
    if gm is None:
        components["graph_memory"] = "unavailable"
        errors.append("graph_memory: not initialized")
    elif getattr(gm, "_pool", None) is False or getattr(gm, "_pool", None) is None:
        components["graph_memory"] = "degraded_in_memory_fallback"
        errors.append("graph_memory: using in-memory fallback (PostgreSQL unavailable)")
    else:
        components["graph_memory"] = "ok"

    # 3. Rate limiter
    if state._rate_limiter is None:
        components["rate_limiter"] = "unavailable"
        errors.append("rate_limiter: not initialized")
    else:
        components["rate_limiter"] = "ok"

    # 4. A2A hub
    if state._a2a_hub is None:
        components["a2a_hub"] = "unavailable"
        errors.append("a2a_hub: initialization failed")
    else:
        components["a2a_hub"] = "ok"

    # 5. MCP server
    if state._mcp_server is None:
        components["mcp_server"] = "unavailable"
        errors.append("mcp_server: initialization failed")
    else:
        components["mcp_server"] = "ok"

    # 6. LLM availability (LangChain chat client libs must be importable)
    try:
        try:
            import langchain_ollama  # noqa: F401
        except ImportError:
            from langchain_community.chat_models import ChatOllama  # noqa: F401
        from llm_factory import LLMFactory

        LLMFactory.get_model()
        components["llm"] = "ok"
    except Exception as exc:
        components["llm"] = "unavailable"
        errors.append(f"llm: unavailable ({exc})")

    return components, errors


@router.get("/ready")
async def readiness():
    components, errors = _component_status()
    if errors:
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "service": "agent",
                "version": "2.0.0",
                "components": components,
                "errors": errors,
            },
        )
    return {
        "status": "ok",
        "service": "agent",
        "version": "2.0.0",
        "components": components,
    }


if settings.prometheus_enabled:

    @router.get("/metrics")
    async def metrics():
        try:
            from metrics import metrics_endpoint

            body, status_code, headers = metrics_endpoint()
            return JSONResponse(
                content=body,
                status_code=status_code,
                headers=headers,
            )
        except Exception as exc:
            logger.exception("Metrics endpoint failed: %s", exc)
            return JSONResponse(
                content={"error": "Metrics not available"},
                status_code=503,
            )
