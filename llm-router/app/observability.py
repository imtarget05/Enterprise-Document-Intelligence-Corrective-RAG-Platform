"""Langfuse tracing glue for the llm-router (FastAPI).

Phase 2 of the observability plan: the Spring Boot backend starts a trace and
propagates its id via the ``X-Langfuse-Trace-Id`` header (see LangfuseService
in the backend). This module joins those Python-side spans to the same trace
so a single request shows both the Java and Python tiers in one tree.

Opt-in: when ``LANGFUSE_PUBLIC_KEY`` / ``LANGFUSE_SECRET_KEY`` are unset the
client is disabled and every helper is a no-op — zero overhead in local/dev
and in staging Render when observability is not configured.

We use the low-level ``langfuse`` client and create observations explicitly so
we can attach the incoming ``trace_id`` as the parent. (The ``@observe``
decorator would start a *new* trace; here we must attach to the backend's.)
"""

from __future__ import annotations

import os
from typing import Any

try:
    from langfuse import Langfuse
except ImportError:
    Langfuse = None

PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
HOST = os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL") or "https://cloud.langfuse.com"

TRACE_HEADER = "X-Langfuse-Trace-Id"

_client: Any = None

if PUBLIC_KEY and SECRET_KEY and Langfuse is not None:
    try:
        _client = Langfuse(public_key=PUBLIC_KEY, secret_key=SECRET_KEY, host=HOST)
    except Exception:  # pragma: no cover - network/env issues must not crash the router
        _client = None


def enabled() -> bool:
    return _client is not None


def trace_id_from_headers(headers: dict[str, str]) -> str | None:
    """Extract the backend-originated trace id from incoming request headers."""
    return headers.get(TRACE_HEADER) or headers.get(TRACE_HEADER.lower())


def generation(
    trace_id: str | None,
    name: str,
    model: str,
    parent_observation_id: str | None = None,
    input: Any = None,
    metadata: dict[str, Any] | None = None,
) -> str | None:
    """Create a generation observation joined to the incoming trace."""
    if _client is None or trace_id is None:
        return None
    try:
        _client.generation(
            trace_id=trace_id,
            name=name,
            model=model,
            parent_observation_id=parent_observation_id,
            input=input,
            metadata=metadata or {},
        )
        return name
    except Exception:
        return None


def update_generation(
    trace_id: str | None,
    name: str,
    output: Any = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    if _client is None or trace_id is None:
        return
    try:
        _client.generation(
            trace_id=trace_id,
            name=name,
            output=output,
            metadata=metadata or {},
        )
    except Exception:
        pass


def span(
    trace_id: str | None,
    name: str,
    parent_observation_id: str | None = None,
    input: Any = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[str | None, Any]:
    """Create a span observation joined to the incoming trace.

    Returns (observation_id, span_client) — both may be None when tracing is
    disabled or no trace id was propagated. Use the returned client to ``end``
    the span with output/error info.
    """
    if _client is None or trace_id is None:
        return None, None
    try:
        obs = _client.span(
            trace_id=trace_id,
            name=name,
            parent_observation_id=parent_observation_id,
            input=input,
            metadata=metadata or {},
        )
        return getattr(obs, "id", name), obs
    except Exception:
        return None, None


def end_span(span_client: Any, output: Any = None, error: str | None = None) -> None:
    if span_client is None:
        return
    try:
        span_client.end(output=output, level="ERROR" if error else "DEFAULT",
                        status_message=error or None)
    except Exception:
        pass


def flush() -> None:
    if _client is not None:
        try:
            _client.flush()
        except Exception:
            pass
