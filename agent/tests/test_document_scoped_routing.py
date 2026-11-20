import json

import pytest

from agents.orchestrator import OrchestratorAgent


@pytest.mark.asyncio
async def test_document_scoped_question_cannot_route_to_web_research(monkeypatch):
    class Model:
        async def ainvoke(self, messages):
            return type("Response", (), {"content": json.dumps({
                "intent": "research", "plan": "Search the web"
            })})()

    monkeypatch.setattr("agents.orchestrator.LLMFactory.get_reasoning_model", lambda **kwargs: Model())
    agent = OrchestratorAgent()
    result = await agent.run({"query": "What is the capital of France?", "document_ids": ["42"],
                              "use_web_search": False})
    assert result["agent_type"] == "rag"


@pytest.mark.asyncio
async def test_explicit_web_search_keeps_research_route(monkeypatch):
    class Model:
        async def ainvoke(self, messages):
            return type("Response", (), {"content": '{"intent":"research","plan":"Search"}'})()

    monkeypatch.setattr("agents.orchestrator.LLMFactory.get_reasoning_model", lambda **kwargs: Model())
    result = await OrchestratorAgent().run({"query": "Search web", "document_ids": ["42"],
                                            "use_web_search": True})
    assert result["agent_type"] == "research"


@pytest.mark.asyncio
async def test_document_question_cannot_become_report(monkeypatch):
    class Model:
        async def ainvoke(self, messages):
            return type("Response", (), {"content": '{"intent":"report","plan":"Write report"}'})()

    monkeypatch.setattr("agents.orchestrator.LLMFactory.get_reasoning_model", lambda **kwargs: Model())
    result = await OrchestratorAgent().run({
        "query": "According to the selected documents, what is the capital of France?",
        "document_ids": ["42"], "use_web_search": False})
    assert result["agent_type"] == "rag"
