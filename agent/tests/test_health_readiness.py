import pytest
from fastapi.testclient import TestClient

import state
from main import app


class _ReadyMemory:
    _pool = object()  # truthy pool object => PostgreSQL connected


class _FallbackMemory:
    _pool = False  # PostgreSQL unavailable, in-memory fallback active


def _set_ready_state(monkeypatch):
    monkeypatch.setattr(state, "_workflow", object())
    monkeypatch.setattr(state, "_long_term_memory", _ReadyMemory())
    monkeypatch.setattr(state, "_graph_memory", _ReadyMemory())
    monkeypatch.setattr(state, "_rate_limiter", object())
    monkeypatch.setattr(state, "_a2a_hub", object())
    monkeypatch.setattr(state, "_mcp_server", object())


def test_health_liveness_always_200():
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_degraded_when_workflow_missing(monkeypatch):
    _set_ready_state(monkeypatch)
    monkeypatch.setattr(state, "_workflow", None)

    response = TestClient(app, raise_server_exceptions=False).get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["components"]["workflow"] == "unavailable"
    assert any("workflow" in e for e in body["errors"])


def test_readiness_degraded_on_memory_fallback(monkeypatch):
    _set_ready_state(monkeypatch)
    monkeypatch.setattr(state, "_long_term_memory", _FallbackMemory())
    monkeypatch.setattr(state, "_graph_memory", _FallbackMemory())

    response = TestClient(app, raise_server_exceptions=False).get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["components"]["long_term_memory"] == "degraded_in_memory_fallback"
    assert body["components"]["graph_memory"] == "degraded_in_memory_fallback"


def test_readiness_degraded_when_llm_missing(monkeypatch):
    _set_ready_state(monkeypatch)
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("langchain_ollama") or name.startswith("langchain_community"):
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    response = TestClient(app, raise_server_exceptions=False).get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["components"]["llm"] == "unavailable"
    assert any("llm" in e for e in body["errors"])


def test_readiness_ok_when_all_components_ready(monkeypatch):
    _set_ready_state(monkeypatch)

    response = TestClient(app, raise_server_exceptions=False).get("/ready")

    # LLM component may legitimately report unavailable in this env; but
    # when LangChain is installed the whole readiness is ok.
    body = response.json()
    if body["components"].get("llm") == "ok":
        assert response.status_code == 200
        assert body["status"] == "ok"
    else:
        assert response.status_code == 503
        assert body["components"]["llm"] == "unavailable"
        assert all(
            v == "ok" for k, v in body["components"].items() if k != "llm"
        )


def test_readiness_healthy_with_allowed_memory_fallback(monkeypatch):
    _set_ready_state(monkeypatch)
    monkeypatch.setattr(state, "_long_term_memory", _FallbackMemory())
    monkeypatch.setattr(state, "_graph_memory", _FallbackMemory())
    monkeypatch.setenv("ALLOW_MEMORY_FALLBACK", "true")

    response = TestClient(app, raise_server_exceptions=False).get("/ready")
    body = response.json()
    assert body["components"]["long_term_memory"] == "healthy_local_fallback"
    assert body["components"]["graph_memory"] == "healthy_local_fallback"
    if body["components"].get("llm") == "ok":
        assert response.status_code == 200
        assert body["status"] == "ok"

