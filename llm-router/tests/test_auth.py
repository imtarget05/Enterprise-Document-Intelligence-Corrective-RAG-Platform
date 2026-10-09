import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Settings
from app.main import create_app


class NoopRouter:
    async def close(self):
        pass


def _client(internal_token):
    settings = Settings(internal_token=internal_token)
    return TestClient(create_app(app_settings=settings, router=NoopRouter()))


def test_protected_http_routes_reject_missing_token_when_configured():
    client = _client("router-test-secret")

    for method, path in (
        ("POST", "/classify"),
        ("POST", "/extract"),
        ("POST", "/document/workflow"),
        ("POST", "/agent/invoke"),
        ("POST", "/agent/jobs"),
        ("GET", "/agent/jobs/not-a-real-job"),
        ("POST", "/api/chat"),
        ("POST", "/api/embeddings"),
    ):
        response = client.request(method, path, json={})
        assert response.status_code == 401, path


def test_protected_http_routes_reject_incorrect_token():
    response = _client("router-test-secret").post(
        "/classify", json={}, headers={"X-Internal-Token": "wrong"}
    )

    assert response.status_code == 401


def test_protected_http_routes_fail_closed_when_token_is_unset():
    response = _client("").post("/classify", json={})

    assert response.status_code == 401


def test_production_settings_require_internal_token():
    with pytest.raises(ValueError, match="ROUTER_INTERNAL_TOKEN must be set"):
        Settings(app_env="production", internal_token="")


def test_protected_http_route_accepts_valid_token():
    response = _client("router-test-secret").post(
        "/classify",
        json={"text": "purchase order", "filename": "order.txt"},
        headers={"X-Internal-Token": "router-test-secret"},
    )

    assert response.status_code == 200


def test_router_websocket_rejects_before_accept_without_token():
    client = _client("router-test-secret")

    with pytest.raises(WebSocketDisconnect) as disconnect:
        with client.websocket_connect("/ws/agent/not-a-real-job"):
            raise AssertionError("unauthenticated websocket was accepted")
    assert disconnect.value.code == 1008


def test_router_websocket_accepts_valid_token():
    client = _client("router-test-secret")

    with client.websocket_connect(
        "/ws/agent/not-a-real-job",
        headers={"X-Internal-Token": "router-test-secret"},
    ) as websocket:
        assert websocket.receive_json() == {"error": "job_not_found"}
