"""Legacy direct side-effect routes must not bypass HITL in production."""

import pytest
from fastapi.testclient import TestClient

import state
from main import app


ROUTES = (
    ("/v1/agent/action", {"action_type": "send_email", "payload": {"to": "nobody@example.test"}}),
    ("/v1/agent/report", {"title": "T", "content": "C", "user_id": "u"}),
    ("/v1/agent/connector/ingest", {"source": "gmail", "user_id": "u", "params": {}}),
)


@pytest.mark.parametrize("path,body", ROUTES)
def test_direct_mutations_are_disabled_by_default_even_with_internal_token(monkeypatch, path, body):
    monkeypatch.setattr(state.settings, "app_env", "production")
    monkeypatch.setattr(state.settings, "internal_service_token", "route-test-secret")
    monkeypatch.setattr(state.settings, "allow_direct_mutation_demos", False)
    response = TestClient(app).post(path, json=body,
                                    headers={"X-Internal-Token": "route-test-secret"})
    assert response.status_code == 403
    assert "disabled" in response.json()["detail"].lower()


@pytest.mark.parametrize("path,body", ROUTES)
def test_production_override_cannot_reenable_direct_mutations(monkeypatch, path, body):
    monkeypatch.setattr(state.settings, "app_env", "production")
    monkeypatch.setattr(state.settings, "internal_service_token", "route-test-secret")
    monkeypatch.setattr(state.settings, "allow_direct_mutation_demos", True)
    response = TestClient(app).post(path, json=body,
                                    headers={"X-Internal-Token": "route-test-secret"})
    assert response.status_code == 403


def test_explicit_local_opt_in_keeps_report_demo_available(monkeypatch):
    class FakeReportAgent:
        async def generate_pdf_report(self, **_kwargs):
            return "/tmp/fake.pdf"

    import agents.report_agent as report_agent_module

    monkeypatch.setattr(state.settings, "app_env", "test")
    monkeypatch.setattr(state.settings, "allow_direct_mutation_demos", True)
    monkeypatch.setattr(report_agent_module, "ReportAgent", FakeReportAgent)
    response = TestClient(app).post(
        "/v1/agent/report", json={"title": "T", "content": "C", "user_id": "u"}
    )
    assert response.status_code == 200
    assert response.json()["report_path"] == "/tmp/fake.pdf"
