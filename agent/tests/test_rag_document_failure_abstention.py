from unittest.mock import AsyncMock, Mock

import pytest

from agents.rag_agent import RagAgent


@pytest.mark.asyncio
async def test_missing_selected_collection_abstains_without_general_knowledge():
    agent = object.__new__(RagAgent)
    agent._long_term_memory = Mock(ensure_table=AsyncMock(), retrieve=AsyncMock(return_value=[]))
    agent._memory = Mock(get_recent=Mock(return_value=[]), add=Mock())
    agent._summarizer = Mock(compress=AsyncMock(return_value=[]), get_summary=Mock(return_value=""))
    agent._retrieve = AsyncMock(return_value=([], 0.0))
    agent._crag_loop = AsyncMock(return_value=([], 0.0))
    agent._deep_reasoning_fallback = AsyncMock(return_value="The capital is Paris")
    agent._turn_counters = {}

    result = await agent.run({"query": "What is the capital of France?", "session_id": "test",
                              "user_id": "alice", "document_ids": ["999999999"],
                              "use_web_search": False})

    assert "Paris" not in result["final_answer"]
    assert "document" in result["final_answer"].lower()
    assert result["sources"] == []
    assert result["answer_origin"] == "abstention"
    agent._deep_reasoning_fallback.assert_not_awaited()
