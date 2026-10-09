"""
Shared runtime state and dependencies for the Agent Service.
Maintains singletons initialized during the FastAPI lifespan.
"""

import contextvars
import hmac
import logging
from typing import Any, Optional

from fastapi import HTTPException, Request, WebSocket, WebSocketException, status

from security.prompt_injection import detect_prompt_injection, sanitize_query
from settings import settings

logger = logging.getLogger(__name__)

# Singletons managed by the application lifespan
_workflow: Any = None
_long_term_memory: Any = None
_graph_memory: Any = None
_rate_limiter: Any = None
_a2a_hub: Any = None
_mcp_server: Any = None
_agent_factory: Any = None

# Contextvars for distributed tracing correlation
_request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
_trace_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")


def get_correlation_ids() -> dict[str, str]:
    return {"request_id": _request_id_ctx.get(""), "trace_id": _trace_id_ctx.get("")}


def check_rate_limit(key: str) -> bool:
    if _rate_limiter is None:
        return True
    return _rate_limiter.is_allowed(key)


def verify_internal_token(request: Request) -> None:
    if getattr(settings, "app_env", "local").lower() in ("test", "testing"):
        return
    token = request.headers.get("X-Internal-Token", "")
    if not settings.internal_service_token or not hmac.compare_digest(
        token, settings.internal_service_token
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized"
        )


def check_prompt_injection(query: str) -> str:
    """
    Detect and mitigate prompt-injection attempts.
    - HIGH severity: blocked (raises ValueError; caller converts to HTTP 400).
    - MEDIUM severity: sanitized + warning logged.
    - LOW / none: returned as-is.
    """
    result = detect_prompt_injection(query)
    if result.is_injection:
        logger.warning(
            "Prompt-injection detected: severity=%s reasons=%s patterns=%s",
            result.severity,
            result.reasons,
            result.matched_patterns,
        )
        if result.severity == "high":
            raise ValueError(
                f"Query rejected by prompt-injection guard: {result.reasons}"
            )
        sanitized = sanitize_query(query)
        logger.info("Query sanitized by prompt-injection guard.")
        return sanitized
    return query


def verify_and_rate_limit(request: Request) -> None:
    verify_internal_token(request)
    enforce_rate_limit(
        request.client.host if request.client else "unknown",
        request.url.path,
    )


def verify_websocket_and_rate_limit(websocket: WebSocket) -> None:
    if getattr(settings, "app_env", "local").lower() in ("test", "testing"):
        return
    token = websocket.headers.get("X-Internal-Token", "")
    if not settings.internal_service_token or not hmac.compare_digest(
        token, settings.internal_service_token
    ):
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
    client_host = websocket.client.host if websocket.client else "unknown"
    if not check_rate_limit(client_host):
        logger.warning(
            "Agent rate limit exceeded for IP: %s path: %s",
            client_host,
            websocket.url.path,
        )
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)


def enforce_rate_limit(client_host: str, path: str) -> None:
    # The app is behind Render's public ingress. Do not trust a raw forwarded
    # header; use the ASGI peer address unless trusted-proxy normalization is
    # explicitly configured and verified for this deployment.
    if not check_rate_limit(client_host):
        logger.warning(
            "Agent rate limit exceeded for IP: %s path: %s", client_host, path
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Maximum {settings.agent_rate_limit_rpm} requests per minute.",
            headers={"Retry-After": "60"},
        )
