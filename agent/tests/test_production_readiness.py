"""Production readiness tests for the agent service (P1.4, P1.5).

Covers:
  * P1.4 — LangGraph shared checkpointer: when DATABASE_URL names a Postgres
    URL and LANGGRAPH_CHECKPOINT_SHARED_REQUIRED=1, the workflow must compile
    with AsyncPostgresSaver (fail closed: no silent SQLite fallback).
  * P1.5 — HITL fail-closed: when Redis is unreachable and HITL_FAIL_CLOSED=true,
    the hitl_gate node blocks the action (HITLStoreUnavailable).

Heavy agent deps are stubbed via sys.modules. For P1.5, Settings fields are
overridden directly on the settings object (env-var reload is unreliable in
pytest), so no global os.environ pollution.
"""

import importlib
import os
import sys
import types

import pytest

# ---------------------------------------------------------------------------
# Stub heavy agent modules so graph.workflow imports cleanly.
# ---------------------------------------------------------------------------
def _stub_agent_modules():
    stubs = {
        "adk_runtime": types.ModuleType("adk_runtime"),
        "agents": types.ModuleType("agents"),
        "agents.orchestrator": types.ModuleType("agents.orchestrator"),
        "agents.rag_agent": types.ModuleType("agents.rag_agent"),
        "agents.report_agent": types.ModuleType("agents.report_agent"),
        "agents.comparator_agent": types.ModuleType("agents.comparator_agent"),
        "agents.researcher_agent": types.ModuleType("agents.researcher_agent"),
        "agents.action_agent": types.ModuleType("agents.action_agent"),
        "agents.engineering_analysis_agent": types.ModuleType(
            "agents.engineering_analysis_agent"),
        "graph.state": types.ModuleType("graph.state"),
        "llm_factory": types.ModuleType("llm_factory"),
        "memory.long_term": types.ModuleType("memory.long_term"),
        "memory.graph_memory": types.ModuleType("memory.graph_memory"),
        "rate_limiter": types.ModuleType("rate_limiter"),
    }
    for name, mod in stubs.items():
        if name not in sys.modules:
            sys.modules[name] = mod

    stubs["agents.orchestrator"].OrchestratorAgent = type(
        "OrchestratorAgent", (), {"run": lambda self, state: state})
    stubs["agents.rag_agent"].RagAgent = type(
        "RagAgent", (), {"run": lambda self, state: state})
    stubs["agents.report_agent"].ReportAgent = type(
        "ReportAgent", (), {"run": lambda self, state: state})
    stubs["agents.comparator_agent"].ComparatorAgent = type(
        "ComparatorAgent", (), {"run": lambda self, state: state})
    stubs["agents.researcher_agent"].ResearcherAgent = type(
        "ResearcherAgent", (), {"run": lambda self, state: state})
    stubs["agents.action_agent"].ActionAgent = type(
        "ActionAgent", (), {"run": lambda self, state: state})
    stubs["agents.engineering_analysis_agent"].EngineeringAnalysisAgent = type(
        "EngineeringAnalysisAgent", (), {"run": lambda self, state: state})
    stubs["graph.state"].AgentState = dict

    class _DummyLongTermMemory:
        async def ensure_table(self):
            pass

        async def ensure_turn_table(self):
            pass

    stubs["memory.long_term"].LongTermMemory = _DummyLongTermMemory

    class _DummyGraphMemory:
        async def ensure_tables(self):
            pass

        async def _get_pool(self):
            return None

    stubs["memory.graph_memory"].GraphMemory = _DummyGraphMemory

    class _DummyRateLimiter:
        def __init__(self, settings):
            pass

    stubs["rate_limiter"].RateLimiter = _DummyRateLimiter
    stubs["adk_runtime"].run_demo_workflow = lambda user_request, document_name: {
        "summary": "stubbed"}


_stub_agent_modules()


