from fastapi.testclient import TestClient

from main import app


def test_report_endpoint_calls_generate_pdf_report_with_valid_signature(monkeypatch):
    captured = {}

    class FakeReportAgent:
        async def generate_pdf_report(self, title: str, content: str, user_id: str) -> str:
            captured["title"] = title
            captured["content"] = content
            captured["user_id"] = user_id
            return "/tmp/fake_report.pdf"

    import agents.report_agent as report_agent_mod

    monkeypatch.setattr(report_agent_mod, "ReportAgent", FakeReportAgent)

    client = TestClient(app)
    response = client.post(
        "/v1/agent/report",
        json={"title": "T", "content": "Some body", "user_id": "u1"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "report_path": "/tmp/fake_report.pdf"}
    assert captured == {"title": "T", "content": "Some body", "user_id": "u1"}
