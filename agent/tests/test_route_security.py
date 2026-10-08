import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import state
from main import app


PROTECTED_ROUTES = [
    ("GET", "/v1/mcp/info", None),
    ("GET", "/v1/mcp/tools", None),
    ("POST", "/v1/mcp/call", {}),
    ("GET", "/v1/mcp/stats", None),
    ("GET", "/v1/a2a/agents", None),
    ("GET", "/v1/a2a/agents/rag", None),
    ("POST", "/v1/a2a/delegate", {}),
    ("GET", "/v1/a2a/stats", None),
    ("GET", "/v1/agent/memory/graph/stats", None),
    ("POST", "/v1/agent/memory/graph/extract", {}),
    ("GET", "/v1/agent/memory/graph/entity/person", None),
    ("GET", "/v1/agent/memory/graph/related/person", None),
    ("GET", "/v1/agent/memory/graph/path", None),
    ("GET", "/v1/agent/memory/graph/session/session-1", None),
    ("GET", "/v1/agent/memory/graph/search?query=person", None),
    ("POST", "/v1/agent/adk/demo", {"user_request": "summarize"}),
]


def _request(client, method, path, json_body=None, headers=None):
    return client.request(method, path, json=json_body, headers=headers or {})


def test_sensitive_route_groups_reject_requests_without_internal_token(monkeypatch):
    monkeypatch.setattr(state.settings, "app_env", "production")
    monkeypatch.setattr(state.settings, "internal_service_token", "route-test-secret")
    client = TestClient(app)

    for method, path, body in PROTECTED_ROUTES:
        response = _request(client, method, path, body)
        assert response.status_code == 401, path


def test_sensitive_route_groups_reject_incorrect_internal_token(monkeypatch):
    monkeypatch.setattr(state.settings, "app_env", "production")
    monkeypatch.setattr(state.settings, "internal_service_token", "route-test-secret")
    client = TestClient(app)

    for method, path, body in PROTECTED_ROUTES:
        response = _request(
            client, method, path, body, headers={"X-Internal-Token": "wrong"}
        )
        assert response.status_code == 401, path


def test_unset_agent_internal_token_fails_closed(monkeypatch):
    monkeypatch.setattr(state.settings, "app_env", "production")
    monkeypatch.setattr(state.settings, "internal_service_token", "")

    response = TestClient(app).get("/v1/mcp/info")

    assert response.status_code == 401


def test_sensitive_route_groups_apply_rate_limit(monkeypatch):
    class DenyAllRateLimiter:
        @staticmethod
        def is_allowed(_key):
            return False

    monkeypatch.setattr(state.settings, "app_env", "production")
    monkeypatch.setattr(state.settings, "internal_service_token", "route-test-secret")
    monkeypatch.setattr(state, "_rate_limiter", DenyAllRateLimiter())

    client = TestClient(app)
    for method, path, body in PROTECTED_ROUTES:
        response = _request(
            client,
            method,
            path,
            body,
            headers={"X-Internal-Token": "route-test-secret"},
        )
        assert response.status_code == 429, path


def test_http_rate_limit_ignores_untrusted_forwarded_ip(monkeypatch):
    observed_keys = []

    class RecordingRateLimiter:
        @staticmethod
        def is_allowed(key):
            observed_keys.append(key)
            return True

    class MCPServerStub:
        @staticmethod
        def get_server_info():
            return {"status": "ready"}

    monkeypatch.setattr(state.settings, "app_env", "production")
    monkeypatch.setattr(state.settings, "internal_service_token", "route-test-secret")
    monkeypatch.setattr(state, "_rate_limiter", RecordingRateLimiter())
    monkeypatch.setattr(state, "_mcp_server", MCPServerStub())

    response = TestClient(app).get(
        "/v1/mcp/info",
        headers={
            "X-Internal-Token": "route-test-secret",
            "X-Forwarded-For": "198.51.100.200, 203.0.113.24",
        },
    )

    assert response.status_code == 200
    assert observed_keys == ["testclient"]


def test_websocket_rate_limit_ignores_untrusted_forwarded_ip(monkeypatch):
    observed_keys = []

    class RecordingRateLimiter:
        @staticmethod
        def is_allowed(key):
            observed_keys.append(key)
            return True

    monkeypatch.setattr(state.settings, "app_env", "production")
    monkeypatch.setattr(state.settings, "internal_service_token", "route-test-secret")
    monkeypatch.setattr(state, "_rate_limiter", RecordingRateLimiter())

    client = TestClient(app)
    with client.websocket_connect(
        "/ws/test-session",
        headers={
            "X-Internal-Token": "route-test-secret",
            "X-Forwarded-For": "198.51.100.200, 203.0.113.24",
        },
    ) as websocket:
        websocket.close()

    assert observed_keys == ["testclient"]


def test_valid_internal_token_reaches_protected_route(monkeypatch):
    class MCPServerStub:
        @staticmethod
        def get_server_info():
            return {"status": "ready"}

    monkeypatch.setattr(state.settings, "app_env", "production")
    monkeypatch.setattr(state.settings, "internal_service_token", "route-test-secret")
    monkeypatch.setattr(state, "_mcp_server", MCPServerStub())

    response = TestClient(app).get(
        "/v1/mcp/info", headers={"X-Internal-Token": "route-test-secret"}
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_agent_websocket_rejects_before_accept_without_token(monkeypatch):
    monkeypatch.setattr(state.settings, "app_env", "production")
    monkeypatch.setattr(state.settings, "internal_service_token", "route-test-secret")
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as disconnect:
        with client.websocket_connect("/ws/test-session"):
            raise AssertionError("unauthenticated websocket was accepted")
    assert disconnect.value.code == 1008


def test_agent_websocket_rate_limits_before_accept(monkeypatch):
    class DenyAllRateLimiter:
        @staticmethod
        def is_allowed(_key):
            return False

    monkeypatch.setattr(state.settings, "app_env", "production")
    monkeypatch.setattr(state.settings, "internal_service_token", "route-test-secret")
    monkeypatch.setattr(state, "_rate_limiter", DenyAllRateLimiter())
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as disconnect:
        with client.websocket_connect(
            "/ws/test-session", headers={"X-Internal-Token": "route-test-secret"}
        ):
            raise AssertionError("rate-limited websocket was accepted")
    assert disconnect.value.code == 1008