def _import_workflow_with_postgres(monkeypatch):
    """Force local env + Postgres DATABASE_URL + SHARED_REQUIRED=1."""
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "x" * 32)
    monkeypatch.setenv("POSTGRES_PASSWORD", "x" * 12)
    monkeypatch.setenv("AGENT_ALLOWED_ORIGINS", "https://example.com")
    monkeypatch.setenv("DATABASE_URL",
                       "postgresql://postgres:postgres@localhost:5432/smartdoc_test")
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT_SHARED_REQUIRED", "1")
    import graph.workflow as wf
    return wf


def test_postgres_checkpointer_selected_when_shared_required(monkeypatch):
    """P1.4: DATABASE_URL (Postgres) + SHARED_REQUIRED → Postgres checkpointer."""
    wf = _import_workflow_with_postgres(monkeypatch)

    class _FakeHandle:
        saver = types.SimpleNamespace()
        loop = None
        closed = False

        def close(self):
            self.closed = True

    orig = wf._connect_postgres_once

    def _fake(url, target):
        return _FakeHandle()

    monkeypatch.setattr(wf, "_connect_postgres_once", _fake)

    try:
        saver = wf._build_checkpointer()
        assert saver is not None
        assert wf._shared_required() is True
    finally:
        monkeypatch.setattr(wf, "_connect_postgres_once", orig)
        wf.close_checkpointers()


def test_postgres_checkpointer_missing_driver_fails_closed(monkeypatch):
    """P1.4: SHARED_REQUIRED=1 + missing driver → error, no SQLite fallback."""
    wf = _import_workflow_with_postgres(monkeypatch)

    import builtins
    real_import = builtins.__import__

    def _no_postgres_saver(name, *args, **kwargs):
        if name == "langgraph.checkpoint.postgres.aio":
            raise ImportError("No module named 'langgraph.checkpoint.postgres'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_postgres_saver)

    try:
        with pytest.raises((wf.SharedCheckpointUnavailable, ImportError,
                            RuntimeError)):
            wf._build_checkpointer()
    finally:
        wf.close_checkpointers()


# ---------------------------------------------------------------------------
# P1.5 — HITL fail-closed (override settings directly; env-var reload is
# unreliable under pytest because pydantic-settings caches env-file reads).
# ---------------------------------------------------------------------------
def _configure_hitl_production(hitl):
    """Flip hitl settings into production/fail-closed/redis mode."""
    hitl.settings.app_env = "production"
    hitl.settings.hitl_fail_closed = True
    hitl.settings.hitl_store_backend = "redis"
    hitl.settings.redis_url = "rediss://localhost:6379/0"
    hitl.hitl_store = hitl.build_hitl_store()


def test_hitl_fail_closed_when_redis_down(monkeypatch):
    """P1.5: HITL_FAIL_CLOSED=true + redis missing → RuntimeError, no fallback."""
    import hitl
    _configure_hitl_production(hitl)

    import builtins
    real_import = builtins.__import__

    def _no_redis(name, *args, **kwargs):
        if name == "redis.asyncio":
            raise ImportError("No module named 'redis.asyncio'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_redis)

    try:
        with pytest.raises(RuntimeError):
            hitl.build_hitl_store()
    finally:
        wf_close = getattr(hitl, "close_checkpointers", None)
        if wf_close:
            wf_close()


def test_hitl_gate_blocks_action_when_store_unavailable(monkeypatch):
    """P1.5: hitl_gate_node must not let an action execute when store is down."""
    import hitl
    _configure_hitl_production(hitl)

    import graph.workflow as wf
    from hitl import HITLStoreUnavailable

    orig_create = wf.hitl_store.create

    async def _unavailable(*args, **kwargs):
        raise HITLStoreUnavailable("Redis down")

    monkeypatch.setattr(wf.hitl_store, "create", _unavailable)

    try:
        import asyncio
        state = {"query": "send email", "session_id": "s", "user_id": "u",
                 "agent_plan": "", "document_ids": [],
                 "hitl_auto_approved": False}
        result = asyncio.run(wf.hitl_gate_node(state))
        assert result["hitl_pending"] is True
        assert result["hitl_approval_id"] is None
        assert result["action_result"]["status"] == "store_unavailable"
        assert "KHÔNG được thực thi" in result["final_answer"]
    finally:
        monkeypatch.setattr(wf.hitl_store, "create", orig_create)
        wf.close_checkpointers()
